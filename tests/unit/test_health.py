"""/health liveness route (workbench-backlog#167).

A container or remote (HTTP transport) deployment needs an unauthenticated liveness URL.
FastMCP's auth guards ``/mcp``, not custom routes, so ``GET /health`` answers with the
server name and package version and nothing else — no config, no secrets.
"""

from __future__ import annotations

from importlib.metadata import version

import httpx

from mcp_gitlab.servers.gitlab import mcp


async def test_health_returns_ok_name_and_version():
    transport = httpx.ASGITransport(app=mcp.http_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://health.test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "name": mcp.name, "version": version("mcp-gitlab")}


async def test_health_exposes_no_secrets():
    transport = httpx.ASGITransport(app=mcp.http_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://health.test") as client:
        response = await client.get("/health")
    assert set(response.json()) == {"status", "name", "version"}
