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
    env["APPDATA"] = str(tmp_path)
    env.update(extra)
    return env


def test_sse_deprecation_warning():
    runner = CliRunner()
    with (
        patch("mcp_gitlab.servers.gitlab.mcp.run_async", new_callable=AsyncMock) as run_async,
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
        run_async.assert_awaited_once()


def test_oauth_requires_streamable_http():
    """R15: --auth oauth on stdio is a usage error before anything runs."""
    runner = CliRunner()
    # Isolate os.environ: main() writes GITLAB_AUTH before the guard raises.
    with (
        patch("mcp_gitlab.servers.gitlab.mcp.run_async", new_callable=AsyncMock) as run_async,
        patch.dict("os.environ", {}, clear=False),
    ):
        result = runner.invoke(main, ["--auth", "oauth"])
    assert result.exit_code == 2
    assert "requires --transport streamable-http" in result.output
    run_async.assert_not_awaited()


def test_oauth_rejected_on_sse():
    runner = CliRunner()
    with (
        patch("mcp_gitlab.servers.gitlab.mcp.run_async", new_callable=AsyncMock) as run_async,
        patch.dict("os.environ", {}, clear=False),
    ):
        result = runner.invoke(main, ["--auth", "oauth", "--transport", "sse"])
    assert result.exit_code == 2
    assert "requires --transport streamable-http" in result.output
    run_async.assert_not_awaited()


def test_stdio_default_does_not_set_oauth():
    """R15: a plain stdio run leaves GITLAB_AUTH at 'token'."""
    runner = CliRunner()
    with (
        patch("mcp_gitlab.servers.gitlab.mcp.run_async", new_callable=AsyncMock) as run_async,
        patch.dict(
            "os.environ",
            {"GITLAB_URL": "https://gitlab.example.com", "GITLAB_TOKEN": "t"},
            clear=False,
        ),
    ):
        result = runner.invoke(main, ["--transport", "stdio"])
        assert result.exit_code == 0
        assert os.environ["GITLAB_AUTH"] == "token"
        run_async.assert_awaited_once()


# ── token-mode HTTP bind guard ──────────────────────


def _http_env(tmp_path, **extra):
    env = _no_token_env(tmp_path, GITLAB_URL=TEST_URL, GITLAB_TOKEN="t")
    env["GITLAB_HTTP_BEARER_TOKEN"] = ""
    env.update(extra)
    return env


def test_token_http_refuses_non_loopback_without_bearer(tmp_path):
    """Token mode must not serve the PAT to the network. A
    non-loopback bind with no bearer token is a usage error before anything runs."""
    runner = CliRunner()
    with (
        patch("mcp_gitlab.servers.gitlab.mcp.run_async", new_callable=AsyncMock) as run_async,
        patch.dict("os.environ", _http_env(tmp_path), clear=False),
    ):
        result = runner.invoke(main, ["--transport", "streamable-http", "--host", "192.0.2.10"])
    assert result.exit_code == 2
    assert "GITLAB_HTTP_BEARER_TOKEN" in result.output
    assert "192.0.2.10" in result.output
    run_async.assert_not_awaited()


def test_token_http_loopback_still_runs_without_bearer(tmp_path):
    """The default 127.0.0.1 bind is only reachable locally, so it needs no bearer."""
    runner = CliRunner()
    with (
        patch("mcp_gitlab.servers.gitlab.mcp.run_async", new_callable=AsyncMock) as run_async,
        patch.dict("os.environ", _http_env(tmp_path), clear=False),
    ):
        result = runner.invoke(main, ["--transport", "streamable-http"])
        assert result.exit_code == 0, result.output
        run_async.assert_awaited_once()


def test_token_http_bearer_allows_non_loopback(tmp_path):
    """A >=16-char bearer gates the HTTP face, so a non-loopback bind is allowed."""
    runner = CliRunner()
    from mcp_gitlab.servers.gitlab import mcp as server

    with (
        patch("mcp_gitlab.servers.gitlab.mcp.run_async", new_callable=AsyncMock) as run_async,
        patch.dict(
            "os.environ",
            _http_env(tmp_path, GITLAB_HTTP_BEARER_TOKEN="0123456789abcdef0123"),
            clear=False,
        ),
    ):
        try:
            result = runner.invoke(main, ["--transport", "streamable-http", "--host", "192.0.2.10"])
            assert result.exit_code == 0, result.output
            run_async.assert_awaited_once()
            assert server.auth is not None
        finally:
            server.auth = None


def test_token_http_short_bearer_is_rejected(tmp_path):
    """Too short a bearer is a usage error, not a weak gate."""
    runner = CliRunner()
    with (
        patch("mcp_gitlab.servers.gitlab.mcp.run_async", new_callable=AsyncMock) as run_async,
        patch.dict(
            "os.environ",
            _http_env(tmp_path, GITLAB_HTTP_BEARER_TOKEN="short"),
            clear=False,
        ),
    ):
        result = runner.invoke(main, ["--transport", "streamable-http", "--host", "192.0.2.10"])
    assert result.exit_code == 2
    assert "at least 16" in result.output
    run_async.assert_not_awaited()


# ── auth subcommands ──────────────────────────────────────────────


def test_bare_invocation_still_serves():
    runner = CliRunner()
    with (
        patch("mcp_gitlab.servers.gitlab.mcp.run_async", new_callable=AsyncMock) as run_async,
        patch.dict(
            "os.environ",
            {"GITLAB_URL": TEST_URL, "GITLAB_TOKEN": "t"},
            clear=False,
        ),
    ):
        result = runner.invoke(main, [])
        assert result.exit_code == 0
        run_async.assert_awaited_once()


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


def test_token_flag_hidden_from_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "--gitlab-token" not in result.output
    assert "--gitlab-url" in result.output  # control: a kept flag is still shown


def test_token_flag_still_works_and_warns(tmp_path):
    runner = CliRunner()
    env = _no_token_env(tmp_path, GITLAB_URL=TEST_URL)
    with (
        patch("mcp_gitlab.servers.gitlab.mcp.run_async", new_callable=AsyncMock) as run_async,
        patch.dict("os.environ", env, clear=False),
    ):
        result = runner.invoke(main, ["--gitlab-token", "argv-tok"])
        assert result.exit_code == 0, result.output
        run_async.assert_awaited_once()
        assert os.environ["GITLAB_TOKEN"] == "argv-tok"
    assert "--gitlab-token is deprecated" in result.stderr
    assert "GITLAB_TOKEN" in result.stderr
    assert "deprecated" not in result.stdout


def test_env_token_does_not_warn(tmp_path):
    runner = CliRunner()
    env = _no_token_env(tmp_path, GITLAB_URL=TEST_URL, GITLAB_TOKEN="env-tok")
    with (
        patch("mcp_gitlab.servers.gitlab.mcp.run_async", new_callable=AsyncMock) as run_async,
        patch.dict("os.environ", env, clear=False),
    ):
        result = runner.invoke(main, [])
        assert result.exit_code == 0, result.output
        run_async.assert_awaited_once()
    assert "deprecated" not in result.stderr


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


def test_missing_config_exits_2_with_one_line():
    """D7: a missing GITLAB_URL is one clear ``Error:`` line and exit 2, not a traceback."""
    runner = CliRunner()
    with (
        patch("mcp_gitlab.servers.gitlab.mcp.run_async", new_callable=AsyncMock) as run_async,
        patch.dict("os.environ", {}, clear=True),
    ):
        result = runner.invoke(main, [])
    assert result.exit_code == 2
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("Error:")
    assert "GITLAB_URL" in lines[0]
    run_async.assert_not_awaited()


def test_invalid_timeout_exits_2():
    """A bad GITLAB_TIMEOUT is surfaced as the same one-line exit-2 error, not a traceback."""
    runner = CliRunner()
    env = {"GITLAB_URL": TEST_URL, "GITLAB_TOKEN": "x", "GITLAB_TIMEOUT": "abc"}
    with (
        patch("mcp_gitlab.servers.gitlab.mcp.run_async", new_callable=AsyncMock) as run_async,
        patch.dict("os.environ", env, clear=True),
    ):
        result = runner.invoke(main, [])
    assert result.exit_code == 2
    assert "GITLAB_TIMEOUT" in result.output
    run_async.assert_not_awaited()


def test_oauth_missing_settings_exits_2():
    """oauth mode with missing settings exits 2 with one line, not a traceback."""
    runner = CliRunner()
    env = {"GITLAB_URL": TEST_URL, "GITLAB_AUTH": "oauth"}
    with (
        patch("mcp_gitlab.servers.gitlab.mcp.run_async", new_callable=AsyncMock) as run_async,
        patch.dict("os.environ", env, clear=True),
    ):
        result = runner.invoke(main, ["--transport", "streamable-http"])
    assert result.exit_code == 2
    assert "OAuth" in result.output
    run_async.assert_not_awaited()


def test_signed_in_without_env_token_starts(tmp_path):
    """A user signed in via `mcp-gitlab auth login` (credentials file present, no
    env token) must start the server, not be rejected for a missing token."""
    runner = CliRunner()
    env = _no_token_env(tmp_path, GITLAB_URL=TEST_URL)
    with (
        patch("mcp_gitlab.servers.gitlab.mcp.run_async", new_callable=AsyncMock) as run_async,
        patch.dict("os.environ", env, clear=True),
    ):
        CredentialStore().save(
            TEST_URL,
            {
                "client_id": "cid",
                "access_token": "at",
                "refresh_token": "rt",
                "expires_at": 9999999999,
                "scopes": ["api"],
            },
        )
        result = runner.invoke(main, [])
    assert result.exit_code == 0, result.output
    run_async.assert_awaited_once()


def test_corrupt_credentials_exits_2(tmp_path, monkeypatch):
    """A corrupt credentials.json (no env token) exits 2 with a clear message
    naming the file, not a traceback."""
    creds = tmp_path / "mcp-gitlab" / "credentials.json"
    creds.parent.mkdir(parents=True)
    creds.write_text("{not json", encoding="utf-8")
    runner = CliRunner()
    env = {"GITLAB_URL": TEST_URL, "XDG_CONFIG_HOME": str(tmp_path), "APPDATA": str(tmp_path)}
    with (
        patch("mcp_gitlab.servers.gitlab.mcp.run_async", new_callable=AsyncMock) as run_async,
        patch.dict("os.environ", env, clear=True),
    ):
        result = runner.invoke(main, [])
    assert result.exit_code == 2
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "credentials file" in result.output
    assert "is not valid JSON" in result.output
    assert str(creds) in result.output
    run_async.assert_not_awaited()
