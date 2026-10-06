"""CLI entry point tests."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import respx
from click.testing import CliRunner
from httpx import Response

from mcp_gitlab import main
from mcp_gitlab.local_auth import CredentialStore

TEST_URL = "https://gitlab.example.com"

_CLEAR_TOKENS = {
    "GITLAB_TOKEN": "",
    "GITLAB_PAT": "",
    "GITLAB_PERSONAL_ACCESS_TOKEN": "",
    "GITLAB_API_TOKEN": "",
    "GITLAB_OAUTH_CLIENT_ID": "",
}


def _no_token_env(tmp_path, **extra):
    env = dict.fromkeys(_CLEAR_TOKENS, "")
    env["XDG_CONFIG_HOME"] = str(tmp_path)
    env.update(extra)
    return env


def test_sse_deprecation_warning():
    runner = CliRunner()
    with (
        patch("mcp_gitlab.asyncio.run") as mock_run,
        patch.dict(
            "os.environ",
            {"GITLAB_URL": "https://gitlab.example.com", "GITLAB_TOKEN": "test-token"},
        ),
    ):
        result = runner.invoke(main, ["--transport", "sse"])
        assert result.exit_code == 0
        assert (
            "Warning: --transport sse uses the HTTP+SSE transport, deprecated in MCP 2026-07-28"
            in result.output
        )
        assert "Use --transport streamable-http" in result.output
        mock_run.assert_called_once()


def test_oauth_requires_streamable_http():
    """R15: --auth oauth on stdio is a usage error before anything runs."""
    runner = CliRunner()
    # Isolate os.environ: main() writes GITLAB_AUTH before the guard raises.
    with (
        patch("mcp_gitlab.asyncio.run") as mock_run,
        patch.dict("os.environ", {}, clear=False),
    ):
        result = runner.invoke(main, ["--auth", "oauth"])
    assert result.exit_code == 2
    assert "requires --transport streamable-http" in result.output
    mock_run.assert_not_called()


def test_oauth_rejected_on_sse():
    runner = CliRunner()
    with (
        patch("mcp_gitlab.asyncio.run") as mock_run,
        patch.dict("os.environ", {}, clear=False),
    ):
        result = runner.invoke(main, ["--auth", "oauth", "--transport", "sse"])
    assert result.exit_code == 2
    assert "requires --transport streamable-http" in result.output
    mock_run.assert_not_called()


def test_stdio_default_does_not_set_oauth():
    """R15: a plain stdio run leaves GITLAB_AUTH at 'token'."""
    runner = CliRunner()
    with (
        patch("mcp_gitlab.asyncio.run") as mock_run,
        patch.dict(
            "os.environ",
            {"GITLAB_URL": "https://gitlab.example.com", "GITLAB_TOKEN": "t"},
            clear=False,
        ),
    ):
        result = runner.invoke(main, ["--transport", "stdio"])
        assert result.exit_code == 0
        assert os.environ["GITLAB_AUTH"] == "token"
        mock_run.assert_called_once()


# ── auth subcommands ──────────────────────────────────────────────


def test_bare_invocation_still_serves():
    runner = CliRunner()
    with (
        patch("mcp_gitlab.asyncio.run") as mock_run,
        patch.dict(
            "os.environ",
            {"GITLAB_URL": TEST_URL, "GITLAB_TOKEN": "t"},
            clear=False,
        ),
    ):
        result = runner.invoke(main, [])
        assert result.exit_code == 0
        mock_run.assert_called_once()


def test_auth_login_does_not_start_server(tmp_path):
    runner = CliRunner()
    token = {"access_token": "at", "refresh_token": "rt", "expires_in": 7200, "scope": "api"}
    with (
        patch("mcp_gitlab.local_auth.device_login", AsyncMock(return_value=token)),
        patch("mcp_gitlab._fetch_username", AsyncMock(return_value="vish")),
        patch("mcp_gitlab.asyncio.run", wraps=asyncio.run) as mock_run,
        patch("mcp_gitlab.servers.gitlab.mcp.run_async") as run_async,
        patch.dict("os.environ", _no_token_env(tmp_path), clear=False),
    ):
        result = runner.invoke(
            main, ["auth", "login", "--client-id", "x", "--gitlab-url", TEST_URL]
        )
    assert result.exit_code == 0, result.output
    assert "Signed in" in result.output
    run_async.assert_not_called()
    mock_run.assert_called_once()
    assert (tmp_path / "mcp-gitlab" / "credentials.json").exists()


def test_auth_login_requires_client_id(tmp_path):
    runner = CliRunner()
    with patch.dict("os.environ", _no_token_env(tmp_path), clear=False):
        result = runner.invoke(main, ["auth", "login", "--gitlab-url", TEST_URL])
    assert result.exit_code == 2
    assert "GITLAB_OAUTH_CLIENT_ID" in result.output


def test_auth_status_not_signed_in(tmp_path):
    runner = CliRunner()
    with patch.dict("os.environ", _no_token_env(tmp_path), clear=False):
        result = runner.invoke(main, ["auth", "status", "--gitlab-url", TEST_URL])
    assert result.exit_code == 1
    assert "Not signed in" in result.output


def test_auth_logout_revokes_then_deletes(tmp_path):
    runner = CliRunner()
    env = _no_token_env(tmp_path)
    with patch.dict("os.environ", env, clear=False):
        store = CredentialStore()
        store.save(
            TEST_URL,
            {
                "client_id": "cid",
                "access_token": "at",
                "refresh_token": "rt",
                "expires_at": 9999999999,
                "scopes": ["api"],
            },
        )
        with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
            revoke = router.post("/oauth/revoke").mock(return_value=Response(200))
            result = runner.invoke(main, ["auth", "logout", "--gitlab-url", TEST_URL])
        assert result.exit_code == 0, result.output
        assert revoke.called
        body = parse_qs(revoke.calls.last.request.content.decode())
        assert body["client_id"][0] == "cid"
        assert body["token"][0] == "at"
        assert "client_secret" not in body
        assert not store.path.exists()


def test_sigint_exits_130(tmp_path):
    runner = CliRunner()

    def boom(*_a, **_k):
        raise KeyboardInterrupt

    with (
        patch("mcp_gitlab.local_auth.device_login", boom),
        patch.dict("os.environ", _no_token_env(tmp_path), clear=False),
    ):
        result = runner.invoke(
            main, ["auth", "login", "--client-id", "x", "--gitlab-url", TEST_URL]
        )
    assert result.exit_code == 130
    assert "Cancelled" in result.output
    assert "Traceback" not in result.output
