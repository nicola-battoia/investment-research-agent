"""Versioned, presentation-only table data derived from Docling chunks."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StoredTableCell(BaseModel):
    """One Docling origin cell and its location in canonical chunk text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    column_index: int = Field(ge=0)
    row_span: int = Field(gt=0)
    column_span: int = Field(gt=0)
    column_header: bool = False
    row_header: bool = False
    text_start: int | None = Field(default=None, ge=0)
    text_end: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_text_range(self) -> Self:
        if (self.text_start is None) != (self.text_end is None):
            raise ValueError("Table cell text offsets must both be present or absent")
        if (
            self.text_start is not None
            and self.text_end is not None
            and self.text_end <= self.text_start
        ):
            raise ValueError("Table cell text end must be after its start")
        if not self.text and self.text_start is not None:
            raise ValueError("Empty table cells cannot have text offsets")
        if self.text and self.text_start is None:
            raise ValueError("Non-empty table cells require text offsets")
        return self


class StoredTableRow(BaseModel):
    """Origin cells that start in one physical Docling row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cells: tuple[StoredTableCell, ...] = ()


class StoredDisplayTable(BaseModel):
    """Lossless table geometry used only to render and highlight citations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    table_ref: str = Field(min_length=1)
    column_count: int = Field(gt=0)
    rows: tuple[StoredTableRow, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_cell_geometry(self) -> Self:
        for row_index, row in enumerate(self.rows):
            for cell in row.cells:
                if cell.column_index + cell.column_span > self.column_count:
                    raise ValueError("Table cell extends beyond the declared columns")
                if row_index + cell.row_span > len(self.rows):
                    raise ValueError("Table cell extends beyond the declared rows")
        return self
