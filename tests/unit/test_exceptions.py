"""Tests for exceptions and the _err envelope that maps them."""

import json

import pytest

from mcp_gitlab.exceptions import (
    GitLabApiError,
    GitLabAuthError,
    GitLabError,
    GitLabNotFoundError,
    GitLabWriteDisabledError,
)
from mcp_gitlab.servers.gitlab import _err

API = {"error", "status_code", "body"}
HINTED = API | {"hint"}


@pytest.mark.parametrize(
    ("exc", "keys"),
    [
        (GitLabError("base"), {"error"}),
        (GitLabApiError(500, "Internal Server Error", "boom"), API),
        (GitLabApiError(409, "Conflict"), HINTED),
        (GitLabApiError(422, "Unprocessable"), HINTED),
        (GitLabApiError(429, "Too Many Requests"), HINTED),
        (GitLabAuthError(401), HINTED),
        (GitLabAuthError(403), HINTED),
        (GitLabNotFoundError("gone"), HINTED),
        (GitLabWriteDisabledError(), {"error", "hint"}),
    ],
    ids=["base", "api-500", "api-409", "api-422", "api-429", "auth-401", "auth-403", "404", "ro"],
)
def test_err_envelope_key_set(exc, keys):
    """Exact key set per exception type; dropping ``body`` or ``hint`` fails here."""
    assert json.loads(_err(exc)).keys() == keys


def test_api_error():
    e = GitLabApiError(500, "Internal Server Error", "something broke")
    assert e.status_code == 500
    assert "500" in str(e)
    assert "something broke" in str(e)


def test_auth_error_401():
    e = GitLabAuthError(401)
    assert e.status_code == 401
    assert "Unauthorized" in str(e)


def test_auth_error_403():
    e = GitLabAuthError(403)
    assert e.status_code == 403
    assert "Forbidden" in str(e)


def test_not_found_error():
    e = GitLabNotFoundError("resource not found")
    assert e.status_code == 404


def test_write_disabled():
    e = GitLabWriteDisabledError()
    assert "read-only" in str(e).lower() or "read_only" in str(e).lower()
