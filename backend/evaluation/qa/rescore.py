"""Recompute evidence coverage from saved turns without new assistant calls.

Later input files take precedence for duplicate case codes. Questions must match
the selected immutable case version; this prevents silently mixing changed tasks.
"""

import argparse
import copy
import json
from pathlib import Path

from evaluation.qa.dataset import (
    DEFAULT_DATASET,
    evidence_recall,
    load_dataset,
    validate_evidence,
)
from evaluation.qa.run import summarize
from evaluation.qa.storage import (
    connection,
    finish_run,
    read_corpus,
    save_result,
    seed_dataset,
    start_run,
    write_report,
)
from evaluation.qa.trace import compact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    validate_evidence(dataset, read_corpus())
    reports = [json.loads(path.read_text()) for path in args.input]
    selected = {
        result["code"]: (report, result)
        for report in reports
        for result in report["results"]
    }
    missing = {c.code for c in dataset.cases} - selected.keys()
    if missing:
        raise ValueError(f"Missing cases: {sorted(missing)}")
    if any(
        r["configuration"]["settings"] != reports[0]["configuration"]["settings"]
        for r in reports
    ):
        raise ValueError("Cannot pool turns with different runtime settings")
    with connection(readonly=True) as conn:
        for case in dataset.cases:
            original, _ = selected[case.code]
            stored = conn.execute(
                "SELECT question,gold_answer FROM qa.cases WHERE dataset_id=%s AND code=%s",
                (original["dataset_id"], case.code),
            ).fetchone()
            if (
                stored is None
                or stored["question"] != case.question
                or stored["gold_answer"] != case.gold_answer
            ):
                raise ValueError(
                    f"{case.code}: task or gold answer changed; run it again instead of reusing a score"
                )
    dataset_id, case_ids = seed_dataset(dataset)
    config = {
        "kind": "evidence_rescore",
        "source_runs": [r["run_id"] for r in reports],
        "settings": reports[0]["configuration"]["settings"],
        "source_configurations": {r["run_id"]: r["configuration"] for r in reports},
        "selection": "Last supplied report wins for each case, independent of outcome",
        "new_assistant_calls": 0,
    }
    run_id = start_run(dataset_id, config)
    output = {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "configuration": config,
        "results": [],
    }
    status = "interrupted"
    try:
        for case in dataset.cases:
            original, old = selected[case.code]
            result = copy.deepcopy(old)
            result["diagnostics"]["trace"] = compact(result["diagnostics"]["trace"])
            result["diagnostics"]["source_run_id"] = original["run_id"]
            for stage in ("retrieval", "read", "citation"):
                field = {"retrieval": "retrieved", "read": "read", "citation": "cited"}[
                    stage
                ]
                result["evaluation"][stage] = evidence_recall(
                    case, set(result["evidence"][f"{field}_chunk_ids"])
                )
            result["evaluation"]["answer_quality_source_run_id"] = original["run_id"]
            save_result(run_id, case_ids[case.code], result)
            output["results"].append(result)
        status = "completed"
    finally:
        finish_run(run_id, status)
        output["status"] = status
        output["summary"] = summarize(output["results"], len(dataset.cases))
        write_report(args.output, output)
    print(json.dumps(output["summary"]))
    raise SystemExit(
        1 if output["summary"]["advisory_passes"] != len(dataset.cases) else 0
    )


if __name__ == "__main__":
    main()
