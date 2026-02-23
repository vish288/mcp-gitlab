"""Tool-level tests — call @mcp.tool functions via FastMCP Client with mocked API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
import respx
from fastmcp import Client, FastMCP
from httpx import Response

from mcp_gitlab.client import GitLabClient
from mcp_gitlab.config import GitLabConfig

TEST_URL = "https://gitlab.example.com"
TEST_TOKEN = "test-token"


def _make_mcp(*, read_only: bool = False) -> FastMCP:
    """Build a FastMCP server with mocked lifespan."""
    config = GitLabConfig(url=TEST_URL, token=TEST_TOKEN, read_only=read_only)
    client = GitLabClient(config)

    @asynccontextmanager
    async def mock_lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        try:
            yield {"client": client, "config": config}
        finally:
            await client.close()

    # Import the real mcp instance and swap lifespan
    from mcp_gitlab.servers.gitlab import mcp

    original_lifespan = mcp._lifespan
    mcp._lifespan = mock_lifespan
    return mcp, original_lifespan


@pytest.fixture
async def tool_client():
    """FastMCP test client with mocked lifespan and respx-mocked HTTP."""
    mcp, original_lifespan = _make_mcp()
    with respx.mock(base_url=f"{TEST_URL}/api/v4") as router:
        async with Client(mcp) as client:
            yield client, router
    mcp._lifespan = original_lifespan


@pytest.fixture
async def readonly_client():
    """FastMCP test client in read-only mode."""
    mcp, original_lifespan = _make_mcp(read_only=True)
    with respx.mock(base_url=f"{TEST_URL}/api/v4") as router:
        async with Client(mcp) as client:
            yield client, router
    mcp._lifespan = original_lifespan


def _parse(result: Any) -> dict | list:
    """Extract JSON from a tool call result."""
    # FastMCP Client.call_tool returns a CallToolResult with .content list
    if hasattr(result, "content"):
        for item in result.content:
            if hasattr(item, "text"):
                return json.loads(item.text)
    # Fallback: if it's iterable (list of content blocks)
    if hasattr(result, "__iter__") and not isinstance(result, (str, dict)):
        for item in result:
            if hasattr(item, "text"):
                return json.loads(item.text)
    return json.loads(str(result))


# ═══════════════════════════════════════════════════════
# Projects
# ═══════════════════════════════════════════════════════


class TestGetProject:
    async def test_happy_path(self, tool_client):
        client, router = tool_client
        router.get("/projects/123").mock(
            return_value=Response(200, json={"id": 123, "name": "test-project"})
        )
        result = await client.call_tool("gitlab_get_project", {"project_id": "123"})
        parsed = _parse(result)
        assert parsed["id"] == 123
        assert parsed["name"] == "test-project"

    async def test_not_found(self, tool_client):
        client, router = tool_client
        router.get("/projects/nonexistent").mock(
            return_value=Response(404, json={"message": "404 Project Not Found"})
        )
        result = await client.call_tool("gitlab_get_project", {"project_id": "nonexistent"})
        parsed = _parse(result)
        assert "error" in parsed
        assert "hint" in parsed
        assert "Verify" in parsed["hint"]

    async def test_auth_error(self, tool_client):
        client, router = tool_client
        router.get("/projects/123").mock(
            return_value=Response(401, json={"message": "401 Unauthorized"})
        )
        result = await client.call_tool("gitlab_get_project", {"project_id": "123"})
        parsed = _parse(result)
        assert "error" in parsed
        assert "hint" in parsed
        assert "GITLAB_TOKEN" in parsed["hint"]


# ═══════════════════════════════════════════════════════
# Write operations in read-only mode
# ═══════════════════════════════════════════════════════


class TestReadOnlyMode:
    async def test_create_project_blocked(self, readonly_client):
        client, router = readonly_client
        result = await client.call_tool("gitlab_create_project", {"name": "test"})
        parsed = _parse(result)
        assert "error" in parsed
        assert "hint" in parsed
        assert "read-only" in parsed["hint"].lower()

    async def test_create_branch_blocked(self, readonly_client):
        client, router = readonly_client
        result = await client.call_tool(
            "gitlab_create_branch",
            {"project_id": "123", "branch_name": "feat/test", "ref": "main"},
        )
        parsed = _parse(result)
        assert "error" in parsed
        assert "read-only" in parsed["hint"].lower()

    async def test_read_still_works(self, readonly_client):
        client, router = readonly_client
        router.get("/projects/123").mock(
            return_value=Response(200, json={"id": 123, "name": "test"})
        )
        result = await client.call_tool("gitlab_get_project", {"project_id": "123"})
        parsed = _parse(result)
        assert parsed["id"] == 123


# ═══════════════════════════════════════════════════════
# Branches
# ═══════════════════════════════════════════════════════


class TestBranches:
    async def test_list_branches(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/repository/branches").mock(
            return_value=Response(200, json=[{"name": "main"}, {"name": "develop"}])
        )
        result = await client.call_tool("gitlab_list_branches", {"project_id": "123"})
        parsed = _parse(result)
        assert len(parsed) == 2
        assert parsed[0]["name"] == "main"

    async def test_create_branch(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/repository/branches").mock(
            return_value=Response(201, json={"name": "feat/new", "commit": {"id": "abc"}})
        )
        result = await client.call_tool(
            "gitlab_create_branch",
            {"project_id": "123", "branch_name": "feat/new", "ref": "main"},
        )
        parsed = _parse(result)
        assert parsed["name"] == "feat/new"


# ═══════════════════════════════════════════════════════
# Merge Requests
# ═══════════════════════════════════════════════════════


class TestMergeRequests:
    async def test_list_mrs(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/merge_requests").mock(
            return_value=Response(200, json=[{"iid": 1, "title": "Test MR", "state": "opened"}])
        )
        result = await client.call_tool("gitlab_list_mrs", {"project_id": "123"})
        parsed = _parse(result)
        assert len(parsed) == 1
        assert parsed[0]["iid"] == 1

    async def test_get_mr(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/merge_requests/1").mock(
            return_value=Response(
                200,
                json={
                    "iid": 1,
                    "title": "Test MR",
                    "state": "opened",
                    "source_branch": "feat/test",
                    "target_branch": "main",
                },
            )
        )
        result = await client.call_tool("gitlab_get_mr", {"project_id": "123", "mr_iid": 1})
        parsed = _parse(result)
        assert parsed["iid"] == 1
        assert parsed["source_branch"] == "feat/test"

    async def test_create_mr(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/merge_requests").mock(
            return_value=Response(201, json={"iid": 5, "title": "New MR", "state": "opened"})
        )
        result = await client.call_tool(
            "gitlab_create_mr",
            {
                "project_id": "123",
                "source_branch": "feat/test",
                "target_branch": "main",
                "title": "New MR",
            },
        )
        parsed = _parse(result)
        assert parsed["iid"] == 5


# ═══════════════════════════════════════════════════════
# Pipelines
# ═══════════════════════════════════════════════════════


class TestPipelines:
    async def test_list_pipelines(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/pipelines").mock(
            return_value=Response(
                200,
                json=[{"id": 100, "status": "success", "ref": "main"}],
            )
        )
        result = await client.call_tool("gitlab_list_pipelines", {"project_id": "123"})
        parsed = _parse(result)
        assert len(parsed) == 1
        assert parsed[0]["status"] == "success"

    async def test_get_pipeline_with_jobs(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/pipelines/100").mock(
            return_value=Response(200, json={"id": 100, "status": "success"})
        )
        router.get("/projects/123/pipelines/100/jobs").mock(
            return_value=Response(200, json=[{"id": 1, "name": "build", "status": "success"}])
        )
        result = await client.call_tool(
            "gitlab_get_pipeline",
            {"project_id": "123", "pipeline_id": 100, "include_jobs": True},
        )
        parsed = _parse(result)
        assert parsed["id"] == 100
        assert len(parsed["jobs"]) == 1


# ═══════════════════════════════════════════════════════
# Issues
# ═══════════════════════════════════════════════════════


class TestIssues:
    async def test_create_issue(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/issues").mock(
            return_value=Response(201, json={"iid": 10, "title": "Bug report"})
        )
        result = await client.call_tool(
            "gitlab_create_issue", {"project_id": "123", "title": "Bug report"}
        )
        parsed = _parse(result)
        assert parsed["iid"] == 10

    async def test_list_issues(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/issues").mock(
            return_value=Response(200, json=[{"iid": 1, "title": "Test", "state": "opened"}])
        )
        result = await client.call_tool("gitlab_list_issues", {"project_id": "123"})
        parsed = _parse(result)
        assert len(parsed) == 1


# ═══════════════════════════════════════════════════════
# Error message enrichment
# ═══════════════════════════════════════════════════════


class TestErrorHints:
    async def test_409_conflict_hint(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/repository/branches").mock(
            return_value=Response(409, json={"message": "Branch already exists"})
        )
        result = await client.call_tool(
            "gitlab_create_branch",
            {"project_id": "123", "branch_name": "main", "ref": "main"},
        )
        parsed = _parse(result)
        assert parsed["status_code"] == 409
        assert "hint" in parsed
        assert "Conflict" in parsed["hint"]

    async def test_422_validation_hint(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/merge_requests").mock(
            return_value=Response(422, json={"message": "Validation failed"})
        )
        result = await client.call_tool(
            "gitlab_create_mr",
            {
                "project_id": "123",
                "source_branch": "feat/x",
                "target_branch": "main",
                "title": "Test",
            },
        )
        parsed = _parse(result)
        assert parsed["status_code"] == 422
        assert "hint" in parsed
        assert "Validation" in parsed["hint"]

    async def test_429_rate_limit_hint(self, tool_client):
        client, router = tool_client
        router.get("/projects/123").mock(return_value=Response(429, text="Rate limit exceeded"))
        result = await client.call_tool("gitlab_get_project", {"project_id": "123"})
        parsed = _parse(result)
        assert parsed["status_code"] == 429
        assert "hint" in parsed
        assert "Rate" in parsed["hint"]


# ═══════════════════════════════════════════════════════
# Variables (masked values)
# ═══════════════════════════════════════════════════════


class TestVariables:
    async def test_list_variables_masks_values(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/variables").mock(
            return_value=Response(
                200,
                json=[
                    {"key": "SECRET", "value": "s3cret!", "masked": True},
                    {"key": "PUBLIC", "value": "hello", "masked": False},
                ],
            )
        )
        result = await client.call_tool("gitlab_list_variables", {"project_id": "123"})
        parsed = _parse(result)
        assert parsed[0]["value"] == "***MASKED***"
        assert parsed[1]["value"] == "hello"
