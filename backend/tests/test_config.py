import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ENV_NAMES = {
    "APP_ENVIRONMENT",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "DATABASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_EMBEDDING_MODEL",
    "OPENAI_EMBEDDING_DIMENSIONS",
    "OPENAI_KEYWORD_MODEL",
    "OPENAI_ASSISTANT_MODEL",
    "OPENAI_ASSISTANT_REASONING_EFFORT",
    "OPENAI_ASSISTANT_MAX_OUTPUT_TOKENS",
    "CHAT_TURN_TIMEOUT_SECONDS",
    "ALLOWED_ORIGINS",
}
VALID_ENV = {
    "APP_ENVIRONMENT": "test",
    "SUPABASE_URL": "http://localhost:54321",
    "SUPABASE_ANON_KEY": "test-anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
    "DATABASE_URL": "postgresql+psycopg://postgres:password@localhost:5432/postgres",
    "OPENAI_API_KEY": "test-openai-key",
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
        "chat_timeout": 180,
        "app_environment": "test",
    }


def test_fails_when_a_required_setting_is_missing(tmp_path: Path) -> None:
    result = run_config_import(
        tmp_path,
        missing={"OPENAI_API_KEY"},
        script="from app.config import Settings; Settings(_env_file=None)",
    )

    assert result.returncode != 0
    assert "openai_api_key" in result.stderr
    assert "Field required" in result.stderr


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
