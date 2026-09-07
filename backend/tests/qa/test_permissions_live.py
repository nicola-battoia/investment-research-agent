"""Desired integrity policy. Failures are intentional evidence, never xfailed."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.qa]


def test_real_database_permissions(pytestconfig):
    if not pytestconfig.getoption("--qa-live"):
        pytest.skip("Run explicitly with --qa-live against the intended database")
    from evaluation.qa.permissions import audit_permissions

    failures = [check for check in audit_permissions() if not check["passed"]]
    assert not failures, failures


def test_real_jwt_postgrest_permissions(pytestconfig):
    if not pytestconfig.getoption("--qa-live"):
        pytest.skip("Run explicitly with --qa-live against the intended database")
    from evaluation.qa.permissions_http import audit_http_permissions

    failures = [check for check in audit_http_permissions() if not check["passed"]]
    assert not failures, failures


def test_real_assistant_chat_integrity(pytestconfig):
    if not pytestconfig.getoption("--qa-live"):
        pytest.skip("Run explicitly with --qa-live; makes real assistant calls")
    from fastapi.testclient import TestClient

    from app.config import settings
    from app.main import create_app
    from evaluation.qa.chat_integrity import check_chat_integrity

    with TestClient(create_app(settings)) as client:
        checks = check_chat_integrity(client)
    failures = [check for check in checks if not check["passed"]]
    assert not failures, failures
