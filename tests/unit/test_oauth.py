"""Unit tests for the GitLab OAuth provider: scope hierarchy, verifier, proxy wiring."""

from __future__ import annotations

import time

import httpx
import pytest
import respx

from mcp_gitlab.config import GitLabConfig
from mcp_gitlab.oauth import GitLabProvider, GitLabTokenVerifier, _expand_scopes
from tests.conftest import TEST_URL

INFO_URL = f"{TEST_URL}/oauth/token/info"


def _info(scope: list[str], *, created: float | None = None, ttl: int | None = 7200) -> dict:
    return {
        "resource_owner_id": 7,
        "scope": scope,
        "expires_in": ttl,
        "created_at": created if created is not None else time.time(),
        "application": {"uid": "app"},
    }


def _verifier(required: list[str] | None = None) -> GitLabTokenVerifier:
    return GitLabTokenVerifier(gitlab_url=TEST_URL, required_scopes=required or ["api"])


def test_scope_expansion():
    """R7: a broader scope satisfies the narrower ones; unknown scopes pass through."""
    assert _expand_scopes(["api"]) == ["api", "read_api", "read_user"]
    assert _expand_scopes(["read_api"]) == ["read_api", "read_user"]
    assert _expand_scopes(["read_user"]) == ["read_user"]
    assert _expand_scopes(["sudo"]) == ["sudo"]


async def test_verifier_ok():
    created = 1_700_000_000.0
    with respx.mock(base_url=TEST_URL) as router:
        router.get("/oauth/token/info").mock(
            return_value=httpx.Response(200, json=_info(["api"], created=created))
        )
        tok = await _verifier().verify_token("glo-x")
    assert tok is not None
    assert tok.token == "glo-x"  # the upstream token tools will send
    assert tok.subject == "7"
    assert tok.scopes == ["api", "read_api", "read_user"]
    assert tok.expires_at == int(created + 7200)
    assert tok.client_id == "app"


async def test_verifier_non_200_returns_none():
    """R17: a revoked/expired token (non-200 from token-info) yields None."""
    with respx.mock(base_url=TEST_URL) as router:
        router.get("/oauth/token/info").mock(return_value=httpx.Response(401))
        assert await _verifier().verify_token("dead") is None


async def test_verifier_does_not_enforce_scope():
    """DEVIATION from the spec's ``test_verifier_missing_required_scope_returns_none``.

    The spec had the verifier return None when the token lacked a required
    scope, but that makes the R8 403 ``insufficient_scope`` path unreachable:
    ``load_access_token`` would return None and the middleware would answer 401
    ``invalid_token`` instead (see ``mcp/server/auth/middleware/bearer_auth.py``
    which only 403s when a token *is* returned but misses a scope). Scope
    enforcement is therefore the resource server's job, not the verifier's; the
    verifier reports the token's (expanded) scopes and the middleware decides.
    Covered end-to-end by ``test_oauth_http.py::test_403_insufficient_scope``.
    """
    with respx.mock(base_url=TEST_URL) as router:
        router.get("/oauth/token/info").mock(
            return_value=httpx.Response(200, json=_info(["read_api"]))
        )
        tok = await _verifier(["api"]).verify_token("glo-x")
    assert tok is not None
    assert tok.scopes == ["read_api", "read_user"]
    assert "api" not in tok.scopes


async def test_verifier_network_error_returns_none():
    with respx.mock(base_url=TEST_URL) as router:
        router.get("/oauth/token/info").mock(side_effect=httpx.ConnectError("boom"))
        assert await _verifier().verify_token("glo-x") is None


async def test_verifier_sends_bearer():
    with respx.mock(base_url=TEST_URL) as router:
        route = router.get("/oauth/token/info").mock(
            return_value=httpx.Response(200, json=_info(["api"]))
        )
        await _verifier().verify_token("glo-x")
    req = route.calls.last.request
    assert req.headers["Authorization"] == "Bearer glo-x"
    assert str(req.url) == INFO_URL


def test_provider_endpoints():
    cfg = GitLabConfig(
        url=TEST_URL,
        auth="oauth",
        oauth_client_id="app",
        oauth_client_secret="s3cret-s3cret-s3cret",  # noqa: S106
        oauth_base_url="http://localhost",
        oauth_scopes="api",
    )
    provider = GitLabProvider(cfg)
    assert provider._upstream_authorization_endpoint == f"{TEST_URL}/oauth/authorize"
    assert provider._upstream_token_endpoint == f"{TEST_URL}/oauth/token"
    assert provider._upstream_revocation_endpoint == f"{TEST_URL}/oauth/revoke"
    assert provider._token_validator.required_scopes == ["api"]


def test_get_client_oauth_without_token_raises(monkeypatch):
    """Defensive branch: oauth mode with no access token (can't happen behind
    RequireAuthMiddleware) raises GitLabAuthError rather than proceeding."""
    from mcp_gitlab.exceptions import GitLabAuthError
    from mcp_gitlab.servers import gitlab as g

    cfg = GitLabConfig(
        url=TEST_URL,
        auth="oauth",
        oauth_client_id="app",
        oauth_client_secret="s3cret",  # noqa: S106
        oauth_base_url="http://localhost",
    )

    class _Ctx:
        lifespan_context = {"client": object(), "config": cfg}

    monkeypatch.setattr(g, "get_access_token", lambda: None)
    with pytest.raises(GitLabAuthError):
        g._get_client(_Ctx())


@pytest.mark.parametrize("ttl", [None, 0])
async def test_verifier_no_expiry_when_ttl_missing(ttl):
    with respx.mock(base_url=TEST_URL) as router:
        router.get("/oauth/token/info").mock(
            return_value=httpx.Response(200, json=_info(["api"], ttl=ttl))
        )
        tok = await _verifier().verify_token("glo-x")
    assert tok is not None
    assert tok.expires_at is None
