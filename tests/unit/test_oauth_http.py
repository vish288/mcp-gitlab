"""In-process HTTP tests driving the real OAuth resource-server middleware.

These touch a few OAuthProxy private attributes (the JWT issuer and the two
token stores) to mint a valid FastMCP JWT and seed its upstream-token mapping
without a live GitLab authorization flow. That coupling is accepted for tests.

Each test drives the server via ``build_oauth_app`` as an ``async with`` inside
its own coroutine: FastMCP's streamable-http lifespan opens an anyio task group
that must be entered and exited in the same task, which an async-generator
fixture (finalized by pytest-asyncio in a separate task) violates.
"""

from __future__ import annotations

import json
import time
import uuid

import httpx
from fastmcp.server.auth.jwt_issuer import JWTIssuer
from fastmcp.server.auth.oauth_proxy.models import JTIMapping, UpstreamTokenSet

from mcp_gitlab.servers.gitlab import mcp
from tests.conftest import OAUTH_BASE, build_oauth_app

RESOURCE = f"{OAUTH_BASE}/mcp"
PRM_URL = f"{OAUTH_BASE}/.well-known/oauth-protected-resource/mcp"
_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


async def _issue(provider, scopes, *, upstream="glo-upstream", aud=None) -> str:
    """Mint a FastMCP JWT and seed its upstream-token mapping; return the JWT."""
    if provider._jwt_issuer is None:
        provider.set_mcp_path("/mcp")
    jti, tid, now = uuid.uuid4().hex, uuid.uuid4().hex, time.time()
    if aud is None:
        issuer = provider.jwt_issuer
    else:
        issuer = JWTIssuer(
            issuer=str(provider.issuer_url), audience=aud, signing_key=provider._jwt_signing_key
        )
    token = issuer.issue_access_token(client_id="c", scopes=scopes, jti=jti, expires_in=600)
    await provider._upstream_token_store.put(
        key=tid,
        value=UpstreamTokenSet(
            upstream_token_id=tid,
            access_token=upstream,
            refresh_token=None,
            refresh_token_expires_at=None,
            expires_at=now + 7200,
            token_type="Bearer",  # noqa: S106
            scope=" ".join(scopes),
            client_id="c",
            created_at=now,
        ),
    )
    await provider._jti_mapping_store.put(
        key=jti, value=JTIMapping(jti=jti, upstream_token_id=tid, created_at=now)
    )
    return token


async def _rpc(http, token, method, params):
    headers = dict(_HEADERS)
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    return await http.post("/mcp", headers=headers, json=body)


def _tool_text(resp: httpx.Response) -> dict:
    """Extract a tools/call result payload from an SSE or JSON response."""
    text = resp.text
    for line in text.splitlines():
        if line.startswith("data:"):
            text = line[len("data:") :].strip()
            break
    obj = json.loads(text)
    return json.loads(obj["result"]["content"][0]["text"])


def _mock_token_info(router, scope):
    router.get("/oauth/token/info").mock(
        return_value=httpx.Response(
            200,
            json={
                "resource_owner_id": 7,
                "scope": scope,
                "expires_in": 7200,
                "created_at": time.time(),
                "application": {"uid": "app"},
            },
        )
    )


async def test_prm_document(tmp_path):
    async with build_oauth_app(tmp_path) as (http, _router, _provider):
        r = await http.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200
    body = r.json()
    assert body["resource"] == RESOURCE
    assert [s.rstrip("/") for s in body["authorization_servers"]] == [OAUTH_BASE]
    assert body["scopes_supported"] == ["api"]
    assert "offline_access" not in body["scopes_supported"]


async def test_as_metadata(tmp_path):
    async with build_oauth_app(tmp_path) as (http, _router, _provider):
        body = (await http.get("/.well-known/oauth-authorization-server")).json()
    for key in ("issuer", "authorization_endpoint", "token_endpoint", "registration_endpoint"):
        assert key in body
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert body["authorization_response_iss_parameter_supported"] is True
    assert body["client_id_metadata_document_supported"] is True


async def test_401_missing_token(tmp_path):
    async with build_oauth_app(tmp_path) as (http, router, _provider):
        r = await _rpc(http, None, "tools/list", {})
        assert not router.calls
    assert r.status_code == 401
    www = r.headers["www-authenticate"]
    assert www.startswith("Bearer")
    assert 'scope="api"' in www
    assert f'resource_metadata="{PRM_URL}"' in www
    assert "error=" not in www


async def test_401_bad_jwt(tmp_path):
    async with build_oauth_app(tmp_path) as (http, router, _provider):
        r = await _rpc(http, "nope-not-a-jwt", "tools/list", {})
        assert not router.calls
    assert r.status_code == 401
    assert 'error="invalid_token"' in r.headers["www-authenticate"]


async def test_401_raw_gitlab_pat_rejected(tmp_path):
    """R5: a raw GitLab PAT is not our JWT; it is rejected and GitLab is never called."""
    async with build_oauth_app(tmp_path) as (http, router, _provider):
        r = await _rpc(http, "glpat-xxxxxxxxxxxxxxxxxxxx", "tools/list", {})  # noqa: S106
        assert not router.calls  # token-info was never hit
    assert r.status_code == 401
    assert 'error="invalid_token"' in r.headers["www-authenticate"]


async def test_401_wrong_audience(tmp_path):
    """R4: a JWT signed with the server key but a foreign ``aud`` is rejected."""
    async with build_oauth_app(tmp_path) as (http, router, provider):
        token = await _issue(provider, ["api"], aud="http://evil/mcp")
        r = await _rpc(http, token, "tools/list", {})
        assert not router.calls
    assert r.status_code == 401
    assert 'error="invalid_token"' in r.headers["www-authenticate"]


async def test_401_upstream_revoked(tmp_path):
    """R3/R17: a valid JWT whose upstream token is revoked (token-info 401) → 401, not 500."""
    async with build_oauth_app(tmp_path) as (http, router, provider):
        router.get("/oauth/token/info").mock(return_value=httpx.Response(401))
        token = await _issue(provider, ["api"])
        r = await _rpc(http, token, "tools/list", {})
    assert r.status_code == 401
    assert 'error="invalid_token"' in r.headers["www-authenticate"]


async def test_403_insufficient_scope(tmp_path):
    """R8: a valid but under-scoped token (read_api, server needs api) → 403."""
    async with build_oauth_app(tmp_path) as (http, router, provider):
        _mock_token_info(router, ["read_api"])
        token = await _issue(provider, ["read_api"])
        r = await _rpc(http, token, "tools/list", {})
    assert r.status_code == 403
    www = r.headers["www-authenticate"]
    assert 'error="insufficient_scope"' in www
    assert 'scope="api"' in www
    assert "resource_metadata=" in www


async def test_tool_call_uses_upstream_bearer(tmp_path):
    """R6: GitLab receives the upstream Bearer token, never the client's JWT or a PAT."""
    async with build_oauth_app(tmp_path) as (http, router, provider):
        _mock_token_info(router, ["api"])
        proj = router.get("/api/v4/projects/1").mock(
            return_value=httpx.Response(200, json={"id": 1, "name": "demo"})
        )
        token = await _issue(provider, ["api"], upstream="glo-upstream")
        r = await _rpc(
            http,
            token,
            "tools/call",
            {"name": "gitlab_get_project", "arguments": {"project_id": "1"}},
        )
        assert r.status_code == 200
        assert _tool_text(r)["id"] == 1
        assert proj.called
        req = proj.calls.last.request
        assert req.headers["authorization"] == "Bearer glo-upstream"
        assert "private-token" not in req.headers
        # The client JWT never appears in any upstream request.
        for call in router.calls:
            assert token not in call.request.headers.get("authorization", "")


async def test_write_blocked_without_api_scope(tmp_path):
    """R18: a read_api-only deployment blocks writes with an actionable hint, no POST sent."""
    async with build_oauth_app(tmp_path, scopes="read_api") as (http, router, provider):
        _mock_token_info(router, ["read_api"])
        post = router.post("/api/v4/projects").mock(return_value=httpx.Response(201, json={}))
        token = await _issue(provider, ["read_api"])
        r = await _rpc(
            http,
            token,
            "tools/call",
            {"name": "gitlab_create_project", "arguments": {"name": "x"}},
        )
        assert r.status_code == 200
        payload = _tool_text(r)
        assert "api" in payload["error"].lower()
        assert "scope" in payload["hint"].lower()
        assert not post.called


async def test_stdio_memory_client_unaffected(tool_client):
    """Regression guard: the module-level ``mcp`` has no auth outside oauth mode."""
    client, router = tool_client
    assert mcp.auth is None
    router.get("/projects/1").mock(return_value=httpx.Response(200, json={"id": 1, "name": "d"}))
    result = await client.call_tool("gitlab_get_project", {"project_id": "1"})
    assert json.loads(result.content[0].text)["id"] == 1
