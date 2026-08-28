import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.config import Settings
from app.database.supabase import (
    create_admin_supabase_client,
    create_user_supabase_client,
)


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_environment="test",
        supabase_url="https://project.supabase.co",
        supabase_anon_key="test-anon-key",
        supabase_service_role_key="test-service-role-key",
        database_url=("postgresql+psycopg://postgres:password@localhost:5432/postgres"),
        azure_openai_endpoint="https://test-resource.openai.azure.com/openai/v1/",
        azure_openai_api_key="test-azure-key",
        azure_openai_assistant_deployment="assistant-gpt-5-6-terra",
        azure_openai_keyword_deployment="keywords-gpt-5-4-nano",
        azure_openai_embedding_deployment="embeddings-text-embedding-3-small",
        openai_embedding_model="text-embedding-3-small",
        openai_embedding_dimensions=1536,
        openai_keyword_model="gpt-5.4-nano",
        openai_assistant_model="gpt-5.6-terra",
        openai_assistant_reasoning_effort="medium",
        openai_assistant_max_output_tokens=3000,
        allowed_origins="http://localhost:5173",
    )


def test_user_client_uses_anon_key_and_user_access_token() -> None:
    expected_client = object()
    factory = AsyncMock(return_value=expected_client)
    shared_http_client = object()

    with patch("app.database.supabase.acreate_client", factory):
        client = asyncio.run(
            create_user_supabase_client(
                make_settings(),
                "user-access-token",
                http_client=shared_http_client,
            )
        )

    assert client is expected_client
    factory.assert_awaited_once()
    call = factory.await_args.kwargs
    assert call["supabase_url"] == "https://project.supabase.co/"
    assert call["supabase_key"] == "test-anon-key"
    assert call["options"].headers == {"Authorization": "Bearer user-access-token"}
    assert call["options"].auto_refresh_token is False
    assert call["options"].persist_session is False
    assert call["options"].httpx_client is shared_http_client


def test_user_client_rejects_a_missing_access_token() -> None:
    with pytest.raises(ValueError, match="access token is required"):
        asyncio.run(create_user_supabase_client(make_settings(), ""))


def test_admin_client_uses_only_the_service_role_key() -> None:
    expected_client = object()
    factory = AsyncMock(return_value=expected_client)
    shared_http_client = object()

    with patch("app.database.supabase.acreate_client", factory):
        client = asyncio.run(
            create_admin_supabase_client(
                make_settings(),
                http_client=shared_http_client,
            )
        )

    assert client is expected_client
    factory.assert_awaited_once()
    call = factory.await_args.kwargs
    assert call["supabase_url"] == "https://project.supabase.co/"
    assert call["supabase_key"] == "test-service-role-key"
    assert "Authorization" not in call["options"].headers
    assert call["options"].auto_refresh_token is False
    assert call["options"].persist_session is False
    assert call["options"].httpx_client is shared_http_client


def test_concurrent_clients_keep_authorization_off_shared_transport() -> None:
    async def create_clients():
        async with httpx.AsyncClient() as shared_http_client:
            first, second, admin = await asyncio.gather(
                create_user_supabase_client(
                    make_settings(),
                    "first-user-token",
                    http_client=shared_http_client,
                ),
                create_user_supabase_client(
                    make_settings(),
                    "second-user-token",
                    http_client=shared_http_client,
                ),
                create_admin_supabase_client(
                    make_settings(),
                    http_client=shared_http_client,
                ),
            )
            return (
                first.postgrest.headers["Authorization"],
                second.postgrest.headers["Authorization"],
                admin.postgrest.headers["Authorization"],
                shared_http_client.headers.get("Authorization"),
            )

    first_auth, second_auth, admin_auth, shared_auth = asyncio.run(create_clients())

    assert first_auth == "Bearer first-user-token"
    assert second_auth == "Bearer second-user-token"
    assert admin_auth == "Bearer test-service-role-key"
    assert shared_auth is None
