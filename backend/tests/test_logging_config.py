import json
import logging
import sys
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace

import structlog

from app.logging_config import configure_logging, production_log_fields


def logging_settings(
    *,
    app_environment: str,
    log_format: str,
    max_event_bytes: int = 4_096,
) -> SimpleNamespace:
    return SimpleNamespace(
        app_environment=app_environment,
        log_format=log_format,
        log_level="INFO",
        log_max_event_bytes=max_event_bytes,
    )


def test_json_and_console_logging_renderers() -> None:
    json_output = StringIO()
    with redirect_stdout(json_output):
        configure_logging(
            logging_settings(app_environment="production", log_format="json")
        )
        structlog.get_logger().info("json_event", answer_status="supported")

    rendered_json = json.loads(json_output.getvalue())
    assert rendered_json["event"] == "json_event"
    assert rendered_json["answer_status"] == "supported"

    console_output = StringIO()
    with redirect_stdout(console_output):
        configure_logging(
            logging_settings(app_environment="development", log_format="console")
        )
        structlog.get_logger().info("console_event", trace_id="trace-1")

    rendered_console = console_output.getvalue()
    assert "console_event" in rendered_console
    assert "trace-1" in rendered_console


def test_production_exception_logging_drops_content_traceback_and_identifiers() -> None:
    output = StringIO()
    with redirect_stdout(output):
        configure_logging(
            logging_settings(app_environment="production", log_format="json")
        )
        prompt = "PRIVATE_PROMPT_SENTINEL"
        history = [{"content": "PRIVATE_HISTORY_SENTINEL"}]
        try:
            raise RuntimeError("PRIVATE_EXCEPTION_SENTINEL")
        except RuntimeError:
            structlog.get_logger().exception(
                "chat_turn_failed",
                trace_id="trace-1",
                stage="stream.failed",
                error_code="assistant_unavailable",
                prompt=prompt,
                history=history,
                user_id="user-private",
                thread_id="thread-private",
            )

    rendered = output.getvalue()
    payload = json.loads(rendered)
    assert payload["error_class"] == "RuntimeError"
    assert payload["error_code"] == "assistant_unavailable"
    assert payload["trace_id"] == "trace-1"
    assert len(rendered.encode()) <= 4_096
    for forbidden in (
        "PRIVATE_PROMPT_SENTINEL",
        "PRIVATE_HISTORY_SENTINEL",
        "PRIVATE_EXCEPTION_SENTINEL",
        "user-private",
        "thread-private",
        "exception",
        "exc_info",
        "frames",
        "locals",
    ):
        assert forbidden not in rendered


def test_production_event_has_a_hard_size_fallback() -> None:
    output = StringIO()
    with redirect_stdout(output):
        configure_logging(
            logging_settings(
                app_environment="production",
                log_format="json",
                max_event_bytes=1_024,
            )
        )
        structlog.get_logger().info(
            "large_safe_event",
            trace_id="trace-1",
            stage="assistant.model.response",
            model="m" * 1_000,
            tool_name="t" * 1_000,
            route="r" * 1_000,
            grounding_reason="g" * 1_000,
            error_code="e" * 1_000,
            upstream_error_code="u" * 1_000,
            usage_limit="l" * 1_000,
            finish_reason="f" * 1_000,
        )

    rendered = output.getvalue().rstrip()
    payload = json.loads(rendered)
    assert payload["event"] == "large_safe_event"
    assert payload["trace_id"] == "trace-1"
    assert payload["log_truncated"] is True
    assert len(rendered.encode()) <= 1_024


def test_production_rate_limit_fields_allow_only_safe_numbers() -> None:
    fields = production_log_fields(
        {
            "retry_after_ms": 2_500,
            "rate_limit_requests": 100,
            "rate_limit_tokens": 100_000,
            "rate_remaining_requests": 7,
            "rate_remaining_tokens": 12_345,
            "rate_reset_requests_ms": 1_500,
            "rate_reset_tokens_ms": 123_000,
            "authorization": "PRIVATE_AUTHORIZATION",
            "response_body": "PRIVATE_RESPONSE_BODY",
            "arbitrary_header": "PRIVATE_HEADER",
        }
    )

    assert fields == {
        "retry_after_ms": 2_500,
        "rate_limit_requests": 100,
        "rate_limit_tokens": 100_000,
        "rate_remaining_requests": 7,
        "rate_remaining_tokens": 12_345,
        "rate_reset_requests_ms": 1_500,
        "rate_reset_tokens_ms": 123_000,
    }


def test_development_exception_logging_keeps_local_diagnostics() -> None:
    output = StringIO()
    with redirect_stdout(output):
        configure_logging(
            logging_settings(app_environment="development", log_format="console")
        )
        try:
            raise RuntimeError("LOCAL_EXCEPTION_SENTINEL")
        except RuntimeError:
            structlog.get_logger().exception(
                "local_failure",
                prompt="LOCAL_PROMPT_SENTINEL",
            )

    rendered = output.getvalue()
    assert "Traceback" in rendered
    assert "LOCAL_EXCEPTION_SENTINEL" in rendered
    assert "LOCAL_PROMPT_SENTINEL" in rendered

    configure_logging(logging_settings(app_environment="production", log_format="json"))


def test_production_uvicorn_errors_drop_traceback_and_exception_message() -> None:
    configure_logging(logging_settings(app_environment="production", log_format="json"))
    try:
        raise RuntimeError("PRIVATE_UVICORN_EXCEPTION_SENTINEL")
    except RuntimeError:
        exc_info = sys.exc_info()
    record = logging.LogRecord(
        "uvicorn.error",
        logging.ERROR,
        __file__,
        1,
        "Exception in ASGI application",
        (),
        exc_info,
    )

    filters = logging.getLogger("uvicorn.error").filters
    assert filters
    assert all(item.filter(record) for item in filters)
    assert record.exc_info is None
    assert record.exc_text is None
    assert record.stack_info is None
    assert record.getMessage() == (
        "Unhandled ASGI application exception error_class=RuntimeError"
    )
    assert "PRIVATE_UVICORN_EXCEPTION_SENTINEL" not in record.getMessage()
