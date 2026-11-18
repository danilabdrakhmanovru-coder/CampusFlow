"""Checks for the supported backend entry point after removing the prototype."""
from app.v1.main import app


def test_only_versioned_api_exposes_application_routes():
    paths = set(app.openapi()["paths"])
    assert {
        "/api/v1/privacy/policy",
        "/api/v1/auth/login",
        "/api/v1/site",
        "/api/v1/booking-holds",
        "/api/v1/admin/imports/{batch_id}/rollback",
    } <= paths
    assert all(path.startswith("/api/v1/") for path in paths)
