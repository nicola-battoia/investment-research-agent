import json
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace

import structlog
from app.logging_config import configure_logging


def test_json_and_console_logging_renderers() -> None:
    json_output = StringIO()
    with redirect_stdout(json_output):
        configure_logging(SimpleNamespace(log_format="json", log_level="INFO"))
        structlog.get_logger().info("json_event", answer_status="supported")

    rendered_json = json.loads(json_output.getvalue())
    assert rendered_json["event"] == "json_event"
    assert rendered_json["answer_status"] == "supported"

    console_output = StringIO()
    with redirect_stdout(console_output):
        configure_logging(SimpleNamespace(log_format="console", log_level="INFO"))
        structlog.get_logger().info("console_event", trace_id="trace-1")

    rendered_console = console_output.getvalue()
    assert "console_event" in rendered_console
    assert "trace-1" in rendered_console

    configure_logging(SimpleNamespace(log_format="json", log_level="INFO"))
