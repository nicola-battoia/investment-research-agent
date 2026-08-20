import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ENV_NAMES = {
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "DATABASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_EMBEDDING_MODEL",
    "OPENAI_EMBEDDING_DIMENSIONS",
    "OPENAI_KEYWORD_MODEL",
    "ALLOWED_ORIGINS",
}
VALID_ENV = {
    "SUPABASE_URL": "http://localhost:54321",
    "SUPABASE_ANON_KEY": "test-anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
    "DATABASE_URL": "postgresql+psycopg://postgres:password@localhost:5432/postgres",
    "OPENAI_API_KEY": "test-openai-key",
    "OPENAI_EMBEDDING_MODEL": "text-embedding-3-small",
    "OPENAI_EMBEDDING_DIMENSIONS": "1536",
    "OPENAI_KEYWORD_MODEL": "gpt-5.4-nano",
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
            "'keyword_model': settings.openai_keyword_model}))"
        ),
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "origins": ["http://localhost:5173", "https://app.example.com"],
        "dimensions": 1536,
        "keyword_model": "gpt-5.4-nano",
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


def test_requires_psycopg_3_database_url(tmp_path: Path) -> None:
    result = run_config_import(
        tmp_path,
        overrides={
            "DATABASE_URL": "postgresql://postgres:password@localhost:5432/postgres"
        },
    )

    assert result.returncode != 0
    assert "must use postgresql+psycopg:// for Psycopg 3" in result.stderr
