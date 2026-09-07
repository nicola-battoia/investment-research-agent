"""Private, versioned evaluation records; never part of the retrieval corpus."""

from datetime import datetime
from typing import ClassVar
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class QADataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("name", "version"), {"schema": "qa"})

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[str] = mapped_column(String(80))
    content_sha256: Mapped[str] = mapped_column(String(64))
    corpus_fingerprint: Mapped[str] = mapped_column(String(64))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class QACase(Base):
    __tablename__ = "cases"
    __table_args__ = (UniqueConstraint("dataset_id", "code"), {"schema": "qa"})

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("qa.datasets.id", ondelete="RESTRICT")
    )
    code: Mapped[str] = mapped_column(String(40))
    question: Mapped[str] = mapped_column(Text)
    gold_answer: Mapped[str] = mapped_column(Text)
    evidence_groups: Mapped[list] = mapped_column(JSONB)
    rubric: Mapped[dict] = mapped_column(JSONB)


class QARun(Base):
    __tablename__ = "runs"
    __table_args__: ClassVar[dict] = {"schema": "qa"}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("qa.datasets.id", ondelete="RESTRICT")
    )
    configuration: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(30))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class QAResult(Base):
    __tablename__ = "results"
    __table_args__ = (
        UniqueConstraint("run_id", "case_id", "attempt"),
        {"schema": "qa"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("qa.runs.id", ondelete="RESTRICT"))
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("qa.cases.id", ondelete="RESTRICT")
    )
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSONB)
    diagnostics: Mapped[dict] = mapped_column(JSONB)
    evaluation: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
