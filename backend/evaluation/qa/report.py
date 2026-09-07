"""Render a saved QA run as a concise Markdown report."""

import argparse
import json
from pathlib import Path

from evaluation.qa.run import summarize


def render_report(report: dict) -> str:
    results = report["results"]
    summary = report.get("summary") or summarize(
        results, len(report["configuration"]["cases"])
    )
    lines = [
        "# Assistant QA run",
        "",
        f"Run: `{report['run_id']}`. Dataset: `{report['dataset_id']}`.",
        "",
        (
            f"Recorded {summary['recorded']}/{summary['selected']} cases. "
            f"Completed turns: {summary['execution_completed']}; execution failures: {summary['execution_failures']}; "
            f"advisory rubric passes: {summary['advisory_passes']}. Human acceptance remains pending."
        ),
        "",
        "Retrieval/read/citation percentages measure required evidence-group coverage, not answer accuracy.",
        "",
        "| Case | Outcome | Retrieved / read / cited | Advisory score | Seconds |",
        "|---|---|---|---|---:|",
    ]
    for result in results:
        evaluation = result["evaluation"]
        coverage = " / ".join(
            f"{evaluation[s]['recall']:.0%}" for s in ("retrieval", "read", "citation")
        )
        score = evaluation["answer_quality"].get("score")
        outcome = (
            result["error_code"]
            or result["diagnostics"].get("answer_status")
            or result["status"]
        )
        lines.append(
            f"| {result['code']} | `{outcome}` | {coverage} | {str(score) + '/10' if score is not None else 'Not assessed'} | {result['diagnostics']['seconds']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_report(json.loads(args.input.read_text())))


if __name__ == "__main__":
    main()
