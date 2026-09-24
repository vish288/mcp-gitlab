"""Shared test fixtures for mcp-gitlab."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
import respx
from fastmcp import Client, FastMCP

from mcp_gitlab.client import GitLabClient
from mcp_gitlab.config import GitLabConfig
from mcp_gitlab.servers.gitlab import mcp

TEST_URL = "https://gitlab.example.com"
TEST_TOKEN = "test-token"
API_BASE = f"{TEST_URL}/api/v4"


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
