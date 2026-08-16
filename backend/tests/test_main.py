import importlib

from fastapi.testclient import TestClient

VALID_ENV = {
    "SUPABASE_URL": "http://localhost:54321",
    "SUPABASE_ANON_KEY": "test-anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
    "DATABASE_URL": "postgresql://postgres:password@localhost:5432/postgres",
    "OPENAI_API_KEY": "test-openai-key",
    "OPENAI_EMBEDDING_MODEL": "text-embedding-3-small",
    "OPENAI_EMBEDDING_DIMENSIONS": "1536",
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
