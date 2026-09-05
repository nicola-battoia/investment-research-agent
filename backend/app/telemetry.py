"""Cost-bounded Azure Monitor tracing for model calls."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from typing import Any

import structlog
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import Span, SpanKind
from pydantic_ai.models import Model
from pydantic_ai.models.instrumented import InstrumentationSettings, InstrumentedModel

from app.config import Settings

logger = structlog.get_logger()

_INSTRUMENTATIONS = (
    "azure_sdk",
    "django",
    "fastapi",
    "flask",
    "psycopg2",
    "requests",
    "urllib",
    "urllib3",
)
_configure_lock = Lock()
_configured = False
_capture_content = False


def configure_azure_monitor_tracing(settings: Settings) -> None:
    """Configure one trace-only Azure Monitor exporter for this process."""
    if not settings.azure_monitor_tracing_enabled:
        return

    connection_string = settings.application_insights_connection_string
    if connection_string is None:  # Settings validation keeps this unreachable.
        raise ValueError("Application Insights connection string is required")

    global _capture_content, _configured
    with _configure_lock:
        if _configured:
            return
        configure_azure_monitor(
            connection_string=connection_string.get_secret_value(),
            resource=Resource.create(
                {
                    "service.name": "document-copilot-backend",
                    "service.namespace": "10k-club",
                    "deployment.environment.name": settings.app_environment,
                }
            ),
            sampling_ratio=settings.azure_monitor_trace_sample_rate,
            disable_logging=True,
            disable_metrics=True,
            enable_live_metrics=False,
            enable_performance_counters=False,
            disable_offline_storage=True,
            browser_sdk_loader_config={"enabled": False},
            instrumentation_options={
                name: {"enabled": False} for name in _INSTRUMENTATIONS
            },
        )
        _capture_content = settings.azure_monitor_capture_content
        _configured = True

    logger.info(
        "azure_monitor_tracing_configured",
        azure_monitor_capture_content=settings.azure_monitor_capture_content,
        trace_sample_rate=settings.azure_monitor_trace_sample_rate,
    )


def instrument_assistant_model(model: Model, settings: Settings) -> Model:
    """Wrap the Responses model with PydanticAI's native OTel instrumentation."""
    if not settings.azure_monitor_tracing_enabled:
        return model
    return InstrumentedModel(
        model,
        options=InstrumentationSettings(
            include_content=settings.azure_monitor_capture_content,
            include_binary_content=False,
            include_model_request_parameters=False,
            version=5,
        ),
    )


@contextmanager
def assistant_turn_span(trace_id: str, model: str) -> Iterator[Span]:
    """Make every model and retrieval span a child of one correlated chat turn."""
    with trace.get_tracer(__name__).start_as_current_span(
        "chat research turn",
        kind=SpanKind.INTERNAL,
        attributes={
            "app.trace_id": trace_id,
            "gen_ai.request.model": model,
        },
    ) as span:
        yield span


@contextmanager
def model_call_span(
    operation: str,
    *,
    model: str,
    role: str,
) -> Iterator[Span]:
    """Create a standard client span for direct Responses or embeddings calls."""
    with trace.get_tracer(__name__).start_as_current_span(
        f"{operation} {model}",
        kind=SpanKind.CLIENT,
        attributes={
            "gen_ai.operation.name": operation,
            "gen_ai.provider.name": "openai",
            "gen_ai.request.model": model,
            "app.model.role": role,
        },
    ) as span:
        yield span


def record_model_input(
    span: Span,
    *,
    user_input: str,
    instructions: str | None = None,
) -> None:
    """Attach model input only when content capture is explicitly enabled."""
    if not _capture_content or not span.is_recording():
        return
    if instructions is not None:
        span.set_attribute(
            "gen_ai.system_instructions",
            _json_text([{"type": "text", "content": instructions}]),
        )
    span.set_attribute(
        "gen_ai.input.messages",
        _json_text(
            [
                {
                    "role": "user",
                    "parts": [{"type": "text", "content": user_input}],
                }
            ]
        ),
    )


def record_model_response(
    span: Span,
    response: object,
    *,
    output: object | None = None,
) -> None:
    """Attach safe response identity/usage and optional output content."""
    response_id = getattr(response, "id", None)
    if isinstance(response_id, str):
        span.set_attribute("gen_ai.response.id", response_id)

    usage = getattr(response, "usage", None)
    if usage is not None:
        _record_usage(span, usage)

    if not _capture_content or output is None or not span.is_recording():
        return
    serialized_output = _model_output_text(output)
    span.set_attribute(
        "gen_ai.output.messages",
        _json_text(
            [
                {
                    "role": "assistant",
                    "parts": [{"type": "text", "content": serialized_output}],
                }
            ]
        ),
    )


def _record_usage(span: Span, usage: object) -> None:
    fields = {
        "input_tokens": "gen_ai.usage.input_tokens",
        "output_tokens": "gen_ai.usage.output_tokens",
        "total_tokens": "app.usage.total_tokens",
    }
    for field, attribute in fields.items():
        value = getattr(usage, field, None)
        if isinstance(value, int):
            span.set_attribute(attribute, value)

    input_details = getattr(usage, "input_tokens_details", None)
    cached_tokens = getattr(input_details, "cached_tokens", None)
    if isinstance(cached_tokens, int):
        span.set_attribute("app.usage.cached_input_tokens", cached_tokens)


def _model_output_text(output: object) -> str:
    model_dump_json = getattr(output, "model_dump_json", None)
    if callable(model_dump_json):
        return str(model_dump_json())
    if isinstance(output, str):
        return output
    return _json_text(output)


def _json_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
