"""Application-wide Structlog configuration."""

from __future__ import annotations

import json
import logging
import math
import sys
from collections.abc import Mapping
from typing import Any

import structlog

from app.config import Settings

_MAX_PRODUCTION_STRING_CHARACTERS = 160
_PRODUCTION_LOG_FIELDS = frozenset(
    {
        "answer_status",
        "cached_replay",
        "candidate_count",
        "candidate_limit",
        "citation_count",
        "context_passage_count",
        "cost_usd",
        "dimensions",
        "duration_ms",
        "elapsed_ms",
        "error_class",
        "error_code",
        "event",
        "evidence_count",
        "failed_after_stage",
        "finish_reason",
        "fused_count",
        "grounding_reason",
        "http_status_code",
        "hydration_ms",
        "input_tokens",
        "keyword_group_count",
        "keyword_term_count",
        "level",
        "log_truncated",
        "max_output_tokens",
        "max_retries",
        "method",
        "model",
        "model_request_index",
        "output_tokens",
        "passage_count",
        "persisted",
        "radius",
        "read_source_count",
        "requested_count",
        "requests",
        "result_count",
        "result_limit",
        "retry",
        "retry_available",
        "retryable",
        "route",
        "rrf_k",
        "run_step",
        "search_calls",
        "selected_status",
        "semantic_weight",
        "sequence",
        "stage",
        "stored_citation_count",
        "stored_message_count",
        "surrounding_calls",
        "timeout_seconds",
        "timestamp",
        "tool_calls",
        "tool_index",
        "tool_name",
        "total_duration_ms",
        "total_tokens",
        "trace_id",
        "upstream_error_code",
        "upstream_status_code",
        "usage_limit",
        "lexical_weight",
    }
)
_MINIMAL_PRODUCTION_FIELDS = (
    "timestamp",
    "level",
    "event",
    "trace_id",
    "sequence",
    "stage",
    "failed_after_stage",
    "error_class",
    "error_code",
)


def configure_logging(settings: Settings) -> None:
    """Configure structured application logs for the selected environment."""
    _configure_uvicorn_exception_safety(
        enabled=settings.app_environment == "production"
    )
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    if settings.log_format == "console":
        processors = [
            *shared_processors,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _console_renderer,
        ]
    else:
        processors = [
            *shared_processors,
            _production_processor(settings.log_max_event_bytes),
            structlog.processors.JSONRenderer(
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level)
        ),
        cache_logger_on_first_use=True,
    )


def production_log_fields(fields: Mapping[str, object]) -> dict[str, object]:
    """Return only bounded scalar fields approved for production logs."""
    return {
        key: normalized
        for key, value in fields.items()
        if key in _PRODUCTION_LOG_FIELDS
        and (normalized := _production_scalar(value)) is not _DROP
    }


def _production_processor(
    max_event_bytes: int,
) -> structlog.types.Processor:
    def processor(
        _logger: object,
        _method_name: str,
        event_dict: dict[str, Any],
    ) -> dict[str, object]:
        safe = production_log_fields(event_dict)
        error_class = _exception_class(event_dict.get("exc_info"))
        if error_class is not None:
            safe.setdefault("error_class", error_class)
        if _encoded_size(safe) <= max_event_bytes:
            return safe
        minimal = {
            key: _fallback_scalar(safe[key])
            for key in _MINIMAL_PRODUCTION_FIELDS
            if key in safe
        }
        minimal["log_truncated"] = True
        return minimal

    return processor


class _Drop:
    pass


_DROP = _Drop()


def _production_scalar(value: object) -> object:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _DROP
    if isinstance(value, str):
        return value[:_MAX_PRODUCTION_STRING_CHARACTERS]
    return _DROP


def _fallback_scalar(value: object) -> object:
    return value[:64] if isinstance(value, str) else value


def _exception_class(exc_info: object) -> str | None:
    if exc_info is True:
        exception_type = sys.exc_info()[0]
        return exception_type.__name__ if exception_type is not None else None
    if isinstance(exc_info, BaseException):
        return type(exc_info).__name__
    if isinstance(exc_info, tuple) and exc_info:
        exception_type = exc_info[0]
        if isinstance(exception_type, type) and issubclass(
            exception_type, BaseException
        ):
            return exception_type.__name__
    return None


def _encoded_size(event: Mapping[str, object]) -> int:
    return len(
        json.dumps(
            event,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    )


class _UvicornExceptionSafetyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        error_class = _exception_class(record.exc_info)
        if error_class is not None:
            record.msg = "Unhandled ASGI application exception error_class=%s"
            record.args = (error_class,)
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def _configure_uvicorn_exception_safety(*, enabled: bool) -> None:
    logger = logging.getLogger("uvicorn.error")
    filters = [
        item
        for item in logger.filters
        if isinstance(item, _UvicornExceptionSafetyFilter)
    ]
    if enabled and not filters:
        logger.addFilter(_UvicornExceptionSafetyFilter())
    if not enabled:
        for item in filters:
            logger.removeFilter(item)


def _console_renderer(
    _logger: object,
    _method_name: str,
    event_dict: dict[str, Any],
) -> str:
    """Render trace identity on one line and larger payloads as indented JSON."""
    context = dict(event_dict)
    timestamp = context.pop("timestamp", "")
    level = str(context.pop("level", "info")).upper()
    event = context.pop("event", "log")
    identity = []
    for key in ("trace_id", "sequence", "stage", "elapsed_ms"):
        value = context.pop(key, None)
        if value is not None:
            identity.append(f"{key}={value}")
    exception = context.pop("exception", None)
    header = " ".join(
        item for item in (str(timestamp), f"[{level}]", str(event), *identity) if item
    )
    sections = [header]
    if context:
        sections.append(
            json.dumps(
                context,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            )
        )
    if exception:
        sections.append(str(exception))
    return "\n".join(sections)
