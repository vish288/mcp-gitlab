"""Tests for local OAuth sign-in (device + web flows, store, refresh, lock)."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import multiprocessing
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from mcp_gitlab import local_auth
from mcp_gitlab.exceptions import GitLabAuthError
from mcp_gitlab.local_auth import CredentialStore, LoginError, build_entry, device_login, web_login

TEST_URL = "https://gitlab.example.com"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return CredentialStore()


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(local_auth.asyncio, "sleep", fake_sleep)
    return sleeps


def _device_init(**over):
    body = {
        "device_code": "DEV",
        "user_code": "ABCD-EFGH",
        "verification_uri": f"{TEST_URL}/oauth/device",
        "verification_uri_complete": f"{TEST_URL}/oauth/device?user_code=ABCD-EFGH",
        "expires_in": 300,
        "interval": 5,
    }
    body.update(over)
    return httpx.Response(200, json=body)


def _token_ok(**over):
    body = {
        "access_token": "at-1",
        "refresh_token": "rt-1",
        "expires_in": 7200,
        "scope": "api",
        "created_at": int(time.time()),
    }
    body.update(over)
    return httpx.Response(200, json=body)


# ── Device flow ───────────────────────────────────────────────────


async def test_device_success(no_sleep):
    echoed: list[str] = []
    with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
        router.post("/oauth/authorize_device").mock(return_value=_device_init())
        router.post("/oauth/token").mock(
            side_effect=[
                httpx.Response(400, json={"error": "authorization_pending"}),
                _token_ok(),
            ]
        )
        async with httpx.AsyncClient() as http:
            token = await device_login(http, TEST_URL, "cid", "api", echo=echoed.append)
    assert token["access_token"] == "at-1"
    assert token["refresh_token"] == "rt-1"
    assert any("ABCD-EFGH" in line for line in echoed)
    assert any(f"{TEST_URL}/oauth/device" in line for line in echoed)


async def test_device_slow_down_adds_five_seconds(no_sleep):
    with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
        router.post("/oauth/authorize_device").mock(return_value=_device_init())
        router.post("/oauth/token").mock(
            side_effect=[httpx.Response(400, json={"error": "slow_down"}), _token_ok()]
        )
        async with httpx.AsyncClient() as http:
            await device_login(http, TEST_URL, "cid", "api", echo=lambda _s: None)
    assert no_sleep == [5, 10]


async def test_device_expired_token_stops(no_sleep):
    with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
        router.post("/oauth/authorize_device").mock(return_value=_device_init())
        route = router.post("/oauth/token").mock(
            return_value=httpx.Response(400, json={"error": "expired_token"})
        )
        async with httpx.AsyncClient() as http:
            with pytest.raises(LoginError) as exc:
                await device_login(http, TEST_URL, "cid", "api", echo=lambda _s: None)
    assert exc.value.code == "expired_token"
    assert route.call_count == 1  # stopped, no more polling


async def test_device_access_denied_stops(no_sleep):
    with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
        router.post("/oauth/authorize_device").mock(return_value=_device_init())
        router.post("/oauth/token").mock(
            return_value=httpx.Response(400, json={"error": "access_denied"})
        )
        async with httpx.AsyncClient() as http:
            with pytest.raises(LoginError) as exc:
                await device_login(http, TEST_URL, "cid", "api", echo=lambda _s: None)
    assert exc.value.code == "access_denied"


async def test_device_404_means_old_gitlab(no_sleep):
    with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
        router.post("/oauth/authorize_device").mock(return_value=httpx.Response(404))
        async with httpx.AsyncClient() as http:
            with pytest.raises(LoginError) as exc:
                await device_login(http, TEST_URL, "cid", "api", echo=lambda _s: None)
    assert exc.value.code == "device_404"
    msg = local_auth_cli_message(exc.value.code)
    assert "17.9" in msg
    assert "--web" in msg


async def test_device_invalid_scope(no_sleep):
    with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
        router.post("/oauth/authorize_device").mock(
            return_value=httpx.Response(400, json={"error": "invalid_scope"})
        )
        async with httpx.AsyncClient() as http:
            with pytest.raises(LoginError) as exc:
                await device_login(http, TEST_URL, "cid", "api", echo=lambda _s: None)
    assert exc.value.code == "invalid_scope"


def local_auth_cli_message(code: str) -> str:
    from mcp_gitlab import _login_error_message

    return _login_error_message(code, TEST_URL, "api")


# ── Web flow ──────────────────────────────────────────────────────


def _fake_browser(*, wrong_state=False, error=None):
    captured: dict[str, str] = {}

    def _open(url: str) -> None:
        query = parse_qs(urlparse(url).query)
        redirect = query["redirect_uri"][0]
        assert redirect.startswith("http://127.0.0.1:")
        assert query["code_challenge_method"][0] == "S256"
        captured["challenge"] = query["code_challenge"][0]
        state = "bogus" if wrong_state else query["state"][0]
        if error:
            callback = f"{redirect}?error={error}&state={state}"
        else:
            callback = f"{redirect}?code=the-code&state={state}"

        def hit() -> None:
            # A 4xx reply (state mismatch) is expected; we only need the request sent.
            with contextlib.suppress(Exception):
                urllib.request.urlopen(callback, timeout=5)  # noqa: S310

        thread = threading.Thread(target=hit)
        thread.start()
        _open.thread = thread

    _open.captured = captured
    return _open


async def test_web_success_with_fake_browser():
    browser = _fake_browser()
    captured: dict[str, bool] = {}

    def token_route(request):
        body = parse_qs(request.content.decode())
        assert body["grant_type"][0] == "authorization_code"
        assert "client_secret" not in body
        verifier = body["code_verifier"][0]
        recomputed = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        captured["match"] = recomputed == browser.captured["challenge"]
        return _token_ok()

    with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
        router.post("/oauth/token").mock(side_effect=token_route)
        async with httpx.AsyncClient() as http:
            token, redirect = await web_login(
                http, TEST_URL, "cid", "api", echo=lambda _s: None, open_browser=browser
            )
    assert token["access_token"] == "at-1"
    assert redirect.startswith("http://127.0.0.1:")
    assert captured["match"] is True


async def test_web_state_mismatch_rejected():
    browser = _fake_browser(wrong_state=True)
    with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
        token_route = router.post("/oauth/token").mock(return_value=_token_ok())
        async with httpx.AsyncClient() as http:
            with pytest.raises(LoginError) as exc:
                await web_login(
                    http, TEST_URL, "cid", "api", echo=lambda _s: None, open_browser=browser
                )
    assert exc.value.code == "state"
    assert token_route.call_count == 0


async def test_web_error_param():
    browser = _fake_browser(error="access_denied")
    with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
        router.post("/oauth/token").mock(return_value=_token_ok())
        async with httpx.AsyncClient() as http:
            with pytest.raises(LoginError) as exc:
                await web_login(
                    http, TEST_URL, "cid", "api", echo=lambda _s: None, open_browser=browser
                )
    assert exc.value.code == "access_denied"


async def test_web_timeout(monkeypatch):
    servers: list = []
    original = local_auth.HTTPServer

    class Recorded(original):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            servers.append(self)

    monkeypatch.setattr(local_auth, "HTTPServer", Recorded)

    with respx.mock(base_url=TEST_URL, assert_all_called=False):
        async with httpx.AsyncClient() as http:
            with pytest.raises(LoginError) as exc:
                await web_login(
                    http,
                    TEST_URL,
                    "cid",
                    "api",
                    echo=lambda _s: None,
                    open_browser=lambda _u: None,
                    timeout=0.2,
                )
    assert exc.value.code == "timeout"
    assert servers[0].socket.fileno() == -1  # socket closed in finally


# ── Store ─────────────────────────────────────────────────────────

ENTRY = {
    "client_id": "cid",
    "access_token": "at",
    "refresh_token": "rt",
    "expires_at": 9999999999,
    "scopes": ["api"],
}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_save_sets_mode_0600_and_dir_0700(store):
    store.save(TEST_URL, dict(ENTRY))
    assert oct(store.path.stat().st_mode & 0o777) == "0o600"
    assert oct(store.path.parent.stat().st_mode & 0o777) == "0o700"


def test_save_is_atomic_no_temp_left(store):
    store.save(TEST_URL, dict(ENTRY))
    names = sorted(p.name for p in store.path.parent.iterdir())
    assert names == ["credentials.json", "credentials.lock"]


def test_host_key_normalises():
    assert local_auth.host_key("https://GitLab.com/") == "https://gitlab.com"
    assert local_auth.host_key("https://host/gitlab/") == "https://host/gitlab"


def test_delete_last_host_removes_file(store):
    store.save(TEST_URL, dict(ENTRY))
    assert store.path.exists()
    store.delete(TEST_URL)
    assert not store.path.exists()


def test_delete_keeps_other_hosts(store):
    store.save(TEST_URL, dict(ENTRY))
    store.save("https://other.example.com", dict(ENTRY))
    store.delete(TEST_URL)
    assert store.path.exists()
    assert store.load(TEST_URL) is None
    assert store.load("https://other.example.com") is not None


def test_load_returns_none_without_file(store):
    assert store.load(TEST_URL) is None


# ── Refresh and locking ───────────────────────────────────────────


async def test_bearer_refreshes_before_margin(store):
    store.save(TEST_URL, {**ENTRY, "expires_at": int(time.time()) + 100})
    with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
        router.post("/oauth/token").mock(
            return_value=_token_ok(access_token="at-2", refresh_token="rt-2")
        )
        creds = store.load(TEST_URL)
        token = await creds.bearer()
        await creds.aclose()
    assert token == "at-2"
    assert store.all()[TEST_URL]["refresh_token"] == "rt-2"


async def test_refresh_rotates_both_tokens(store):
    store.save(TEST_URL, {**ENTRY, "expires_at": 0})
    with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
        router.post("/oauth/token").mock(
            return_value=_token_ok(access_token="new-at", refresh_token="new-rt")
        )
        creds = store.load(TEST_URL)
        await creds.refresh()
        await creds.aclose()
    assert creds.access_token == "new-at"
    assert creds.refresh_token == "new-rt"
    saved = store.all()[TEST_URL]
    assert saved["access_token"] == "new-at"
    assert saved["refresh_token"] == "new-rt"


async def test_refresh_failure_is_auth_error(store):
    store.save(TEST_URL, {**ENTRY, "expires_at": 0})
    with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
        router.post("/oauth/token").mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant"})
        )
        creds = store.load(TEST_URL)
        with pytest.raises(GitLabAuthError) as exc:
            await creds.refresh()
        await creds.aclose()
    assert exc.value.status_code == 401
    assert "invalid_grant" in exc.value.body


async def test_concurrent_refresh_hits_gitlab_once(store):
    import asyncio

    store.save(TEST_URL, {**ENTRY, "expires_at": 0})
    with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
        route = router.post("/oauth/token").mock(
            return_value=_token_ok(access_token="shared-at", refresh_token="shared-rt")
        )
        a = store.load(TEST_URL)
        b = store.load(TEST_URL)
        await asyncio.gather(a.bearer(), b.bearer())
        await a.aclose()
        await b.aclose()
    assert route.call_count == 1
    assert a.access_token == b.access_token == "shared-at"


def _hold_lock(path: str, seconds: float, ready: str) -> None:
    store = CredentialStore(Path(path))
    with store.locked():
        Path(ready).write_text("held")
        time.sleep(seconds)


@pytest.mark.skipif(sys.platform == "win32", reason="msvcrt lock semantics differ")
def test_lock_blocks_second_process(store, tmp_path):
    ready = tmp_path / "ready"
    ctx = multiprocessing.get_context("fork")
    child = ctx.Process(target=_hold_lock, args=(str(store.path), 0.5, str(ready)))
    child.start()
    try:
        while not ready.exists():
            time.sleep(0.01)
        start = time.monotonic()
        with store.locked():
            waited = time.monotonic() - start
    finally:
        child.join()
    assert waited >= 0.4


# ── build_entry ───────────────────────────────────────────────────


def test_build_entry_uses_response_scope():
    token = {"access_token": "at", "refresh_token": "rt", "expires_in": 7200, "scope": "read_api"}
    entry = build_entry("cid", token, "api")
    assert entry["scopes"] == ["read_api"]  # recorded downgrade, not the request


def test_build_entry_falls_back_to_requested_scopes():
    token = {"access_token": "at", "expires_in": 7200}
    entry = build_entry("cid", token, "api", "http://127.0.0.1:5/callback")
    assert entry["scopes"] == ["api"]
    assert entry["redirect_uri"] == "http://127.0.0.1:5/callback"


# ── Edge paths ────────────────────────────────────────────────────


def test_json_handles_non_json():
    assert local_auth._json(httpx.Response(400, text="not json")) == {}
    assert local_auth._json(httpx.Response(200, json=[1, 2])) == {}  # non-dict body


def test_read_ignores_malformed_file(store):
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("[]")  # a list, not {version, hosts}
    assert store.all() == {}


def test_atomic_write_cleans_up_on_error(store, monkeypatch):
    def boom(*_a, **_k):
        msg = "boom"
        raise RuntimeError(msg)

    monkeypatch.setattr(local_auth.json, "dumps", boom)
    with pytest.raises(RuntimeError):
        store.save(TEST_URL, dict(ENTRY))
    leftovers = [p.name for p in store.path.parent.iterdir() if p.name.startswith(".credentials.")]
    assert leftovers == []  # temp file unlinked in finally


async def test_refresh_echoes_redirect_uri(store):
    store.save(TEST_URL, {**ENTRY, "expires_at": 0, "redirect_uri": "http://127.0.0.1:9/callback"})
    captured: dict[str, dict] = {}

    def route(request):
        captured["body"] = parse_qs(request.content.decode())
        return _token_ok()

    with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
        router.post("/oauth/token").mock(side_effect=route)
        creds = store.load(TEST_URL)
        await creds.refresh()
        await creds.aclose()
    assert captured["body"]["redirect_uri"][0] == "http://127.0.0.1:9/callback"
    assert store.all()[TEST_URL]["redirect_uri"] == "http://127.0.0.1:9/callback"


async def test_device_deadline_expired(no_sleep):
    with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
        router.post("/oauth/authorize_device").mock(return_value=_device_init(expires_in=0))
        route = router.post("/oauth/token").mock(return_value=_token_ok())
        async with httpx.AsyncClient() as http:
            with pytest.raises(LoginError) as exc:
                await device_login(http, TEST_URL, "cid", "api", echo=lambda _s: None)
    assert exc.value.code == "expired_token"
    assert route.call_count == 0  # deadline hit before the first poll


async def test_web_token_exchange_fails():
    browser = _fake_browser()
    with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
        router.post("/oauth/token").mock(
            return_value=httpx.Response(400, json={"error": "invalid_client"})
        )
        async with httpx.AsyncClient() as http:
            with pytest.raises(LoginError) as exc:
                await web_login(
                    http, TEST_URL, "cid", "api", echo=lambda _s: None, open_browser=browser
                )
    assert exc.value.code == "invalid_client"


async def test_web_ignores_non_callback_request():
    def browser(url: str) -> None:
        redirect = parse_qs(urlparse(url).query)["redirect_uri"][0]
        base = redirect.rsplit("/callback", 1)[0]

        def hit() -> None:
            # A 404 is expected; we only need a non-/callback request delivered.
            with contextlib.suppress(Exception):
                urllib.request.urlopen(f"{base}/favicon.ico", timeout=5)  # noqa: S310

        threading.Thread(target=hit).start()

    with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
        router.post("/oauth/token").mock(return_value=_token_ok())
        async with httpx.AsyncClient() as http:
            with pytest.raises(LoginError) as exc:
                await web_login(
                    http,
                    TEST_URL,
                    "cid",
                    "api",
                    echo=lambda _s: None,
                    open_browser=browser,
                    timeout=2,
                )
    assert exc.value.code == "timeout"
