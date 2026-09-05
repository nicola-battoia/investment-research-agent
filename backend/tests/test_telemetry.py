from types import SimpleNamespace
from unittest.mock import Mock

from opentelemetry.trace import Span
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.instrumented import InstrumentedModel

from app import telemetry
from app.config import Settings


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "app_environment": "test",
        "supabase_url": "https://project.supabase.co",
        "supabase_anon_key": "test-anon-key",
        "supabase_service_role_key": "test-service-role-key",
        "database_url": (
            "postgresql+psycopg://postgres:password@localhost:5432/postgres"
        ),
        "azure_openai_endpoint": ("https://test-resource.openai.azure.com/openai/v1/"),
        "azure_openai_api_key": "test-azure-key",
        "azure_openai_assistant_deployment": "assistant-gpt-5-6-terra",
        "azure_openai_keyword_deployment": "keywords-gpt-5-4-nano",
        "azure_openai_embedding_deployment": "embeddings-text-embedding-3-small",
        "openai_embedding_model": "text-embedding-3-small",
        "openai_embedding_dimensions": 1536,
        "openai_keyword_model": "gpt-5.4-nano",
        "openai_assistant_model": "gpt-5.6-terra",
        "openai_assistant_reasoning_effort": "medium",
        "openai_assistant_max_output_tokens": 3000,
        "allowed_origins": "http://localhost:5173",
    }
    values.update(overrides)
    return Settings(**values)


def test_configures_trace_only_cost_bounded_azure_exporter(monkeypatch) -> None:
    configure = Mock()
    monkeypatch.setattr(telemetry, "configure_azure_monitor", configure)
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setattr(telemetry, "_capture_content", False)
    settings = make_settings(
        azure_monitor_tracing_enabled=True,
        azure_monitor_capture_content=True,
        azure_monitor_trace_sample_rate=0.25,
        application_insights_connection_string="InstrumentationKey=secret",
    )

    telemetry.configure_azure_monitor_tracing(settings)
    telemetry.configure_azure_monitor_tracing(settings)

    configure.assert_called_once()
    kwargs = configure.call_args.kwargs
    assert kwargs["connection_string"] == "InstrumentationKey=secret"
    assert kwargs["sampling_ratio"] == 0.25
    assert kwargs["disable_logging"] is True
    assert kwargs["disable_metrics"] is True
    assert kwargs["enable_live_metrics"] is False
    assert kwargs["enable_performance_counters"] is False
    assert kwargs["disable_offline_storage"] is True
    assert all(
        not options["enabled"] for options in kwargs["instrumentation_options"].values()
    )
    assert kwargs["resource"].attributes["service.name"] == ("document-copilot-backend")


def test_wraps_only_enabled_assistant_models() -> None:
    model = FunctionModel(lambda _messages, _info: None)

    assert telemetry.instrument_assistant_model(model, make_settings()) is model
    instrumented = telemetry.instrument_assistant_model(
        model,
        make_settings(
            azure_monitor_tracing_enabled=True,
            application_insights_connection_string="InstrumentationKey=secret",
        ),
    )

    assert isinstance(instrumented, InstrumentedModel)
    options = instrumented.instrumentation_settings
    assert options.include_content is False
    assert options.include_binary_content is False
    assert options.include_model_request_parameters is False


def test_records_direct_model_content_and_usage_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(telemetry, "_capture_content", True)
    span = Mock(spec=Span)
    span.is_recording.return_value = True
    response = SimpleNamespace(
        id="response-123",
        usage=SimpleNamespace(
            input_tokens=120,
            output_tokens=30,
            total_tokens=150,
            input_tokens_details=SimpleNamespace(cached_tokens=20),
        ),
    )

    telemetry.record_model_input(
        span,
        instructions="Extract keywords",
        user_input="Compare revenue",
    )
    telemetry.record_model_response(
        span,
        response,
        output={"groups": [["revenue"]]},
    )

    attributes = dict(call.args for call in span.set_attribute.call_args_list)
    assert "Extract keywords" in attributes["gen_ai.system_instructions"]
    assert "Compare revenue" in attributes["gen_ai.input.messages"]
    assert "revenue" in attributes["gen_ai.output.messages"]
    assert attributes["gen_ai.response.id"] == "response-123"
    assert attributes["gen_ai.usage.input_tokens"] == 120
    assert attributes["gen_ai.usage.output_tokens"] == 30
    assert attributes["app.usage.total_tokens"] == 150
    assert attributes["app.usage.cached_input_tokens"] == 20


def test_omits_direct_model_content_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(telemetry, "_capture_content", False)
    span = Mock(spec=Span)
    span.is_recording.return_value = True

    telemetry.record_model_input(span, user_input="sensitive prompt")

    span.set_attribute.assert_not_called()
