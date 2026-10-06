"""Local OAuth sign-in for the stdio transport.

``mcp-gitlab auth login`` signs in to a GitLab instance as a public OAuth
client (RFC 8628 device grant by default, RFC 8252 loopback + PKCE with
``--web``) and stores the tokens in one per-user file. The server then reads
that file when no env token is set, refreshing the access token on demand
under a cross-process lock.

This is not MCP authorization: the MCP 2026-07-28 spec says stdio
implementations SHOULD NOT follow the authorization spec and should retrieve
credentials from the environment. The server never prompts; all interaction
lives in the separate ``auth`` commands.

Stdlib only for the flows; network goes through ``httpx`` (already a
dependency), so respx can mock it in tests.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import tempfile
import time
import webbrowser
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .exceptions import GitLabAuthError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

# Proactive-refresh margin, matching glab: refresh once the token is within
# five minutes of expiry rather than waiting for a 401.
REFRESH_MARGIN = 300

# Public (non-confidential) OAuth application owned by the maintainer. Empty
# until registered; see the README "Sign in without a token". The spec does
# not invent an ID.
GITLAB_COM_CLIENT_ID = ""
DEFAULT_CLIENT_IDS = {"https://gitlab.com": GITLAB_COM_CLIENT_ID}

_DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"  # noqa: S105 — not a secret


class LoginError(Exception):
    """A sign-in flow failed. ``code`` is the OAuth error or a local marker
    (``device_404``, ``timeout``, ``state``); the CLI maps it to a message."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RefreshError(GitLabAuthError):
    """A stored token could not be refreshed. Presents as a 401 auth error so
    the existing ``_err`` auth hint (with the login pointer) applies."""

    def __init__(self, error: str) -> None:
        self.error = error
        super().__init__(401, f"stored OAuth credentials expired or revoked ({error})")


# ── Paths and keys ────────────────────────────────────────────────


def credentials_path() -> Path:
    """The per-user credentials file. Same place on macOS and Linux (as gh
    does); ``platformdirs`` would agree but is not a declared dependency."""
    if os.name == "nt":  # pragma: no cover — exercised only on Windows
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "mcp-gitlab" / "credentials.json"


def host_key(url: str) -> str:
    """Normalise a GitLab base URL to the storage key: scheme and host
    lower-cased, no trailing slash. Equals ``GitLabConfig.url`` for normal
    inputs and keeps a subfolder install (``https://host/gitlab``) distinct."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    return f"{scheme}://{netloc}{parsed.path}".rstrip("/")


def resolve_client_id(url: str, client_id: str | None) -> str | None:
    """``--client-id`` > ``GITLAB_OAUTH_CLIENT_ID`` > built-in default, or None."""
    if client_id:
        return client_id
    return DEFAULT_CLIENT_IDS.get(host_key(url)) or None


def _json(resp: httpx.Response) -> dict[str, Any]:
    try:
        body = resp.json()
    except (ValueError, json.JSONDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


# ── Cross-process lock ────────────────────────────────────────────


def _flock_exclusive(fd: int) -> None:
    """Take an exclusive, blocking lock on ``fd``. The kernel releases it when
    the holder's fd is closed or the process dies, so there is no stale-lock
    case."""
    if os.name == "nt":  # pragma: no cover — untested in CI (Linux only)
        import msvcrt

        # ponytail: untested in CI; a Windows user report is the trigger to add a runner
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                return
            except OSError:
                time.sleep(0.1)
    else:
        import fcntl

        # ponytail: blocking flock; add a timeout if a hang is ever observed
        fcntl.flock(fd, fcntl.LOCK_EX)


# ── Store ─────────────────────────────────────────────────────────


class CredentialStore:
    """The credentials file: load, save (atomic, 0600), delete, and a lock.

    One credential set per GitLab base URL. ``verify`` and ``timeout`` seed the
    httpx client that refresh uses, so a self-signed instance still refreshes.
    """

    def __init__(self, path: Path | None = None, *, verify: bool = True, timeout: int = 30) -> None:
        self.path = path or credentials_path()
        self._lock_path = self.path.with_name("credentials.lock")
        self._verify = verify
        self._timeout = timeout

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": 1, "hosts": {}}
        if not isinstance(data, dict) or "hosts" not in data:
            return {"version": 1, "hosts": {}}
        return data

    def all(self) -> dict[str, dict]:
        return self._read().get("hosts", {})

    def load(self, url: str) -> LocalCredentials | None:
        key = host_key(url)
        entry = self.all().get(key)
        if entry is None:
            return None
        http = httpx.AsyncClient(verify=self._verify, timeout=self._timeout)
        return LocalCredentials.from_entry(key, entry, store=self, http=http)

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Block until this process holds the file lock, then release on exit.

        Synchronous; used by ``save``/``delete`` and by the CLI, where there is
        no in-process concurrency. The async refresh path locks via a thread so
        it never blocks the event loop (see ``LocalCredentials.refresh``)."""
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            _flock_exclusive(fd)
            yield
        finally:
            os.close(fd)

    def _write_atomic(self, data: dict[str, Any]) -> None:
        """Write the file so a reader never sees a partial one and the mode is
        0600 before the first byte. Caller holds the lock."""
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(
            dir=self.path.parent, prefix=".credentials.", delete=False
        )
        try:
            if hasattr(os, "fchmod"):  # absent on Windows < 3.13; %APPDATA% is per-user there
                os.fchmod(tmp.fileno(), 0o600)
            tmp.write(json.dumps(data, indent=2).encode("utf-8"))
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp.close()
            os.replace(tmp.name, self.path)
        except BaseException:
            tmp.close()
            Path(tmp.name).unlink(missing_ok=True)
            raise

    def save(self, url: str, entry: dict) -> None:
        with self.locked():
            self._save_held(url, entry)

    def _save_held(self, url: str, entry: dict) -> None:
        """Save while the lock is already held (the refresh path)."""
        data = self._read()
        data.setdefault("version", 1)
        data.setdefault("hosts", {})[host_key(url)] = entry
        self._write_atomic(data)

    def delete(self, url: str) -> None:
        with self.locked():
            data = self._read()
            data.get("hosts", {}).pop(host_key(url), None)
            if data.get("hosts"):
                self._write_atomic(data)
            else:
                self.path.unlink(missing_ok=True)


class LocalCredentials:
    """A stored OAuth session for one host, able to refresh itself."""

    def __init__(
        self,
        *,
        url: str,
        client_id: str,
        access_token: str,
        refresh_token: str,
        expires_at: int,
        scopes: list[str],
        redirect_uri: str | None,
        store: CredentialStore,
        http: httpx.AsyncClient,
    ) -> None:
        self.url = url
        self.client_id = client_id
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at
        self.scopes = scopes
        self.redirect_uri = redirect_uri
        self._store = store
        self._http = http

    @classmethod
    def from_entry(
        cls, url: str, entry: dict, *, store: CredentialStore, http: httpx.AsyncClient
    ) -> LocalCredentials:
        return cls(
            url=url,
            client_id=entry.get("client_id", ""),
            access_token=entry.get("access_token", ""),
            refresh_token=entry.get("refresh_token", ""),
            expires_at=int(entry.get("expires_at", 0)),
            scopes=list(entry.get("scopes", [])),
            redirect_uri=entry.get("redirect_uri"),
            store=store,
            http=http,
        )

    def to_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "client_id": self.client_id,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scopes": self.scopes,
        }
        if self.redirect_uri:
            entry["redirect_uri"] = self.redirect_uri
        return entry

    def near_expiry(self) -> bool:
        return self.expires_at - time.time() < REFRESH_MARGIN

    async def aclose(self) -> None:
        await self._http.aclose()

    async def bearer(self) -> str:
        if self.near_expiry():
            await self.refresh()
        return self.access_token

    def _adopt_response(self, data: dict[str, Any]) -> None:
        self.access_token = data["access_token"]
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        created = int(data.get("created_at", time.time()))
        self.expires_at = created + int(data.get("expires_in", 7200))
        if data.get("scope"):
            self.scopes = data["scope"].split()

    async def refresh(self) -> None:
        """Refresh the access token, persisting the rotated pair under the
        file lock after re-reading. The re-read makes rotation safe across
        server processes: a loser adopts the winner's tokens instead of
        spending the already-spent single-use refresh token.

        The lock is taken in a worker thread so a blocking wait never stalls
        the event loop; concurrent in-process refreshes serialise the same way
        a second process would."""
        self._store.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self._store._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            await asyncio.to_thread(_flock_exclusive, fd)
            fresh = self._store.all().get(self.url)
            if (
                fresh
                and fresh.get("access_token") != self.access_token
                and int(fresh.get("expires_at", 0)) - time.time() >= REFRESH_MARGIN
            ):
                self.access_token = fresh["access_token"]
                self.refresh_token = fresh.get("refresh_token", self.refresh_token)
                self.expires_at = int(fresh.get("expires_at", 0))
                self.scopes = list(fresh.get("scopes", self.scopes))
                return
            data: dict[str, Any] = {
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "refresh_token": self.refresh_token,
            }
            if self.redirect_uri:
                data["redirect_uri"] = self.redirect_uri
            resp = await self._http.post(f"{self.url}/oauth/token", data=data)
            if resp.status_code != 200:
                raise RefreshError(_json(resp).get("error", str(resp.status_code)))
            self._adopt_response(_json(resp))
            self._store._save_held(self.url, self.to_entry())
        finally:
            os.close(fd)


# ── Flows ─────────────────────────────────────────────────────────


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


async def device_login(
    http: httpx.AsyncClient,
    url: str,
    client_id: str,
    scopes: str,
    *,
    echo: Callable[[str], Any],
) -> dict[str, Any]:
    """RFC 8628 device grant. Returns the token response dict."""
    resp = await http.post(
        f"{url}/oauth/authorize_device", data={"client_id": client_id, "scope": scopes}
    )
    if resp.status_code == 404:
        code = "device_404"
        raise LoginError(code)
    body = _json(resp)
    if resp.status_code != 200:
        raise LoginError(body.get("error", str(resp.status_code)))

    device_code = body["device_code"]
    interval = int(body.get("interval", 5))
    expires_in = int(body.get("expires_in", 300))
    deadline = time.monotonic() + expires_in

    echo(f"Open {body['verification_uri']} and enter the code:")
    echo("")
    echo(f"    {body['user_code']}")
    echo("")
    if body.get("verification_uri_complete"):
        echo(f"Or open {body['verification_uri_complete']}")
    echo(f"Waiting for approval (expires in {max(1, round(expires_in / 60))} min)...")

    while True:
        if time.monotonic() >= deadline:
            code = "expired_token"
            raise LoginError(code)
        await asyncio.sleep(interval)
        tok = await http.post(
            f"{url}/oauth/token",
            data={
                "grant_type": _DEVICE_GRANT,
                "device_code": device_code,
                "client_id": client_id,
            },
        )
        if tok.status_code == 200:
            return _json(tok)
        err = _json(tok).get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        raise LoginError(err or str(tok.status_code))


async def web_login(
    http: httpx.AsyncClient,
    url: str,
    client_id: str,
    scopes: str,
    *,
    echo: Callable[[str], Any],
    open_browser: Callable[[str], Any] = webbrowser.open,
    timeout: float = 300,
) -> tuple[dict[str, Any], str]:
    """RFC 8252 loopback + PKCE (S256). Returns (token response, redirect_uri)."""
    verifier = secrets.token_urlsafe(48)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    state = secrets.token_urlsafe(16)
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:  # silence stderr logging
            pass

        def _reply(self, status: int, message: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(message.encode("utf-8"))

        def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
            parsed = urlparse(self.path)
            if parsed.path != "/callback":
                self._reply(404, "Not found.")
                return
            query = parse_qs(parsed.query)
            if not secrets.compare_digest((query.get("state") or [""])[0], state):
                result["error"] = "state"
                self._reply(400, "Sign-in state did not match. You can close this tab.")
                return
            if "error" in query:
                result["error"] = query["error"][0]
                self._reply(200, "Sign-in was denied. You can close this tab.")
                return
            result["code"] = (query.get("code") or [""])[0]
            self._reply(200, "Signed in to mcp-gitlab. You can close this tab.")

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = timeout
    try:
        port = server.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}/callback"
        authorize_url = f"{url}/oauth/authorize?" + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": scopes,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        echo("Opening your browser. If it does not open, visit:")
        echo("")
        echo(f"    {authorize_url}")
        echo("")
        echo(f"Waiting for the browser (times out in {max(1, round(timeout / 60))} min)...")
        open_browser(authorize_url)
        await asyncio.to_thread(server.handle_request)
    finally:
        server.socket.close()

    if result.get("error") == "state":
        code = "state"
        raise LoginError(code)
    if "error" in result:
        raise LoginError(result["error"])
    if not result.get("code"):
        code = "timeout"
        raise LoginError(code)

    tok = await http.post(
        f"{url}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": result["code"],
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
    )
    if tok.status_code != 200:
        raise LoginError(_json(tok).get("error", str(tok.status_code)))
    return _json(tok), redirect_uri


async def revoke(http: httpx.AsyncClient, url: str, client_id: str, token: str) -> None:
    """Revoke a token at GitLab. Public client: ``client_id`` only, no secret."""
    resp = await http.post(f"{url}/oauth/revoke", data={"client_id": client_id, "token": token})
    resp.raise_for_status()


def build_entry(
    client_id: str, token: dict[str, Any], requested_scopes: str, redirect_uri: str | None = None
) -> dict[str, Any]:
    """A credentials-file entry from a token response. ``scopes`` come from the
    response ``scope`` (so a server-side downgrade is recorded), falling back to
    what was requested. ``expires_at = created_at + expires_in``."""
    created = int(token.get("created_at", time.time()))
    entry: dict[str, Any] = {
        "client_id": client_id,
        "access_token": token["access_token"],
        "refresh_token": token.get("refresh_token", ""),
        "expires_at": created + int(token.get("expires_in", 7200)),
        "scopes": token.get("scope", "").split() or requested_scopes.split(),
    }
    if redirect_uri:
        entry["redirect_uri"] = redirect_uri
    return entry
