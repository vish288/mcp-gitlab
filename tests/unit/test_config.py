"""Tests for GitLab configuration."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from mcp_gitlab.config import GitLabConfig


def test_config_from_env():
    env = {"GITLAB_URL": "https://gitlab.example.com", "GITLAB_TOKEN": "glpat-abc123"}
    with patch.dict(os.environ, env, clear=False):
        config = GitLabConfig.from_env()
    assert config.url == "https://gitlab.example.com"
    assert config.token == "glpat-abc123"
    assert config.read_only is False
    assert config.timeout == 30


def test_config_from_env_with_pat():
    env = {"GITLAB_URL": "https://gitlab.example.com", "GITLAB_PAT": "glpat-xyz"}
    with patch.dict(os.environ, env, clear=False):
        config = GitLabConfig.from_env()
    assert config.token == "glpat-xyz"


def test_config_read_only():
    env = {
        "GITLAB_URL": "https://gitlab.example.com",
        "GITLAB_TOKEN": "x",
        "GITLAB_READ_ONLY": "true",
    }
    with patch.dict(os.environ, env, clear=False):
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
    with patch.dict(os.environ, env, clear=False):
        config = GitLabConfig.from_env()
    assert config.token == "glpat-pat"


def test_config_from_env_with_api_token():
    env = {"GITLAB_URL": "https://gitlab.example.com", "GITLAB_API_TOKEN": "glpat-api"}
    with patch.dict(os.environ, env, clear=False):
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
    with patch.dict(os.environ, env, clear=False):
        config = GitLabConfig.from_env()
    assert config.token == "winner"


def test_config_url_strips_trailing_slash():
    env = {"GITLAB_URL": "https://gitlab.example.com/", "GITLAB_TOKEN": "x"}
    with patch.dict(os.environ, env, clear=False):
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


def test_oauth_base_url_strips_trailing_slash():
    env = {
        "GITLAB_URL": "https://gitlab.example.com",
        "GITLAB_AUTH": "oauth",
        "GITLAB_OAUTH_BASE_URL": "https://mcp.example.com/",
    }
    with patch.dict(os.environ, env, clear=False):
        config = GitLabConfig.from_env()
    assert config.oauth_base_url == "https://mcp.example.com"
