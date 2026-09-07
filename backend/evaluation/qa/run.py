"""Run real authenticated FastAPI/SSE turns and retain failures as QA results."""

import argparse
import json
import subprocess
import time
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import settings
from evaluation.qa.dataset import (
    DEFAULT_DATASET,
    GoldenCase,
    digest,
    evidence_recall,
    load_dataset,
    minimum_calls,
    validate_evidence,
)
from evaluation.qa.identity import temporary_identity
from evaluation.qa.storage import (
    finish_run,
    read_corpus,
    save_result,
    seed_dataset,
    start_run,
    write_report,
)
from evaluation.qa.trace import ReportTrace, evidence_from_trace


def parse_sse(text: str) -> list[dict]:
    return [
        json.loads(line[6:])
        for line in text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


def configuration(cases: list[str]) -> dict:
    safe = {
        key: value
        for key, value in settings.model_dump(mode="json").items()
        if key.startswith(("assistant_", "retrieval_", "chat_", "openai_"))
        or key
        in {
            "azure_openai_assistant_deployment",
            "azure_openai_keyword_deployment",
            "azure_openai_embedding_deployment",
        }
    }
    root = Path(__file__).parents[2]
    code_snapshot = [
        (str(path.relative_to(root)), digest(path.read_text()))
        for folder in (root / "app", root / "evaluation/qa")
        for path in sorted(folder.rglob("*.py"))
    ]
    return {
        "settings": safe,
        "cases": cases,
        "evaluator_version": "1",
        "transport": "local FastAPI TestClient, real Supabase JWT, DB and Azure",
        "git_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "policy_sha256": digest(
            (Path(__file__).parents[2] / "app/assistant/policy.py").read_text()
        ),
        "code_sha256": digest(json.dumps(code_snapshot)),
    }


def run_case(
    client: TestClient, headers: dict, case: GoldenCase, rows: list[dict]
) -> dict:
    trace = ReportTrace()
    thread_response = client.post(
        "/chat/threads", headers=headers, json={"title": f"QA {case.code}"}
    )
    thread_response.raise_for_status()
    thread_id = thread_response.json()["id"]
    started = time.perf_counter()
    try:
        with patch("app.api.chat.AssistantTrace.create", return_value=trace):
            response = client.post(
                "/chat/stream",
                headers=headers,
                json={
                    "id": thread_id,
                    "message": {
                        "id": str(uuid4()),
                        "role": "user",
                        "parts": [{"type": "text", "text": case.question}],
                    },
                },
            )
        events = parse_sse(response.text) if response.status_code == 200 else []
        answer = "".join(e["delta"] for e in events if e["type"] == "text-delta")
        failures = [e["data"] for e in events if e["type"] == "data-turn-error"]
        finished = any(e["type"] == "finish" for e in events)
        citation_parts = [e for e in events if e["type"] == "data-citation"]
        loaded_response = client.get(f"/chat/threads/{thread_id}", headers=headers)
        loaded_response.raise_for_status()
        messages = loaded_response.json()["messages"]
        stored = [m for m in messages if m["role"] == "assistant"]
        stored_parts = stored[-1]["parts"] if stored else []
        stored_answer = "".join(p["text"] for p in stored_parts if p["type"] == "text")
        stored_citations = [p for p in stored_parts if p["type"] == "data-citation"]
        reloaded = (
            bool(stored)
            and answer == stored_answer
            and citation_parts == stored_citations
        )
        error = failures[0]["code"] if failures else None
        if response.status_code != 200:
            error = f"http_{response.status_code}"
        if not error and not (finished and answer and reloaded):
            error = "incomplete_or_reload_mismatch"
        evidence = evidence_from_trace(trace.events, rows)
        evidence["citations"] = citation_parts
        evidence["cited_chunk_ids"] = sorted(
            {str(p["data"]["chunkId"]) for p in citation_parts}
        )
        evaluation = {
            "retrieval": evidence_recall(case, set(evidence["retrieved_chunk_ids"])),
            "read": evidence_recall(case, set(evidence["read_chunk_ids"])),
            "citation": evidence_recall(case, set(evidence["cited_chunk_ids"])),
            "answer_quality": {
                "status": "not_assessed",
                "reason": "Use --judge for an advisory rubric score; human review is the release gate.",
            },
            "reload_matches": reloaded,
            "failed_turn_persisted": bool(error and stored),
            "minimum_calls": minimum_calls(case),
        }
        return {
            "code": case.code,
            "status": "failed" if error else "completed",
            "answer": answer,
            "error_code": error,
            "evidence": evidence,
            "evaluation": evaluation,
            "diagnostics": {
                "case_sha256": digest(case.model_dump_json()),
                "http_status": response.status_code,
                "seconds": round(time.perf_counter() - started, 2),
                "answer_status": stored[-1].get("metadata", {}).get("answerStatus")
                if stored
                else None,
                "sse_event_types": [e["type"] for e in events],
                "trace": trace.events,
            },
        }
    finally:
        deleted = client.delete(f"/chat/threads/{thread_id}", headers=headers)
        deleted.raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--cases", help="Comma-separated case codes; default all 15")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--judge", action="store_true")
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    rows = read_corpus()
    validate_evidence(dataset, rows)
    selected = (
        args.cases.split(",") if args.cases else [case.code for case in dataset.cases]
    )
    if set(selected) - {c.code for c in dataset.cases}:
        parser.error("Unknown case code")
    dataset_id, case_ids = seed_dataset(dataset)
    config = configuration(selected)
    run_id = start_run(dataset_id, config)
    report = {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "configuration": config,
        "results": [],
    }
    status = "interrupted"
    try:
        from app.main import app

        with TestClient(app, raise_server_exceptions=False) as client:
            for case in dataset.cases:
                if case.code not in selected:
                    continue
                print(f"Running {case.code}", flush=True)
                # A fresh account per case isolates history and avoids token expiry.
                with temporary_identity() as token:
                    result = run_case(
                        client, {"Authorization": f"Bearer {token}"}, case, rows
                    )
                if args.judge and result["status"] == "completed":
                    from evaluation.qa.judge import judge_answer

                    result["evaluation"]["answer_quality"] = judge_answer(
                        case, result, rows
                    )
                save_result(run_id, case_ids[case.code], result)
                report["results"].append(result)
                write_report(args.output, report)
                print(
                    f"{case.code}: {result['status']} {result['error_code']} ({result['diagnostics']['seconds']}s)",
                    flush=True,
                )
        status = "completed"
    finally:
        finish_run(run_id, status)
        report["status"] = status
        report["summary"] = summarize(report["results"], len(selected))
        write_report(args.output, report)
    if report["summary"]["execution_failures"] or (
        args.judge and report["summary"]["advisory_passes"] != len(selected)
    ):
        raise SystemExit(1)


def summarize(results: list[dict], selected_count: int) -> dict:
    completed = sum(r["status"] == "completed" for r in results)
    passes = sum(
        r["evaluation"]["answer_quality"].get("rubric_pass", False) for r in results
    )
    return {
        "selected": selected_count,
        "recorded": len(results),
        "execution_completed": completed,
        "execution_failures": sum(r["status"] != "completed" for r in results),
        "unrecorded": selected_count - len(results),
        "execution_completion_rate": completed / selected_count,
        "advisory_passes": passes,
        "advisory_pass_rate_all_selected": passes / selected_count,
        "human_acceptance": "pending",
    }


if __name__ == "__main__":
    main()
