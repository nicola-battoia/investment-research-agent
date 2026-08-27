"""Application-wide Structlog configuration."""

from __future__ import annotations

import json
import logging
from typing import Any

import structlog

from app.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure structured application logs for the selected environment."""
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    if settings.log_format == "console":
        processors = [
            *shared_processors,
            structlog.processors.format_exc_info,
            _console_renderer,
        ]
    else:
        processors = [
            *shared_processors,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level)
        ),
        cache_logger_on_first_use=True,
    )


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
