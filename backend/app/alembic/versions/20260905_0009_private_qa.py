"""Add private versioned QA datasets and run history.

Revision ID: 20260905_0009
Revises: 20260823_0008
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260905_0009"
down_revision = "20260823_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA qa")
    op.execute("REVOKE ALL ON SCHEMA qa FROM PUBLIC, anon, authenticated, service_role")
    op.create_table(
        "datasets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("version", sa.String(80), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("corpus_fingerprint", sa.String(64), nullable=False),
        sa.Column("metadata", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("name", "version"),
        schema="qa",
    )
    op.create_table(
        "cases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "dataset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("qa.datasets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("gold_answer", sa.Text, nullable=False),
        sa.Column("evidence_groups", JSONB, nullable=False),
        sa.Column("rubric", JSONB, nullable=False),
        sa.UniqueConstraint("dataset_id", "code"),
        schema="qa",
    )
    op.create_table(
        "runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "dataset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("qa.datasets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("configuration", JSONB, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        schema="qa",
    )
    op.create_table(
        "results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("qa.runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            UUID(as_uuid=True),
            sa.ForeignKey("qa.cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("answer", sa.Text, nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("evidence", JSONB, nullable=False),
        sa.Column("diagnostics", JSONB, nullable=False),
        sa.Column("evaluation", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("run_id", "case_id", "attempt"),
        schema="qa",
    )
    for table in ("datasets", "cases", "runs", "results"):
        op.execute(f"ALTER TABLE qa.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"REVOKE ALL ON TABLE qa.{table} FROM PUBLIC, anon, authenticated, service_role"
        )
    # Dataset snapshots are append-only even for ordinary operator UPDATE/DELETE.
    op.execute("""
        CREATE FUNCTION qa.reject_dataset_mutation() RETURNS trigger
        LANGUAGE plpgsql SET search_path = '' AS $$
        BEGIN
          RAISE EXCEPTION 'QA datasets and cases are immutable; create a new version';
        END $$;
    """)
    for table in ("datasets", "cases"):
        op.execute(f"""
            CREATE TRIGGER immutable_snapshot BEFORE UPDATE OR DELETE ON qa.{table}
            FOR EACH ROW EXECUTE FUNCTION qa.reject_dataset_mutation()
        """)
    op.execute(
        "REVOKE ALL ON FUNCTION qa.reject_dataset_mutation() FROM PUBLIC, anon, authenticated, service_role"
    )


def downgrade() -> None:
    for table in ("results", "runs", "cases", "datasets"):
        op.drop_table(table, schema="qa")
    op.execute("DROP FUNCTION qa.reject_dataset_mutation()")
    op.execute("DROP SCHEMA qa")
