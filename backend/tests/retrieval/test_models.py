from datetime import date

import pytest
from pydantic import ValidationError

from app.retrieval.models import RetrievalFilters


def test_filters_normalize_and_deduplicate_values() -> None:
    filters = RetrievalFilters(
        companies=(" Apple Inc. ", "APPLE INC."),
        tickers=(" aapl ", "AAPL"),
        filing_types=(" 10-k ",),
        filing_years=(2024, 2024, 2023),
    )

    assert filters.companies == ("apple inc.",)
    assert filters.tickers == ("AAPL",)
    assert filters.filing_types == ("10-K",)
    assert filters.filing_years == (2024, 2023)


def test_filters_reject_empty_values_and_inverted_dates() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        RetrievalFilters(tickers=(" ",))

    with pytest.raises(ValidationError, match="start must not be after"):
        RetrievalFilters(
            filed_on_or_after=date(2025, 1, 1),
            filed_on_or_before=date(2024, 1, 1),
        )
