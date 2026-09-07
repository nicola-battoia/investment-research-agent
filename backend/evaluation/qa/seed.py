"""Validate current evidence and publish an immutable QA dataset snapshot."""

import argparse
from pathlib import Path

from evaluation.qa.dataset import DEFAULT_DATASET, load_dataset, validate_evidence
from evaluation.qa.storage import read_corpus, seed_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    validate_evidence(dataset, read_corpus())
    dataset_id, cases = seed_dataset(dataset)
    print(f"Validated {dataset.version}: {len(cases)} cases; dataset {dataset_id}")


if __name__ == "__main__":
    main()
