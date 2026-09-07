"""Direct operator-only SQL access; QA never enters the public data API."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import settings
from evaluation.qa.dataset import GoldenDataset, digest

CORPUS_SQL = """
SELECT d.accession_number, d.ticker, d.report_date, d.content_checksum,
       c.id AS chunk_id, c.chunk_index, c.text, c.token_count, c.section_title
FROM public.source_documents d JOIN public.document_chunks c ON c.document_id=d.id
ORDER BY d.accession_number, c.chunk_index
"""


@contextmanager
def connection(*, readonly: bool = False):
    url = settings.database_url.get_secret_value().replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(
        url,
        connect_timeout=15,
        row_factory=dict_row,
        options="-c statement_timeout=30000 -c lock_timeout=5000",
    ) as conn:
        if readonly:
            conn.execute("SET TRANSACTION READ ONLY")
        yield conn


def read_corpus() -> list[dict]:
    with connection(readonly=True) as conn:
        return conn.execute(CORPUS_SQL).fetchall()


def seed_dataset(dataset: GoldenDataset) -> tuple[str, dict[str, str]]:
    payload = dataset.model_dump(mode="json")
    checksum = digest(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    with connection() as conn:
        existing = conn.execute(
            "SELECT id,content_sha256 FROM qa.datasets WHERE name=%s AND version=%s",
            (dataset.name, dataset.version),
        ).fetchone()
        if existing:
            if existing["content_sha256"] != checksum:
                raise ValueError("Existing dataset version differs; use a new version")
            dataset_id = existing["id"]
        else:
            dataset_id = uuid4()
            conn.execute(
                "INSERT INTO qa.datasets (id,name,version,content_sha256,corpus_fingerprint,metadata) VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    dataset_id,
                    dataset.name,
                    dataset.version,
                    checksum,
                    dataset.corpus_fingerprint,
                    Jsonb(dataset.metadata),
                ),
            )
            for case in dataset.cases:
                conn.execute(
                    "INSERT INTO qa.cases (id,dataset_id,code,question,gold_answer,evidence_groups,rubric) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (
                        uuid4(),
                        dataset_id,
                        case.code,
                        case.question,
                        case.gold_answer,
                        Jsonb([g.model_dump() for g in case.evidence_groups]),
                        Jsonb(case.rubric),
                    ),
                )
        cases = conn.execute(
            "SELECT code,id FROM qa.cases WHERE dataset_id=%s", (dataset_id,)
        ).fetchall()
        return str(dataset_id), {row["code"]: str(row["id"]) for row in cases}


def start_run(dataset_id: str, configuration: dict) -> str:
    run_id = str(uuid4())
    with connection() as conn:
        conn.execute(
            "INSERT INTO qa.runs (id,dataset_id,configuration,status) VALUES (%s,%s,%s,'running')",
            (run_id, dataset_id, Jsonb(configuration)),
        )
    return run_id


def save_result(run_id: str, case_id: str, result: dict) -> None:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO qa.results (id,run_id,case_id,attempt,status,answer,error_code,evidence,diagnostics,evaluation)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
            (
                uuid4(),
                run_id,
                case_id,
                result.get("attempt", 1),
                result["status"],
                result.get("answer"),
                result.get("error_code"),
                Jsonb(result["evidence"]),
                Jsonb(result["diagnostics"]),
                Jsonb(result["evaluation"]),
            ),
        )


def finish_run(run_id: str, status: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE qa.runs SET status=%s,finished_at=%s WHERE id=%s",
            (status, datetime.now(UTC), run_id),
        )


def write_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
