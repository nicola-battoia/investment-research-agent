import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from openai import AsyncOpenAI
from pydantic_ai.providers.azure import AzureProvider

from app.config import Settings
from app.services import AzureOpenAIService


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_environment="test",
        supabase_url="https://project.supabase.co",
        supabase_anon_key="test-anon-key",
        supabase_service_role_key="test-service-role-key",
        database_url="postgresql+psycopg://postgres:password@localhost:5432/postgres",
        azure_openai_endpoint="https://test-resource.openai.azure.com/openai/v1/",
        azure_openai_api_key="test-azure-key",
        azure_openai_assistant_deployment="assistant-gpt-5-6-terra",
        azure_openai_keyword_deployment="keywords-gpt-5-4-nano",
        azure_openai_embedding_deployment="embeddings-text-embedding-3-small",
        azure_openai_http_max_retries=7,
        openai_embedding_model="text-embedding-3-small",
        openai_embedding_dimensions=1536,
        openai_keyword_model="gpt-5.4-nano",
        openai_assistant_model="gpt-5.6-terra",
        openai_assistant_reasoning_effort="medium",
        openai_assistant_max_output_tokens=3000,
        allowed_origins="http://localhost:5173",
    )


def test_builds_shared_azure_v1_client_and_routes_pydantic_model() -> None:
    service = AzureOpenAIService(make_settings())

    assert str(service.client.base_url) == (
        "https://test-resource.openai.azure.com/openai/v1/"
    )
    assert service.client.max_retries == 7

    model = service.create_responses_model(
        "assistant-gpt-5-6-terra",
        "gpt-5.6-terra",
    )

    assert model.model_name == "assistant-gpt-5-6-terra"
    azure_profile = AzureProvider.model_profile("gpt-5.6-terra")
    assert azure_profile is not None
    assert all(model.profile[key] == value for key, value in azure_profile.items())
    asyncio.run(service.close())
    assert service.client.is_closed


def test_does_not_close_an_injected_client() -> None:
    close = AsyncMock()
    client = cast(
        AsyncOpenAI,
        SimpleNamespace(close=close),
    )
    service = AzureOpenAIService(make_settings(), client=client)

    asyncio.run(service.close())

    close.assert_not_awaited()


def test_production_openai_clients_are_constructed_only_in_service() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    constructor = re.compile(r"\b(?:AsyncOpenAI|OpenAI)\(")
    matches = []
    for path in backend_root.rglob("*.py"):
        if "tests" in path.parts or ".venv" in path.parts:
            continue
        if constructor.search(path.read_text(encoding="utf-8")):
            matches.append(path.relative_to(backend_root).as_posix())

    assert matches == ["app/services/azure_openai_service.py"]
