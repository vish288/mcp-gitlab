"""Shared test fixtures for mcp-gitlab."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
import respx
from fastmcp import Client, FastMCP

from mcp_gitlab.client import GitLabClient
from mcp_gitlab.config import GitLabConfig
from mcp_gitlab.oauth import GitLabProvider
from mcp_gitlab.servers.gitlab import mcp

TEST_URL = "https://gitlab.example.com"
TEST_TOKEN = "test-token"
API_BASE = f"{TEST_URL}/api/v4"
# Loopback host: the MCP SDK rejects a non-HTTPS issuer URL unless it is
# localhost/127.0.0.1 (`mcp/server/auth/routes.py::validate_issuer_url`), so
# the spec's literal "http://testserver" cannot be used as the OAuth base.
OAUTH_BASE = "http://localhost"


@pytest.fixture
async def client() -> AsyncIterator[GitLabClient]:
    """A bare GitLabClient for client-level tests, closed after the test."""
    gl = GitLabClient(GitLabConfig(url=TEST_URL, token=TEST_TOKEN))
    yield gl
    await gl.close()


@pytest.fixture
def mock_api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=API_BASE) as router:
        yield router


@asynccontextmanager
async def _tool_client(*, read_only: bool) -> AsyncIterator[tuple[Client, respx.MockRouter]]:
    """The real ``mcp`` server, its lifespan swapped for one that hands tools a
    GitLabClient pointed at a respx-mocked API.

    The original lifespan is restored in ``finally`` so a failure inside
    ``Client(mcp)`` cannot leak the mock into later tests.
    """
    config = GitLabConfig(url=TEST_URL, token=TEST_TOKEN, read_only=read_only)
    gl = GitLabClient(config)

    @asynccontextmanager
    async def mock_lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        try:
            yield {"client": gl, "config": config}
        finally:
            await gl.close()

    original = mcp._lifespan
    mcp._lifespan = mock_lifespan
    try:
        with respx.mock(base_url=API_BASE) as router:
            async with Client(mcp) as mcp_client:
                yield mcp_client, router
    finally:
        mcp._lifespan = original


@pytest.fixture
async def tool_client() -> AsyncIterator[tuple[Client, respx.MockRouter]]:
    """(FastMCP client, respx router) against the server in read-write mode."""
    async with _tool_client(read_only=False) as pair:
        yield pair


@pytest.fixture
async def readonly_client() -> AsyncIterator[tuple[Client, respx.MockRouter]]:
    """(FastMCP client, respx router) against the server in read-only mode."""
    async with _tool_client(read_only=True) as pair:
        yield pair


@asynccontextmanager
async def build_oauth_app(
    tmp_path: Any, *, scopes: str = "api"
) -> AsyncIterator[tuple[httpx.AsyncClient, respx.MockRouter, GitLabProvider]]:
    """The real ``mcp`` server in oauth mode, driven in-process over HTTP.

    Yields ``(http, router, provider)``: an httpx client bound to the ASGI app
    via ``ASGITransport`` (so requests run through the real
    ``RequireAuthMiddleware``), a respx router mocking the GitLab instance
    (``TEST_URL``, covering both ``/oauth/token/info`` and ``/api/v4/...``),
    and the ``GitLabProvider``. ``FASTMCP_HOME`` points at ``tmp_path`` to
    isolate the encrypted token store.

    The lifespan is swapped (as ``_tool_client`` does) so tools get a
    ``GitLabClient`` over the mocked API; ``mcp.auth`` is set before
    ``http_app()`` so the proxy's routes and JWT issuer are built, and both are
    restored afterwards.
    """
    import os

    os.environ["FASTMCP_HOME"] = str(tmp_path)
    config = GitLabConfig(
        url=TEST_URL,
        auth="oauth",
        oauth_client_id="app",
        oauth_client_secret="s3cret-s3cret-s3cret",  # noqa: S106
        oauth_base_url=OAUTH_BASE,
        oauth_scopes=scopes,
    )
    gl = GitLabClient(config)

    @asynccontextmanager
    async def mock_lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        try:
            yield {"client": gl, "config": config}
        finally:
            await gl.close()

    provider = GitLabProvider(config)
    original_lifespan = mcp._lifespan
    original_auth = mcp.auth
    mcp._lifespan = mock_lifespan
    mcp.auth = provider
    app = mcp.http_app(stateless_http=True)
    try:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with (
                httpx.AsyncClient(transport=transport, base_url=OAUTH_BASE) as http,
                respx.mock(base_url=TEST_URL, assert_all_called=False) as router,
            ):
                yield http, router, provider
    finally:
        mcp._lifespan = original_lifespan
        mcp.auth = original_auth
