"""Summarize recorded QA traces without model calls or database writes."""

import argparse
import json
import re
from collections import Counter
from pathlib import Path


def passages(value):
    if isinstance(value, list):
        for item in value:
            yield from passages(item)
    elif isinstance(value, dict):
        if "accession_number" in value and "chunk_index" in value:
            yield value
        else:
            for item in value.values():
                yield from passages(item)


def analyze_case(result: dict) -> dict:
    events = result["diagnostics"]["trace"]
    responses = [e for e in events if e["stage"] == "assistant.model.response"]
    completed = [e for e in events if e["stage"] == "assistant.tool.completed"]
    searches = []
    returned_keys = []
    read_keys = []
    token_counts = {}
    for event in events:
        if event["stage"] == "retrieval.search.completed":
            for passage in passages(event.get("ranked_passages", [])):
                token_counts[(passage["accession_number"], passage["chunk_index"])] = (
                    passage.get("token_count")
                )
            for passage in passages(event.get("context_passages", [])):
                token_counts[(passage["accession_number"], passage["chunk_index"])] = (
                    passage.get("token_count")
                )
        if event["stage"] == "retrieval.surrounding.completed":
            for passage in passages(event.get("passages", [])):
                token_counts[(passage["accession_number"], passage["chunk_index"])] = (
                    passage.get("token_count")
                )
    started = {
        e["tool_call_id"]: e for e in events if e["stage"] == "assistant.tool.started"
    }
    for event in completed:
        found = list(passages(event.get("result", {})))
        keys = [(p["accession_number"], p["chunk_index"]) for p in found]
        if event["tool_name"] == "search_filings":
            searches.append(
                {
                    "arguments": started[event["tool_call_id"]]["arguments"],
                    "returned": len(keys),
                    "new_chunks": len(set(keys) - set(returned_keys)),
                    "filing_distribution": dict(
                        Counter(f"{p['ticker']}:{p['report_date'][:4]}" for p in found)
                    ),
                }
            )
            returned_keys.extend(keys)
        else:
            read_keys.extend(keys)

    # Trace usage is cumulative. Summing its input_tokens would count it repeatedly.
    previous = 0
    request_inputs = []
    for response in responses:
        request_inputs.append(response["input_tokens"] - previous)
        previous = response["input_tokens"]
    if any(value < 0 for value in request_inputs):
        raise ValueError("Expected monotonic cumulative assistant usage")
    failure = next((e for e in events if e["stage"] == "stream.failed"), {})
    projected = re.search(r"\(input_tokens=(\d+)\)", failure.get("error_message", ""))
    first_read = next(
        (e for e in completed if e["tool_name"] != "search_filings"), None
    )
    before_read = [
        e
        for e in responses
        if first_read and e["elapsed_ms"] < first_read["elapsed_ms"]
    ]
    known_read_tokens = [token_counts.get(key) for key in set(read_keys)]
    return {
        "code": result["code"],
        "outcome": result["error_code"] or result["diagnostics"]["answer_status"],
        "seconds": result["diagnostics"]["seconds"],
        "provider_input_tokens": previous,
        "provider_output_tokens": responses[-1]["output_tokens"] if responses else 0,
        "per_request_input_tokens": request_inputs,
        "projected_cumulative_input_at_stop": int(projected[1]) if projected else None,
        "provider_input_before_first_read": before_read[-1]["input_tokens"]
        if before_read
        else None,
        "model_responses": len(responses),
        "completed_tool_calls": len(completed),
        "tool_sequence": [e["tool_name"] for e in completed],
        "tool_failures": [
            {k: e.get(k) for k in ("tool_name", "error_message")}
            for e in events
            if e["stage"] == "assistant.tool.failed"
        ],
        "grounding_rejections": [
            e["reason"] for e in events if e["stage"] == "assistant.grounding.rejected"
        ],
        "searches": searches,
        "search_return_occurrences": len(returned_keys),
        "unique_search_chunks": len(set(returned_keys)),
        "repeated_search_return_occurrences": len(returned_keys)
        - len(set(returned_keys)),
        "read_occurrences": len(read_keys),
        "unique_read_chunks": len(set(read_keys)),
        "unique_read_corpus_tokens": sum(known_read_tokens)
        if all(v is not None for v in known_read_tokens)
        else None,
        "maximum_read_chunk_corpus_tokens": max(known_read_tokens, default=0)
        if all(v is not None for v in known_read_tokens)
        else None,
        "minimum_calls": result["evaluation"]["minimum_calls"],
        "evidence_recall": {
            key: result["evaluation"][key]["recall"]
            for key in ("retrieval", "read", "citation")
        },
        "advisory_quality": result["evaluation"]["answer_quality"],
        "failure": {
            key: failure[key]
            for key in (
                "error_code",
                "error_message",
                "failed_after_stage",
                "rate_limit_tokens",
                "rate_reset_tokens_ms",
                "retry_after_seconds",
            )
            if key in failure
        },
    }


def analyze_report(report: dict) -> dict:
    cases = [analyze_case(result) for result in report["results"]]
    return {
        "run_id": report["run_id"],
        "dataset_id": report["dataset_id"],
        "settings": report["configuration"]["settings"],
        "outcomes": dict(Counter(case["outcome"] for case in cases)),
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {
        "method": (
            "Difference consecutive cumulative provider usage for request inputs; "
            "keep the local projected stop estimate separate. Corpus chunk token "
            "counts exclude schemas, instructions, previews and replay overhead. "
            "Tools count completed calls separately from failed attempts. "
            "Advisory grades do not establish acceptance. No new model calls."
        ),
        "runs": [analyze_report(json.loads(path.read_text())) for path in args.input],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
