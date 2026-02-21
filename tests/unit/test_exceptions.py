"""Tests for exceptions."""

from mcp_gitlab.exceptions import (
    GitLabApiError,
    GitLabAuthError,
    GitLabNotFoundError,
    GitLabWriteDisabledError,
)


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
