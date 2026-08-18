import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.database.supabase import (
    create_admin_supabase_client,
    create_user_supabase_client,
)


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        supabase_url="https://project.supabase.co",
        supabase_anon_key="test-anon-key",
        supabase_service_role_key="test-service-role-key",
        database_url=("postgresql+psycopg://postgres:password@localhost:5432/postgres"),
        openai_api_key="test-openai-key",
        openai_embedding_model="text-embedding-3-small",
        openai_embedding_dimensions=1536,
        allowed_origins="http://localhost:5173",
    )


def test_user_client_uses_anon_key_and_user_access_token() -> None:
    expected_client = object()
    factory = AsyncMock(return_value=expected_client)

    with patch("app.database.supabase.acreate_client", factory):
        client = asyncio.run(
            create_user_supabase_client(make_settings(), "user-access-token")
        )

    assert client is expected_client
    factory.assert_awaited_once()
    call = factory.await_args.kwargs
    assert call["supabase_url"] == "https://project.supabase.co/"
    assert call["supabase_key"] == "test-anon-key"
    assert call["options"].headers == {"Authorization": "Bearer user-access-token"}
    assert call["options"].auto_refresh_token is False
    assert call["options"].persist_session is False


def test_user_client_rejects_a_missing_access_token() -> None:
    with pytest.raises(ValueError, match="access token is required"):
        asyncio.run(create_user_supabase_client(make_settings(), ""))


def test_admin_client_uses_only_the_service_role_key() -> None:
    expected_client = object()
    factory = AsyncMock(return_value=expected_client)

    with patch("app.database.supabase.acreate_client", factory):
        client = asyncio.run(create_admin_supabase_client(make_settings()))

    assert client is expected_client
    factory.assert_awaited_once()
    call = factory.await_args.kwargs
    assert call["supabase_url"] == "https://project.supabase.co/"
    assert call["supabase_key"] == "test-service-role-key"
    assert "Authorization" not in call["options"].headers
    assert call["options"].auto_refresh_token is False
    assert call["options"].persist_session is False
