import importlib
from types import SimpleNamespace

from fastapi.testclient import TestClient
from structlog.testing import capture_logs

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
    "ALLOWED_ORIGINS": "http://localhost:5173",
}


def test_health_confirms_configuration_and_cors(monkeypatch) -> None:
    for name, value in VALID_ENV.items():
        monkeypatch.setenv(name, value)

    main = importlib.import_module("app.main")

    with TestClient(main.app) as client:
        response = client.get("/health")
        cors_response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert cors_response.status_code == 200
    assert cors_response.headers["access-control-allow-origin"] == (
        "http://localhost:5173"
    )
    assert main.app.state.settings.openai_embedding_dimensions == 1536


def test_handled_error_log_uses_status_and_route_template(monkeypatch) -> None:
    for name, value in VALID_ENV.items():
        monkeypatch.setenv(name, value)
    main = importlib.import_module("app.main")
    from app.assistant.tracing import AssistantTrace

    trace = AssistantTrace(
        trace_id="trace-1",
        thread_id="PRIVATE_THREAD_ID",
        user_id="PRIVATE_USER_ID",
        client_message_id="PRIVATE_CLIENT_ID",
        mode="summary",
        max_content_characters=12_000,
    )
    request = SimpleNamespace(
        state=SimpleNamespace(assistant_trace=trace),
        method="GET",
        scope={"route": SimpleNamespace(path="/chat/threads/{thread_id}")},
    )

    with capture_logs() as logs:
        main._log_handled_chat_error(
            request,
            RuntimeError("PRIVATE_ERROR_MESSAGE"),
            "thread_missing",
            404,
        )

    assert logs[0]["event"] == "chat_request_failed"
    assert logs[0]["http_status_code"] == 404
    assert logs[0]["route"] == "/chat/threads/{thread_id}"
    assert logs[0]["error_code"] == "thread_missing"
    assert "PRIVATE" not in str(logs[0])
