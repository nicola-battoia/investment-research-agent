from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Annotated
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from supabase_auth import User
from supabase_auth.errors import AuthApiError, AuthInvalidJwtError
from supabase_auth.types import UserResponse

from app.auth.dependencies import get_current_user
from app.config import Settings


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_environment="test",
        supabase_url="https://project.supabase.co",
        supabase_anon_key="test-anon-key",
        supabase_service_role_key="test-service-role-key",
        database_url=("postgresql+psycopg://postgres:password@localhost:5432/postgres"),
        openai_api_key="test-openai-key",
        openai_embedding_model="text-embedding-3-small",
        openai_embedding_dimensions=1536,
        openai_keyword_model="gpt-5.4-nano",
        openai_assistant_model="gpt-5.6-terra",
        openai_assistant_reasoning_effort="medium",
        openai_assistant_max_output_tokens=3000,
        allowed_origins="http://localhost:5173",
    )


def make_app() -> FastAPI:
    application = FastAPI()
    application.state.settings = make_settings()

    @application.get("/protected")
    async def protected_route(
        user: Annotated[User, Depends(get_current_user)],
    ) -> dict[str, str | None]:
        return {"id": user.id, "email": user.email}

    return application


def test_missing_bearer_token_is_rejected() -> None:
    client_factory = AsyncMock()

    with patch(
        "app.auth.dependencies.create_user_supabase_client",
        client_factory,
    ):
        response = TestClient(make_app()).get("/protected")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "detail": "Invalid or expired authentication credentials"
    }
    client_factory.assert_not_awaited()


@pytest.mark.parametrize(
    "auth_error",
    [
        AuthInvalidJwtError("Invalid JWT"),
        AuthApiError("JWT expired", 401, None),
    ],
    ids=["invalid", "expired"],
)
def test_invalid_or_expired_bearer_token_is_rejected(
    auth_error: Exception,
) -> None:
    get_user = AsyncMock(side_effect=auth_error)
    supabase_client = SimpleNamespace(auth=SimpleNamespace(get_user=get_user))
    client_factory = AsyncMock(return_value=supabase_client)

    with patch(
        "app.auth.dependencies.create_user_supabase_client",
        client_factory,
    ):
        response = TestClient(make_app()).get(
            "/protected",
            headers={"Authorization": "Bearer bad-token"},
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "detail": "Invalid or expired authentication credentials"
    }
    get_user.assert_awaited_once_with("bad-token")


def test_valid_bearer_token_returns_the_supabase_user() -> None:
    user = User(
        id="8b50b43c-571d-4fbc-8a3b-32e3bbfa39da",
        email="analyst@10kclub.example",
        app_metadata={},
        user_metadata={},
        aud="authenticated",
        created_at=datetime.now(UTC),
    )
    get_user = AsyncMock(return_value=UserResponse(user=user))
    supabase_client = SimpleNamespace(auth=SimpleNamespace(get_user=get_user))
    client_factory = AsyncMock(return_value=supabase_client)
    application = make_app()

    with patch(
        "app.auth.dependencies.create_user_supabase_client",
        client_factory,
    ):
        response = TestClient(application).get(
            "/protected",
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "id": user.id,
        "email": "analyst@10kclub.example",
    }
    client_factory.assert_awaited_once_with(
        application.state.settings,
        "valid-token",
    )
    get_user.assert_awaited_once_with("valid-token")
