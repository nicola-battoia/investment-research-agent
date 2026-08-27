"""Request-local source IDs and retrieved passage ownership."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from app.assistant.outputs import PassagePreview, ReadablePassage
from app.config import settings
from app.retrieval.models import SourcePassage


class EvidenceLimitError(Exception):
    """The current assistant turn has reached its evidence bound."""


class UnknownSourceError(Exception):
    """The model requested a source that was not retrieved in this turn."""


@dataclass
class TurnEvidence:
    """Mutable evidence belongs to exactly one request-scoped assistant run."""

    max_passages: int = settings.assistant_max_turn_evidence
    _by_source_id: dict[str, SourcePassage] = field(default_factory=dict)
    _source_id_by_chunk: dict[UUID, str] = field(default_factory=dict)
    _read_source_ids: set[str] = field(default_factory=set)

    def register(self, passage: SourcePassage) -> str:
        existing = self._source_id_by_chunk.get(passage.chunk_id)
        if existing is not None:
            return existing
        if len(self._by_source_id) >= self.max_passages:
            raise EvidenceLimitError(
                f"A turn can register at most {self.max_passages} passages"
            )
        source_id = f"S{len(self._by_source_id) + 1}"
        self._by_source_id[source_id] = passage
        self._source_id_by_chunk[passage.chunk_id] = source_id
        return source_id

    def require(self, source_id: str) -> SourcePassage:
        try:
            return self._by_source_id[source_id]
        except KeyError as error:
            raise UnknownSourceError(
                f"{source_id!r} is not evidence retrieved during this turn"
            ) from error

    def source_id_for(self, passage: SourcePassage) -> str:
        return self.register(passage)

    @property
    def passages(self) -> dict[str, SourcePassage]:
        return dict(self._by_source_id)

    @property
    def read_source_ids(self) -> frozenset[str]:
        return frozenset(self._read_source_ids)

    @property
    def is_empty(self) -> bool:
        return not self._by_source_id

    def preview(self, passage: SourcePassage) -> PassagePreview:
        text = " ".join(passage.text.split())
        if len(text) > settings.assistant_evidence_preview_characters:
            text = text[: settings.assistant_evidence_preview_characters].rstrip() + "…"
        return PassagePreview(
            source_id=self.source_id_for(passage),
            passage_kind=passage.passage_kind,
            company=passage.company,
            ticker=passage.ticker,
            filing_type=passage.filing_type,
            filing_date=passage.filing_date,
            report_date=passage.report_date,
            accession_number=passage.accession_number,
            chunk_index=passage.chunk_index,
            page_number=passage.page_number,
            section_title=passage.section_title,
            preview=text,
        )

    def readable(self, passage: SourcePassage) -> ReadablePassage:
        source_id = self.source_id_for(passage)
        self._read_source_ids.add(source_id)
        return ReadablePassage(
            source_id=source_id,
            passage_kind=passage.passage_kind,
            company=passage.company,
            ticker=passage.ticker,
            filing_type=passage.filing_type,
            filing_date=passage.filing_date,
            report_date=passage.report_date,
            accession_number=passage.accession_number,
            sec_url=passage.sec_url,
            chunk_index=passage.chunk_index,
            page_number=passage.page_number,
            section_title=passage.section_title,
            text=passage.text,
        )
