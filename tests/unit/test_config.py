"""Tests for GitLab configuration."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from mcp_gitlab.config import GitLabConfig


def test_config_from_env():
    env = {"GITLAB_URL": "https://gitlab.example.com", "GITLAB_TOKEN": "glpat-abc123"}
    with patch.dict(os.environ, env, clear=True):
        config = GitLabConfig.from_env()
    assert config.url == "https://gitlab.example.com"
    assert config.token == "glpat-abc123"
    assert config.read_only is False
    assert config.timeout == 30


def test_config_from_env_with_pat():
    env = {"GITLAB_URL": "https://gitlab.example.com", "GITLAB_PAT": "glpat-xyz"}
    with patch.dict(os.environ, env, clear=True):
        config = GitLabConfig.from_env()
    assert config.token == "glpat-xyz"


def test_config_read_only():
    env = {
        "GITLAB_URL": "https://gitlab.example.com",
        "GITLAB_TOKEN": "x",
        "GITLAB_READ_ONLY": "true",
    }
    with patch.dict(os.environ, env, clear=True):
        config = GitLabConfig.from_env()
    assert config.read_only is True


def test_config_api_url():
    config = GitLabConfig(url="https://gitlab.example.com", token="x")
    assert config.api_url == "https://gitlab.example.com/api/v4"


def test_config_validate_missing_url():
    config = GitLabConfig(url="", token="x")
    with pytest.raises(ValueError, match="GITLAB_URL"):
        config.validate()


def test_config_validate_missing_token():
    config = GitLabConfig(url="https://gitlab.example.com", token="")
    with pytest.raises(ValueError, match="GITLAB_TOKEN"):
        config.validate()


def test_config_from_env_with_personal_access_token():
    env = {"GITLAB_URL": "https://gitlab.example.com", "GITLAB_PERSONAL_ACCESS_TOKEN": "glpat-pat"}
    with patch.dict(os.environ, env, clear=True):
        config = GitLabConfig.from_env()
    assert config.token == "glpat-pat"


def test_config_from_env_with_api_token():
    env = {"GITLAB_URL": "https://gitlab.example.com", "GITLAB_API_TOKEN": "glpat-api"}
    with patch.dict(os.environ, env, clear=True):
        config = GitLabConfig.from_env()
    assert config.token == "glpat-api"


def test_config_token_priority():
    """GITLAB_TOKEN takes precedence over all other aliases."""
    env = {
        "GITLAB_URL": "https://gitlab.example.com",
        "GITLAB_TOKEN": "winner",
        "GITLAB_PAT": "loser1",
        "GITLAB_PERSONAL_ACCESS_TOKEN": "loser2",
        "GITLAB_API_TOKEN": "loser3",
    }
    with patch.dict(os.environ, env, clear=True):
        config = GitLabConfig.from_env()
    assert config.token == "winner"


def test_config_url_strips_trailing_slash():
    env = {"GITLAB_URL": "https://gitlab.example.com/", "GITLAB_TOKEN": "x"}
    with patch.dict(os.environ, env, clear=True):
        config = GitLabConfig.from_env()
    assert config.url == "https://gitlab.example.com"


def test_oauth_mode_requires_client_fields():
    """All three missing OAuth vars are named in one message."""
    config = GitLabConfig(url="https://gitlab.example.com", auth="oauth")
    with pytest.raises(ValueError) as exc:
        config.validate()
    msg = str(exc.value)
    assert "GITLAB_OAUTH_CLIENT_ID" in msg
    assert "GITLAB_OAUTH_CLIENT_SECRET" in msg
    assert "GITLAB_OAUTH_BASE_URL" in msg


def test_oauth_mode_does_not_require_token():
    """OAuth mode validates with the three client fields and no PAT."""
    config = GitLabConfig(
        url="https://gitlab.example.com",
        auth="oauth",
        oauth_client_id="app",
        oauth_client_secret="s3cret",
        oauth_base_url="https://mcp.example.com",
    )
    config.validate()  # no raise


def test_token_mode_unchanged():
    """Default auth is token; a token is still required."""
    config = GitLabConfig(url="https://gitlab.example.com", token="")
    assert config.auth == "token"
    with pytest.raises(ValueError, match="GitLab token is required"):
        config.validate()


def test_invalid_auth_value():
    config = GitLabConfig(url="https://gitlab.example.com", token="x", auth="bogus")
    with pytest.raises(ValueError, match="GITLAB_AUTH must be"):
        config.validate()


def test_scopes_property_splits():
    assert GitLabConfig(oauth_scopes="api read_user").scopes == ["api", "read_user"]
    assert GitLabConfig().scopes == ["api"]


class _Creds:
    scopes = ["read_api"]


def test_validate_accepts_credentials_without_token():
    """Stored OAuth credentials satisfy validate() with no env token."""
    config = GitLabConfig(url="https://gitlab.example.com", token="", credentials=_Creds())
    config.validate()  # no raise


def test_validate_missing_token_mentions_login():
    config = GitLabConfig(url="https://gitlab.example.com", token="")
    with pytest.raises(ValueError, match="mcp-gitlab auth login"):
        config.validate()
    # The existing GITLAB_TOKEN match still holds.
    with pytest.raises(ValueError, match="GITLAB_TOKEN"):
        config.validate()


def test_token_scopes_property():
    assert GitLabConfig().token_scopes is None
    assert GitLabConfig(credentials=_Creds()).token_scopes == ["read_api"]


@pytest.mark.parametrize("value", ["true", "1", "yes", "TRUE", "Yes"])
def test_read_only_truthy_values(value):
    """GITLAB_READ_ONLY accepts true/1/yes case-insensitively, not only 'true'."""
    env = {
        "GITLAB_URL": "https://gitlab.example.com",
        "GITLAB_TOKEN": "x",
        "GITLAB_READ_ONLY": value,
    }
    with patch.dict(os.environ, env, clear=True):
        assert GitLabConfig.from_env().read_only is True


@pytest.mark.parametrize("value", ["false", "0", "no", ""])
def test_read_only_falsy_values(value):
    env = {
        "GITLAB_URL": "https://gitlab.example.com",
        "GITLAB_TOKEN": "x",
        "GITLAB_READ_ONLY": value,
    }
    with patch.dict(os.environ, env, clear=True):
        assert GitLabConfig.from_env().read_only is False


@pytest.mark.parametrize("value", ["false", "0", "no", "FALSE", "No"])
def test_ssl_verify_falsy_values(value):
    """GITLAB_SSL_VERIFY=false/0/no disables verification case-insensitively."""
    env = {
        "GITLAB_URL": "https://gitlab.example.com",
        "GITLAB_TOKEN": "x",
        "GITLAB_SSL_VERIFY": value,
    }
    with patch.dict(os.environ, env, clear=True):
        assert GitLabConfig.from_env().ssl_verify is False


def test_ssl_verify_default_and_truthy():
    with patch.dict(os.environ, {"GITLAB_URL": "u", "GITLAB_TOKEN": "x"}, clear=True):
        assert GitLabConfig.from_env().ssl_verify is True
    env = {"GITLAB_URL": "u", "GITLAB_TOKEN": "x", "GITLAB_SSL_VERIFY": "true"}
    with patch.dict(os.environ, env, clear=True):
        assert GitLabConfig.from_env().ssl_verify is True


def test_timeout_from_env():
    env = {"GITLAB_URL": "u", "GITLAB_TOKEN": "x", "GITLAB_TIMEOUT": "60"}
    with patch.dict(os.environ, env, clear=True):
        assert GitLabConfig.from_env().timeout == 60


def test_secrets_absent_from_repr():
    """The dataclass repr must never leak the token or OAuth credentials."""
    config = GitLabConfig(
        url="https://gitlab.example.com",
        token="glpat-supersecret",  # noqa: S106
        oauth_client_secret="oauth-secret-value",  # noqa: S106
        oauth_jwt_key="jwt-signing-key",  # noqa: S106
    )
    text = repr(config)
    assert "glpat-supersecret" not in text
    assert "oauth-secret-value" not in text
    assert "jwt-signing-key" not in text
    assert "https://gitlab.example.com" in text  # non-secret fields still shown


def test_oauth_base_url_strips_trailing_slash():
    env = {
        "GITLAB_URL": "https://gitlab.example.com",
        "GITLAB_AUTH": "oauth",
        "GITLAB_OAUTH_BASE_URL": "https://mcp.example.com/",
    }
    with patch.dict(os.environ, env, clear=True):
        config = GitLabConfig.from_env()
    assert config.oauth_base_url == "https://mcp.example.com"


def test_invalid_timeout_names_the_variable():
    env = {"GITLAB_URL": "https://gitlab.example.com", "GITLAB_TOKEN": "x", "GITLAB_TIMEOUT": "30s"}
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValueError, match="GITLAB_TIMEOUT"):
        GitLabConfig.from_env()


def test_non_positive_timeout_rejected():
    env = {"GITLAB_URL": "https://gitlab.example.com", "GITLAB_TOKEN": "x", "GITLAB_TIMEOUT": "0"}
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValueError, match="positive"):
        GitLabConfig.from_env()
