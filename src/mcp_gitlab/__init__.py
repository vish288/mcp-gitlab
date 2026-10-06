"""MCP server for GitLab API."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from typing import TYPE_CHECKING, Any

import click
import httpx
from dotenv import load_dotenv

if TYPE_CHECKING:
    from collections.abc import Awaitable

_TOKEN_ENV_VARS = (
    "GITLAB_TOKEN",
    "GITLAB_PAT",
    "GITLAB_PERSONAL_ACCESS_TOKEN",
    "GITLAB_API_TOKEN",
)


@click.group(invoke_without_command=True)
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse", "streamable-http"]),
    default="stdio",
    help="MCP transport type (sse is deprecated; use streamable-http)",
)
@click.option("--port", default=8000, help="Port for HTTP transports")
@click.option("--host", default="127.0.0.1", help="Host for HTTP transports")
@click.option("--gitlab-url", envvar="GITLAB_URL", help="GitLab instance URL")
@click.option("--gitlab-token", envvar="GITLAB_TOKEN", help="GitLab personal access token")
@click.option("--read-only", is_flag=True, help="Disable write operations")
@click.option(
    "--auth",
    type=click.Choice(["token", "oauth"]),
    envvar="GITLAB_AUTH",
    default="token",
    help="token (PAT from env, default) or oauth (OAuth 2.1 proxy to GitLab; streamable-http only)",
)
@click.pass_context
def main(
    ctx: click.Context,
    transport: str,
    port: int,
    host: str,
    gitlab_url: str | None,
    gitlab_token: str | None,
    read_only: bool,
    auth: str,
) -> None:
    """Run the GitLab MCP server. Subcommands: auth."""
    if ctx.invoked_subcommand is not None:
        return  # `mcp-gitlab auth ...`: the subcommand runs instead of the server

    load_dotenv()

    if gitlab_url:
        os.environ["GITLAB_URL"] = gitlab_url
    if gitlab_token:
        os.environ["GITLAB_TOKEN"] = gitlab_token
    if read_only:
        os.environ["GITLAB_READ_ONLY"] = "true"
    os.environ["GITLAB_AUTH"] = auth

    if auth == "oauth" and transport != "streamable-http":
        msg = (
            "--auth oauth requires --transport streamable-http "
            "(OAuth applies to HTTP only; stdio uses env credentials)"
        )
        raise click.UsageError(msg)

    if transport == "sse":
        click.echo(
            "Warning: --transport sse uses the HTTP+SSE transport, deprecated in MCP 2026-07-28. "
            "Use --transport streamable-http.",
            err=True,
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s | %(message)s",
    )

    from .servers import prompts, resources  # noqa: F401 — registers decorators
    from .servers.gitlab import mcp

    if auth == "oauth":
        from .config import GitLabConfig
        from .oauth import GitLabProvider

        cfg = GitLabConfig.from_env()
        cfg.validate()
        mcp.auth = GitLabProvider(cfg)
        logging.getLogger(__name__).info(
            "Auth: oauth (GitLab app %s, scopes %s)", cfg.oauth_client_id, cfg.oauth_scopes
        )

    run_kwargs: dict = {"transport": transport}
    if transport != "stdio":
        run_kwargs["host"] = host
        run_kwargs["port"] = port

    asyncio.run(mcp.run_async(show_banner=False, **run_kwargs))


# ── auth subcommands (local OAuth sign-in for stdio) ──────────────
#
# These never start the server. Each runs in a terminal, prints to stdout,
# reports errors on stderr with exit code 1 (2 for a missing client ID), and
# exits 130 on Ctrl-C / 143 on SIGTERM with one line and no traceback.


@main.group()
def auth() -> None:
    """Sign in to GitLab without a personal access token."""


def _env_token_set() -> bool:
    return any(os.environ.get(name) for name in _TOKEN_ENV_VARS)


def _store_for(cfg: Any) -> Any:
    from .local_auth import CredentialStore

    return CredentialStore(verify=cfg.ssl_verify, timeout=cfg.timeout)


def _auth_config() -> Any:
    from .config import GitLabConfig

    return GitLabConfig.from_env()


def _sigterm(*_: Any) -> None:
    raise SystemExit(143)


def _login_error_message(code: str, url: str, scopes: str) -> str:
    messages = {
        "invalid_client": (
            "GitLab rejected the client ID (invalid_client). "
            "The app must be non-confidential and the ID correct."
        ),
        "invalid_scope": (
            f'GitLab rejected the scopes "{scopes}" (invalid_scope). '
            "Tick the same scopes on the OAuth application."
        ),
        "access_denied": "Sign-in was denied in GitLab.",
        "expired_token": "Sign-in timed out after 5 min. Run mcp-gitlab auth login again.",
        "timeout": "Sign-in timed out after 5 min. Run mcp-gitlab auth login again.",
        "device_404": (
            "This GitLab does not offer the device flow (needs GitLab 17.9 or later). "
            "Try mcp-gitlab auth login --web."
        ),
        "state": (
            "Callback state did not match; ignoring the response. Run mcp-gitlab auth login again."
        ),
    }
    return messages.get(code, f"Sign-in failed ({code}).")


def _run(coro: Awaitable[None], *, url: str, scopes: str = "") -> None:
    """Drive an auth coroutine with the owner's process-hygiene contract:
    Ctrl-C -> 130, SIGTERM -> 143, flow/network/OS errors -> exit 1, each with
    one stderr line and no traceback. ``asyncio.run`` cancellation runs the
    flows' ``finally`` blocks (socket closed, temp file unlinked)."""
    from .local_auth import LoginError, RefreshError

    signal.signal(signal.SIGTERM, _sigterm)
    try:
        asyncio.run(coro)
    except KeyboardInterrupt:
        click.echo("Cancelled. Nothing was saved.", err=True)
        sys.exit(130)
    except SystemExit as e:
        if e.code == 143:
            click.echo("Terminated. Nothing was saved.", err=True)
        raise
    except LoginError as e:
        click.echo(_login_error_message(e.code, url, scopes), err=True)
        sys.exit(1)
    except RefreshError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    except httpx.HTTPError as e:
        click.echo(f"Could not reach {url}: {e}.", err=True)
        sys.exit(1)
    except OSError as e:
        click.echo(f"Could not write credentials: {e}.", err=True)
        sys.exit(1)


async def _fetch_username(http: httpx.AsyncClient, url: str, access_token: str) -> str | None:
    """Best-effort ``@username`` from GET /api/v4/user; None when offline."""
    try:
        resp = await http.get(
            f"{url}/api/v4/user", headers={"Authorization": f"Bearer {access_token}"}
        )
    except httpx.HTTPError:
        return None
    if resp.status_code == 200:
        body = resp.json()
        return body.get("username") if isinstance(body, dict) else None
    return None


@auth.command()
@click.option("--gitlab-url", envvar="GITLAB_URL", default="https://gitlab.com", show_default=True)
@click.option("--client-id", envvar="GITLAB_OAUTH_CLIENT_ID")
@click.option("--scopes", default="api", show_default=True, help="Space-separated GitLab scopes")
@click.option("--web", "use_web", is_flag=True, help="Browser sign-in (PKCE) instead of device")
@click.option("--force", is_flag=True, help="Re-login even when valid credentials exist")
def login(gitlab_url: str, client_id: str | None, scopes: str, use_web: bool, force: bool) -> None:
    """Sign in to GitLab and store the tokens locally."""
    load_dotenv()
    from . import local_auth

    cfg = _auth_config()
    store = _store_for(cfg)
    resolved = local_auth.resolve_client_id(gitlab_url, client_id)
    if not resolved:
        click.echo(
            f"No OAuth client ID for {gitlab_url}. Set GITLAB_OAUTH_CLIENT_ID or pass "
            "--client-id. Register a non-confidential app with redirect URI "
            'http://127.0.0.1/callback; see README "Sign in without a token".',
            err=True,
        )
        sys.exit(2)
    if _env_token_set():
        click.echo(
            "Note: GITLAB_TOKEN is set; the server will use it instead of stored credentials."
        )

    async def _do() -> None:
        http = httpx.AsyncClient(verify=cfg.ssl_verify, timeout=cfg.timeout)
        existing = store.load(gitlab_url)
        try:
            if existing is not None and not existing.near_expiry() and not force:
                username = await _fetch_username(http, gitlab_url, existing.access_token)
                suffix = f" as @{username}" if username else ""
                click.echo(
                    f"Already signed in to {gitlab_url}{suffix}. Use --force to sign in again."
                )
                return
            click.echo(f"GitLab: {gitlab_url}")
            click.echo(f"Scopes: {scopes}")
            click.echo("")
            if use_web:
                token, redirect_uri = await local_auth.web_login(
                    http, gitlab_url, resolved, scopes, echo=click.echo
                )
            else:
                token = await local_auth.device_login(
                    http, gitlab_url, resolved, scopes, echo=click.echo
                )
                redirect_uri = None
            entry = local_auth.build_entry(resolved, token, scopes, redirect_uri)
            username = await _fetch_username(http, gitlab_url, entry["access_token"])
            store.save(gitlab_url, entry)
            suffix = f" as @{username}" if username else ""
            click.echo(f"Signed in to {gitlab_url}{suffix} (scopes: {' '.join(entry['scopes'])}).")
            click.echo(f"Saved to {store.path}.")
            click.echo("")
            click.echo(f"Start the server with GITLAB_URL={gitlab_url} and no token.")
        finally:
            await http.aclose()
            if existing is not None:
                await existing.aclose()

    _run(_do(), url=gitlab_url, scopes=scopes)


@auth.command()
@click.option("--gitlab-url", envvar="GITLAB_URL")
def status(gitlab_url: str | None) -> None:
    """Show stored credentials and token freshness."""
    load_dotenv()
    cfg = _auth_config()
    store = _store_for(cfg)

    if _env_token_set():
        click.echo(
            "Note: GITLAB_TOKEN is set; the server will use it instead of stored credentials."
        )

    from .local_auth import REFRESH_MARGIN, RefreshError, host_key

    if gitlab_url:
        hosts = [host_key(gitlab_url)]
        if store.load(gitlab_url) is None:
            click.echo("Not signed in. Run mcp-gitlab auth login.", err=True)
            sys.exit(1)
    else:
        hosts = list(store.all().keys())
        if not hosts:
            click.echo("Not signed in. Run mcp-gitlab auth login.", err=True)
            sys.exit(1)

    def _fmt(seconds: float) -> str:
        minutes = max(0, int(seconds // 60))
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m" if hours else f"{minutes}m"

    def _short(cid: str) -> str:
        return f"{cid[:4]}...{cid[-3:]}" if len(cid) > 10 else cid

    async def _do() -> None:
        failed = False
        for key in hosts:
            creds = store.load(key)
            if creds is None:  # pragma: no cover — hosts come from the store
                continue
            http = httpx.AsyncClient(verify=cfg.ssl_verify, timeout=cfg.timeout)
            try:
                click.echo(key)
                username = await _fetch_username(http, key, creds.access_token)
                click.echo(f"  Account:  {'@' + username if username else '(offline)'}")
                click.echo(f"  Scopes:   {' '.join(creds.scopes)}")
                remaining = creds.expires_at - time.time()
                if remaining >= REFRESH_MARGIN:
                    click.echo(
                        f"  Token:    expires in {_fmt(remaining)} (refreshes automatically)"
                    )
                else:
                    try:
                        await creds.refresh()
                        left = creds.expires_at - time.time()
                        click.echo(
                            f"  Token:    refreshed; expires in {_fmt(left)} "
                            "(refreshes automatically)"
                        )
                    except RefreshError as e:
                        click.echo(
                            f"  Token:    expired; refresh failed ({e.error}). "
                            "Run mcp-gitlab auth login."
                        )
                        failed = True
                click.echo(f"  App:      {_short(creds.client_id)} (GITLAB_OAUTH_CLIENT_ID)")
                click.echo(f"  Storage:  {store.path}")
            finally:
                await http.aclose()
                await creds.aclose()
        if failed:
            sys.exit(1)

    _run(_do(), url=hosts[0])


@auth.command()
@click.option("--gitlab-url", envvar="GITLAB_URL", default="https://gitlab.com", show_default=True)
def logout(gitlab_url: str) -> None:
    """Revoke the token at GitLab and remove the stored credentials."""
    load_dotenv()
    from . import local_auth

    cfg = _auth_config()
    store = _store_for(cfg)

    async def _do() -> None:
        creds = store.load(gitlab_url)
        if creds is None:
            click.echo(f"No credentials for {gitlab_url}.")
            return
        http = httpx.AsyncClient(verify=cfg.ssl_verify, timeout=cfg.timeout)
        try:
            try:
                await local_auth.revoke(http, gitlab_url, creds.client_id, creds.access_token)
                click.echo(f"Revoked the token at {gitlab_url}.")
            except httpx.HTTPError as e:
                click.echo(
                    f"Could not revoke at {gitlab_url} ({e}); removed the local credentials "
                    "anyway. Revoke under GitLab Settings → Applications → Authorized "
                    "applications."
                )
            store.delete(gitlab_url)
            click.echo(f"Removed credentials for {gitlab_url}.")
        finally:
            await http.aclose()
            await creds.aclose()

    _run(_do(), url=gitlab_url)


if __name__ == "__main__":
    main()
