import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ENV_NAMES = {
    "APP_ENVIRONMENT",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_HTTP_CONNECT_TIMEOUT_SECONDS",
    "SUPABASE_HTTP_READ_TIMEOUT_SECONDS",
    "SUPABASE_HTTP_WRITE_TIMEOUT_SECONDS",
    "SUPABASE_HTTP_POOL_TIMEOUT_SECONDS",
    "DATABASE_URL",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ASSISTANT_DEPLOYMENT",
    "AZURE_OPENAI_KEYWORD_DEPLOYMENT",
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    "OPENAI_EMBEDDING_MODEL",
    "OPENAI_EMBEDDING_DIMENSIONS",
    "OPENAI_KEYWORD_MODEL",
    "OPENAI_KEYWORD_MAX_OUTPUT_TOKENS",
    "OPENAI_ASSISTANT_MODEL",
    "OPENAI_ASSISTANT_REASONING_EFFORT",
    "OPENAI_ASSISTANT_MAX_OUTPUT_TOKENS",
    "ASSISTANT_MAX_MODEL_REQUESTS",
    "ASSISTANT_MAX_TOOL_CALLS",
    "ASSISTANT_MAX_TOTAL_OUTPUT_TOKENS",
    "ASSISTANT_MAX_TOTAL_INPUT_TOKENS",
    "ASSISTANT_MAX_REQUEST_INPUT_TOKENS",
    "ASSISTANT_EVIDENCE_PREVIEW_CHARACTERS",
    "ASSISTANT_MAX_SEARCH_CALLS",
    "ASSISTANT_MAX_SURROUNDING_CALLS",
    "ASSISTANT_SEARCH_RESULT_LIMIT",
    "CHAT_TURN_TIMEOUT_SECONDS",
    "APPLICATION_INSIGHTS_CONNECTION_STRING",
    "AZURE_MONITOR_TRACING_ENABLED",
    "AZURE_MONITOR_CAPTURE_CONTENT",
    "AZURE_MONITOR_TRACE_SAMPLE_RATE",
    "ALLOWED_ORIGINS",
}
VALID_ENV = {
    "APP_ENVIRONMENT": "test",
    "SUPABASE_URL": "http://localhost:54321",
    "SUPABASE_ANON_KEY": "test-anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
    "DATABASE_URL": "postgresql+psycopg://postgres:password@localhost:5432/postgres",
    "AZURE_OPENAI_ENDPOINT": "https://test-resource.openai.azure.com/openai/v1/",
    "AZURE_OPENAI_API_KEY": "test-azure-key",
    "AZURE_OPENAI_ASSISTANT_DEPLOYMENT": "assistant-gpt-5-6-terra",
    "AZURE_OPENAI_KEYWORD_DEPLOYMENT": "keywords-gpt-5-4-nano",
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": "embeddings-text-embedding-3-small",
    "OPENAI_EMBEDDING_MODEL": "text-embedding-3-small",
    "OPENAI_EMBEDDING_DIMENSIONS": "1536",
    "OPENAI_KEYWORD_MODEL": "gpt-5.4-nano",
    "OPENAI_ASSISTANT_MODEL": "gpt-5.6-terra",
    "OPENAI_ASSISTANT_REASONING_EFFORT": "medium",
    "OPENAI_ASSISTANT_MAX_OUTPUT_TOKENS": "3000",
    "CHAT_TURN_TIMEOUT_SECONDS": "180",
    "ALLOWED_ORIGINS": "http://localhost:5173, https://app.example.com/",
}


def run_config_import(
    tmp_path: Path,
    *,
    overrides: dict[str, str] | None = None,
    missing: set[str] | None = None,
    script: str = "from app.config import settings",
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for name in CONFIG_ENV_NAMES:
        env.pop(name, None)
    env.update(VALID_ENV)
    env.update(overrides or {})
    for name in missing or set():
        env.pop(name, None)
    env["PYTHONPATH"] = str(BACKEND_ROOT)

    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_loads_and_normalizes_valid_settings(tmp_path: Path) -> None:
    result = run_config_import(
        tmp_path,
        script=(
            "import json; "
            "from app.config import settings; "
            "print(json.dumps({'origins': "
            "[str(origin).rstrip('/') for origin in settings.allowed_origins], "
            "'dimensions': settings.openai_embedding_dimensions, "
            "'keyword_model': settings.openai_keyword_model, "
            "'assistant_model': settings.openai_assistant_model, "
            "'assistant_effort': settings.openai_assistant_reasoning_effort, "
            "'assistant_max_tokens': "
            "settings.openai_assistant_max_output_tokens, "
            "'keyword_max_tokens': settings.openai_keyword_max_output_tokens, "
            "'model_requests': settings.assistant_max_model_requests, "
            "'tool_calls': settings.assistant_max_tool_calls, "
            "'total_output_tokens': "
            "settings.assistant_max_total_output_tokens, "
            "'total_input_tokens': settings.assistant_max_total_input_tokens, "
            "'request_input_tokens': "
            "settings.assistant_max_request_input_tokens, "
            "'search_calls': settings.assistant_max_search_calls, "
            "'surrounding_calls': settings.assistant_max_surrounding_calls, "
            "'search_results': settings.assistant_search_result_limit, "
            "'preview_characters': "
            "settings.assistant_evidence_preview_characters, "
            "'supabase_timeouts': ["
            "settings.supabase_http_connect_timeout_seconds, "
            "settings.supabase_http_read_timeout_seconds, "
            "settings.supabase_http_write_timeout_seconds, "
            "settings.supabase_http_pool_timeout_seconds], "
            "'chat_timeout': settings.chat_turn_timeout_seconds, "
            "'app_environment': settings.app_environment}))"
        ),
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "origins": ["http://localhost:5173", "https://app.example.com"],
        "dimensions": 1536,
        "keyword_model": "gpt-5.4-nano",
        "assistant_model": "gpt-5.6-terra",
        "assistant_effort": "medium",
        "assistant_max_tokens": 3000,
        "keyword_max_tokens": 800,
        "model_requests": 10,
        "tool_calls": 8,
        "total_output_tokens": 10_000,
        "total_input_tokens": 75_000,
        "request_input_tokens": 50_000,
        "search_calls": 5,
        "surrounding_calls": 2,
        "search_results": 10,
        "preview_characters": 400,
        "supabase_timeouts": [5.0, 15.0, 15.0, 5.0],
        "chat_timeout": 180,
        "app_environment": "test",
    }


@pytest.mark.parametrize(
    ("environment_name", "field_name"),
    [
        ("AZURE_OPENAI_ENDPOINT", "azure_openai_endpoint"),
        ("AZURE_OPENAI_API_KEY", "azure_openai_api_key"),
        (
            "AZURE_OPENAI_ASSISTANT_DEPLOYMENT",
            "azure_openai_assistant_deployment",
        ),
        ("AZURE_OPENAI_KEYWORD_DEPLOYMENT", "azure_openai_keyword_deployment"),
        (
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
            "azure_openai_embedding_deployment",
        ),
    ],
)
def test_fails_when_required_azure_setting_is_missing(
    tmp_path: Path,
    environment_name: str,
    field_name: str,
) -> None:
    result = run_config_import(
        tmp_path,
        missing={environment_name},
        script="from app.config import Settings; Settings(_env_file=None)",
    )

    assert result.returncode != 0
    assert field_name in result.stderr
    assert "Field required" in result.stderr


def test_requires_azure_openai_v1_endpoint(tmp_path: Path) -> None:
    result = run_config_import(
        tmp_path,
        overrides={"AZURE_OPENAI_ENDPOINT": "https://test-resource.openai.azure.com/"},
    )

    assert result.returncode != 0
    assert "must end with /openai/v1/" in result.stderr


def test_requires_keyword_extraction_model(tmp_path: Path) -> None:
    result = run_config_import(
        tmp_path,
        missing={"OPENAI_KEYWORD_MODEL"},
        script="from app.config import Settings; Settings(_env_file=None)",
    )

    assert result.returncode != 0
    assert "openai_keyword_model" in result.stderr


def test_requires_assistant_model(tmp_path: Path) -> None:
    result = run_config_import(
        tmp_path,
        missing={"OPENAI_ASSISTANT_MODEL"},
        script="from app.config import Settings; Settings(_env_file=None)",
    )

    assert result.returncode != 0
    assert "openai_assistant_model" in result.stderr


def test_rejects_invalid_assistant_reasoning_effort(tmp_path: Path) -> None:
    result = run_config_import(
        tmp_path,
        overrides={"OPENAI_ASSISTANT_REASONING_EFFORT": "extreme"},
    )

    assert result.returncode != 0
    assert "openai_assistant_reasoning_effort" in result.stderr


def test_rejects_invalid_cors_origins(tmp_path: Path) -> None:
    result = run_config_import(
        tmp_path,
        overrides={"ALLOWED_ORIGINS": "not-an-origin"},
    )

    assert result.returncode != 0
    assert "allowed_origins.0" in result.stderr


def test_rejects_non_positive_embedding_dimensions(tmp_path: Path) -> None:
    result = run_config_import(
        tmp_path,
        overrides={"OPENAI_EMBEDDING_DIMENSIONS": "0"},
    )

    assert result.returncode != 0
    assert "openai_embedding_dimensions" in result.stderr


def test_rejects_non_positive_chat_timeout(tmp_path: Path) -> None:
    result = run_config_import(
        tmp_path,
        overrides={"CHAT_TURN_TIMEOUT_SECONDS": "0"},
    )

    assert result.returncode != 0
    assert "chat_turn_timeout_seconds" in result.stderr


def test_rejects_per_request_input_limit_above_cumulative_limit(
    tmp_path: Path,
) -> None:
    result = run_config_import(
        tmp_path,
        overrides={
            "ASSISTANT_MAX_TOTAL_INPUT_TOKENS": "1000",
            "ASSISTANT_MAX_REQUEST_INPUT_TOKENS": "1001",
        },
    )

    assert result.returncode != 0
    assert "ASSISTANT_MAX_REQUEST_INPUT_TOKENS cannot exceed" in result.stderr
    assert "ASSISTANT_MAX_TOTAL_INPUT_TOKENS" in result.stderr


def test_requires_psycopg_3_database_url(tmp_path: Path) -> None:
    result = run_config_import(
        tmp_path,
        overrides={
            "DATABASE_URL": "postgresql://postgres:password@localhost:5432/postgres"
        },
    )

    assert result.returncode != 0
    assert "must use postgresql+psycopg:// for Psycopg 3" in result.stderr


def test_requires_explicit_app_environment(tmp_path: Path) -> None:
    result = run_config_import(
        tmp_path,
        missing={"APP_ENVIRONMENT"},
        script="from app.config import Settings; Settings(_env_file=None)",
    )

    assert result.returncode != 0
    assert "app_environment" in result.stderr


def test_rejects_unsafe_production_logging_profiles(tmp_path: Path) -> None:
    console = run_config_import(
        tmp_path,
        overrides={
            "APP_ENVIRONMENT": "production",
            "LOG_FORMAT": "console",
            "ASSISTANT_TRACE_MODE": "summary",
        },
    )
    full = run_config_import(
        tmp_path,
        overrides={
            "APP_ENVIRONMENT": "production",
            "LOG_FORMAT": "json",
            "ASSISTANT_TRACE_MODE": "full",
        },
    )

    assert console.returncode != 0
    assert "Production logging requires LOG_FORMAT=json" in console.stderr
    assert full.returncode != 0
    assert "cannot use ASSISTANT_TRACE_MODE=full" in full.stderr


def test_requires_application_insights_connection_when_tracing_is_enabled(
    tmp_path: Path,
) -> None:
    result = run_config_import(
        tmp_path,
        overrides={"AZURE_MONITOR_TRACING_ENABLED": "true"},
    )

    assert result.returncode != 0
    assert "APPLICATION_INSIGHTS_CONNECTION_STRING is required" in result.stderr


def test_requires_tracing_when_azure_content_capture_is_enabled(
    tmp_path: Path,
) -> None:
    result = run_config_import(
        tmp_path,
        overrides={"AZURE_MONITOR_CAPTURE_CONTENT": "true"},
    )

    assert result.returncode != 0
    assert "AZURE_MONITOR_CAPTURE_CONTENT requires" in result.stderr


@pytest.mark.parametrize("sample_rate", ["-0.1", "1.1"])
def test_rejects_invalid_azure_monitor_sample_rate(
    tmp_path: Path,
    sample_rate: str,
) -> None:
    result = run_config_import(
        tmp_path,
        overrides={"AZURE_MONITOR_TRACE_SAMPLE_RATE": sample_rate},
    )

    assert result.returncode != 0
    assert "azure_monitor_trace_sample_rate" in result.stderr
