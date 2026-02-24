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
        assert parsed["count"] == 2
        assert parsed["items"][0]["name"] == "main"

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
        assert parsed["count"] == 1
        assert parsed["items"][0]["iid"] == 1

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
        assert parsed["count"] == 1
        assert parsed["items"][0]["status"] == "success"

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
        assert parsed["count"] == 1


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
        assert parsed["items"][0]["value"] == "***MASKED***"
        assert parsed["items"][1]["value"] == "hello"

    async def test_create_variable(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/variables").mock(
            return_value=Response(201, json={"key": "NEW_VAR", "value": "val"})
        )
        result = await client.call_tool(
            "gitlab_create_variable",
            {"project_id": "123", "key": "NEW_VAR", "value": "val"},
        )
        parsed = _parse(result)
        assert parsed["key"] == "NEW_VAR"

    async def test_update_variable(self, tool_client):
        client, router = tool_client
        router.put("/projects/123/variables/MY_KEY").mock(
            return_value=Response(200, json={"key": "MY_KEY", "value": "updated"})
        )
        result = await client.call_tool(
            "gitlab_update_variable",
            {"project_id": "123", "key": "MY_KEY", "value": "updated"},
        )
        parsed = _parse(result)
        assert parsed["key"] == "MY_KEY"
        assert parsed["value"] == "updated"

    async def test_delete_variable(self, tool_client):
        client, router = tool_client
        router.delete("/projects/123/variables/MY_KEY").mock(return_value=Response(204))
        result = await client.call_tool(
            "gitlab_delete_variable",
            {"project_id": "123", "key": "MY_KEY"},
        )
        parsed = _parse(result)
        assert parsed["status"] == "deleted"
        assert parsed["key"] == "MY_KEY"

    async def test_list_group_variables_masks_values(self, tool_client):
        client, router = tool_client
        router.get("/groups/10/variables").mock(
            return_value=Response(
                200,
                json=[
                    {"key": "GRP_SECRET", "value": "hidden", "masked": True},
                    {"key": "GRP_PUBLIC", "value": "visible", "masked": False},
                ],
            )
        )
        result = await client.call_tool("gitlab_list_group_variables", {"group_id": "10"})
        parsed = _parse(result)
        assert parsed["count"] == 2
        assert parsed["items"][0]["value"] == "***MASKED***"
        assert parsed["items"][1]["value"] == "visible"

    async def test_create_group_variable(self, tool_client):
        client, router = tool_client
        router.post("/groups/10/variables").mock(
            return_value=Response(201, json={"key": "GRP_VAR", "value": "val"})
        )
        result = await client.call_tool(
            "gitlab_create_group_variable",
            {"group_id": "10", "key": "GRP_VAR", "value": "val"},
        )
        parsed = _parse(result)
        assert parsed["key"] == "GRP_VAR"

    async def test_update_group_variable(self, tool_client):
        client, router = tool_client
        router.put("/groups/10/variables/MY_KEY").mock(
            return_value=Response(200, json={"key": "MY_KEY", "value": "new"})
        )
        result = await client.call_tool(
            "gitlab_update_group_variable",
            {"group_id": "10", "key": "MY_KEY", "value": "new"},
        )
        parsed = _parse(result)
        assert parsed["key"] == "MY_KEY"

    async def test_delete_group_variable(self, tool_client):
        client, router = tool_client
        router.delete("/groups/10/variables/MY_KEY").mock(return_value=Response(204))
        result = await client.call_tool(
            "gitlab_delete_group_variable",
            {"group_id": "10", "key": "MY_KEY"},
        )
        parsed = _parse(result)
        assert parsed["status"] == "deleted"
        assert parsed["key"] == "MY_KEY"


# ═══════════════════════════════════════════════════════
# Projects (write operations)
# ═══════════════════════════════════════════════════════


class TestProjectWrites:
    async def test_create_project(self, tool_client):
        client, router = tool_client
        router.post("/projects").mock(
            return_value=Response(201, json={"id": 456, "name": "new-proj"})
        )
        result = await client.call_tool("gitlab_create_project", {"name": "new-proj"})
        parsed = _parse(result)
        assert parsed["id"] == 456
        assert parsed["name"] == "new-proj"

    async def test_delete_project(self, tool_client):
        client, router = tool_client
        router.delete("/projects/123").mock(return_value=Response(204))
        result = await client.call_tool("gitlab_delete_project", {"project_id": "123"})
        parsed = _parse(result)
        assert parsed["status"] == "deleted"
        assert parsed["project_id"] == "123"

    async def test_update_project_merge_settings(self, tool_client):
        client, router = tool_client
        router.put("/projects/123").mock(
            return_value=Response(
                200,
                json={
                    "id": 123,
                    "merge_method": "ff",
                    "only_allow_merge_if_pipeline_succeeds": True,
                },
            )
        )
        result = await client.call_tool(
            "gitlab_update_project_merge_settings",
            {
                "project_id": "123",
                "merge_method": "ff",
                "only_allow_merge_if_pipeline_succeeds": True,
            },
        )
        parsed = _parse(result)
        assert parsed["merge_method"] == "ff"


# ═══════════════════════════════════════════════════════
# Approvals
# ═══════════════════════════════════════════════════════


class TestApprovals:
    async def test_get_project_approvals(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/approvals").mock(
            return_value=Response(
                200, json={"approvals_before_merge": 2, "reset_approvals_on_push": True}
            )
        )
        result = await client.call_tool("gitlab_get_project_approvals", {"project_id": "123"})
        parsed = _parse(result)
        assert parsed["approvals_before_merge"] == 2

    async def test_update_project_approvals(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/approvals").mock(
            return_value=Response(
                200, json={"approvals_before_merge": 3, "reset_approvals_on_push": False}
            )
        )
        result = await client.call_tool(
            "gitlab_update_project_approvals",
            {"project_id": "123", "approvals_before_merge": 3},
        )
        parsed = _parse(result)
        assert parsed["approvals_before_merge"] == 3

    async def test_list_project_approval_rules(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/approval_rules").mock(
            return_value=Response(
                200,
                json=[
                    {"id": 1, "name": "rule-1", "approvals_required": 1},
                    {"id": 2, "name": "rule-2", "approvals_required": 2},
                ],
            )
        )
        result = await client.call_tool("gitlab_list_project_approval_rules", {"project_id": "123"})
        parsed = _parse(result)
        assert parsed["count"] == 2
        assert parsed["items"][0]["name"] == "rule-1"

    async def test_create_project_approval_rule(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/approval_rules").mock(
            return_value=Response(201, json={"id": 3, "name": "new-rule", "approvals_required": 1})
        )
        result = await client.call_tool(
            "gitlab_create_project_approval_rule",
            {"project_id": "123", "name": "new-rule", "approvals_required": 1},
        )
        parsed = _parse(result)
        assert parsed["id"] == 3
        assert parsed["name"] == "new-rule"

    async def test_update_project_approval_rule(self, tool_client):
        client, router = tool_client
        router.put("/projects/123/approval_rules/1").mock(
            return_value=Response(
                200, json={"id": 1, "name": "updated-rule", "approvals_required": 2}
            )
        )
        result = await client.call_tool(
            "gitlab_update_project_approval_rule",
            {
                "project_id": "123",
                "rule_id": 1,
                "name": "updated-rule",
                "approvals_required": 2,
            },
        )
        parsed = _parse(result)
        assert parsed["name"] == "updated-rule"

    async def test_delete_project_approval_rule(self, tool_client):
        client, router = tool_client
        router.delete("/projects/123/approval_rules/1").mock(return_value=Response(204))
        result = await client.call_tool(
            "gitlab_delete_project_approval_rule",
            {"project_id": "123", "rule_id": 1},
        )
        parsed = _parse(result)
        assert parsed["status"] == "deleted"
        assert parsed["rule_id"] == 1

    async def test_list_mr_approval_rules(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/merge_requests/1/approval_rules").mock(
            return_value=Response(
                200,
                json=[{"id": 10, "name": "mr-rule", "approvals_required": 1}],
            )
        )
        result = await client.call_tool(
            "gitlab_list_mr_approval_rules",
            {"project_id": "123", "mr_iid": 1},
        )
        parsed = _parse(result)
        assert parsed["count"] == 1
        assert parsed["items"][0]["name"] == "mr-rule"

    async def test_create_mr_approval_rule(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/merge_requests/1/approval_rules").mock(
            return_value=Response(
                201, json={"id": 11, "name": "new-mr-rule", "approvals_required": 1}
            )
        )
        result = await client.call_tool(
            "gitlab_create_mr_approval_rule",
            {
                "project_id": "123",
                "mr_iid": 1,
                "name": "new-mr-rule",
                "approvals_required": 1,
            },
        )
        parsed = _parse(result)
        assert parsed["id"] == 11

    async def test_update_mr_approval_rule(self, tool_client):
        client, router = tool_client
        router.put("/projects/123/merge_requests/1/approval_rules/1").mock(
            return_value=Response(
                200, json={"id": 1, "name": "upd-mr-rule", "approvals_required": 3}
            )
        )
        result = await client.call_tool(
            "gitlab_update_mr_approval_rule",
            {
                "project_id": "123",
                "mr_iid": 1,
                "rule_id": 1,
                "name": "upd-mr-rule",
                "approvals_required": 3,
            },
        )
        parsed = _parse(result)
        assert parsed["name"] == "upd-mr-rule"

    async def test_delete_mr_approval_rule(self, tool_client):
        client, router = tool_client
        router.delete("/projects/123/merge_requests/1/approval_rules/1").mock(
            return_value=Response(204)
        )
        result = await client.call_tool(
            "gitlab_delete_mr_approval_rule",
            {"project_id": "123", "mr_iid": 1, "rule_id": 1},
        )
        parsed = _parse(result)
        assert parsed["status"] == "deleted"
        assert parsed["rule_id"] == 1


# ═══════════════════════════════════════════════════════
# Groups
# ═══════════════════════════════════════════════════════


class TestGroups:
    async def test_list_groups(self, tool_client):
        client, router = tool_client
        router.get("/groups").mock(
            return_value=Response(
                200,
                json=[
                    {"id": 10, "name": "group-a"},
                    {"id": 20, "name": "group-b"},
                ],
            )
        )
        result = await client.call_tool("gitlab_list_groups", {})
        parsed = _parse(result)
        assert parsed["count"] == 2
        assert parsed["items"][0]["name"] == "group-a"

    async def test_get_group(self, tool_client):
        client, router = tool_client
        router.get("/groups/10").mock(
            return_value=Response(200, json={"id": 10, "name": "group-a"})
        )
        result = await client.call_tool("gitlab_get_group", {"group_id": "10"})
        parsed = _parse(result)
        assert parsed["id"] == 10
        assert parsed["name"] == "group-a"

    async def test_share_project_with_group(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/share").mock(return_value=Response(204))
        result = await client.call_tool(
            "gitlab_share_project_with_group",
            {"project_id": "123", "group_id": 10, "access_level": "developer"},
        )
        parsed = _parse(result)
        assert parsed["status"] == "shared"
        assert parsed["group_id"] == 10

    async def test_unshare_project_with_group(self, tool_client):
        client, router = tool_client
        router.delete("/projects/123/share/10").mock(return_value=Response(204))
        result = await client.call_tool(
            "gitlab_unshare_project_with_group",
            {"project_id": "123", "group_id": 10},
        )
        parsed = _parse(result)
        assert parsed["status"] == "unshared"

    async def test_share_group_with_group(self, tool_client):
        client, router = tool_client
        router.post("/groups/10/share").mock(return_value=Response(204))
        result = await client.call_tool(
            "gitlab_share_group_with_group",
            {
                "target_group_id": "10",
                "source_group_id": 20,
                "access_level": "maintainer",
            },
        )
        parsed = _parse(result)
        assert parsed["status"] == "shared"

    async def test_unshare_group_with_group(self, tool_client):
        client, router = tool_client
        router.delete("/groups/10/share/20").mock(return_value=Response(204))
        result = await client.call_tool(
            "gitlab_unshare_group_with_group",
            {"target_group_id": "10", "source_group_id": 20},
        )
        parsed = _parse(result)
        assert parsed["status"] == "unshared"


# ═══════════════════════════════════════════════════════
# Branches (delete)
# ═══════════════════════════════════════════════════════


class TestBranchDelete:
    async def test_delete_branch(self, tool_client):
        client, router = tool_client
        router.delete("/projects/123/repository/branches/feat%2Fold").mock(
            return_value=Response(204)
        )
        result = await client.call_tool(
            "gitlab_delete_branch",
            {"project_id": "123", "branch_name": "feat/old"},
        )
        parsed = _parse(result)
        assert parsed["status"] == "deleted"
        assert parsed["branch"] == "feat/old"


# ═══════════════════════════════════════════════════════
# Commits
# ═══════════════════════════════════════════════════════


class TestCommits:
    async def test_list_commits(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/repository/commits").mock(
            return_value=Response(
                200,
                json=[
                    {"id": "abc123", "title": "Initial commit"},
                    {"id": "def456", "title": "Second commit"},
                ],
            )
        )
        result = await client.call_tool("gitlab_list_commits", {"project_id": "123"})
        parsed = _parse(result)
        assert parsed["count"] == 2
        assert parsed["items"][0]["id"] == "abc123"

    async def test_get_commit_without_diff(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/repository/commits/abc123").mock(
            return_value=Response(
                200,
                json={"id": "abc123", "title": "Initial commit", "message": "init"},
            )
        )
        result = await client.call_tool(
            "gitlab_get_commit",
            {"project_id": "123", "sha": "abc123"},
        )
        parsed = _parse(result)
        assert parsed["id"] == "abc123"
        assert "diffs" not in parsed

    async def test_get_commit_with_diff(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/repository/commits/abc123").mock(
            return_value=Response(
                200,
                json={"id": "abc123", "title": "Initial commit"},
            )
        )
        router.get("/projects/123/repository/commits/abc123/diff").mock(
            return_value=Response(
                200,
                json=[{"old_path": "a.py", "new_path": "a.py", "diff": "@@ ..."}],
            )
        )
        result = await client.call_tool(
            "gitlab_get_commit",
            {"project_id": "123", "sha": "abc123", "include_diff": True},
        )
        parsed = _parse(result)
        assert parsed["id"] == "abc123"
        assert len(parsed["diffs"]) == 1
        assert parsed["diffs"][0]["old_path"] == "a.py"

    async def test_create_commit(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/repository/commits").mock(
            return_value=Response(
                201,
                json={"id": "new123", "title": "Add file", "message": "Add file"},
            )
        )
        result = await client.call_tool(
            "gitlab_create_commit",
            {
                "project_id": "123",
                "branch": "main",
                "commit_message": "Add file",
                "actions": [{"action": "create", "file_path": "test.txt", "content": "hello"}],
            },
        )
        parsed = _parse(result)
        assert parsed["id"] == "new123"

    async def test_compare(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/repository/compare").mock(
            return_value=Response(
                200,
                json={
                    "commit": {"id": "abc"},
                    "commits": [{"id": "abc"}],
                    "diffs": [{"old_path": "a.py", "new_path": "a.py"}],
                },
            )
        )
        result = await client.call_tool(
            "gitlab_compare",
            {"project_id": "123", "from": "main", "to": "develop"},
        )
        parsed = _parse(result)
        assert "diffs" in parsed
        assert len(parsed["commits"]) == 1


# ═══════════════════════════════════════════════════════
# Merge Requests (additional write operations)
# ═══════════════════════════════════════════════════════


class TestMergeRequestWrites:
    async def test_update_mr(self, tool_client):
        client, router = tool_client
        router.put("/projects/123/merge_requests/1").mock(
            return_value=Response(
                200,
                json={"iid": 1, "title": "Updated Title", "state": "opened"},
            )
        )
        result = await client.call_tool(
            "gitlab_update_mr",
            {"project_id": "123", "mr_iid": 1, "title": "Updated Title"},
        )
        parsed = _parse(result)
        assert parsed["title"] == "Updated Title"

    async def test_merge_mr(self, tool_client):
        client, router = tool_client
        router.put("/projects/123/merge_requests/1/merge").mock(
            return_value=Response(
                200,
                json={"iid": 1, "state": "merged", "merge_commit_sha": "deadbeef"},
            )
        )
        result = await client.call_tool(
            "gitlab_merge_mr",
            {"project_id": "123", "mr_iid": 1},
        )
        parsed = _parse(result)
        assert parsed["state"] == "merged"

    async def test_merge_mr_sequence(self, tool_client):
        client, router = tool_client
        # Mock GET for mergeable check on each MR
        router.get("/projects/123/merge_requests/1").mock(
            return_value=Response(
                200,
                json={"iid": 1, "detailed_merge_status": "mergeable"},
            )
        )
        router.get("/projects/123/merge_requests/2").mock(
            return_value=Response(
                200,
                json={"iid": 2, "detailed_merge_status": "mergeable"},
            )
        )
        # Mock PUT for merge on each MR
        router.put("/projects/123/merge_requests/1/merge").mock(
            return_value=Response(200, json={"iid": 1, "state": "merged"})
        )
        router.put("/projects/123/merge_requests/2/merge").mock(
            return_value=Response(200, json={"iid": 2, "state": "merged"})
        )
        result = await client.call_tool(
            "gitlab_merge_mr_sequence",
            {"project_id": "123", "mr_iids": [1, 2]},
        )
        parsed = _parse(result)
        assert parsed["status"] == "all_merged"
        assert parsed["merged"] == [1, 2]

    async def test_rebase_mr(self, tool_client):
        client, router = tool_client
        router.put("/projects/123/merge_requests/1/rebase").mock(
            return_value=Response(200, json={"rebase_in_progress": True})
        )
        result = await client.call_tool(
            "gitlab_rebase_mr",
            {"project_id": "123", "mr_iid": 1},
        )
        parsed = _parse(result)
        assert parsed["rebase_in_progress"] is True

    async def test_mr_changes(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/merge_requests/1/changes").mock(
            return_value=Response(
                200,
                json={
                    "iid": 1,
                    "changes": [{"old_path": "a.py", "new_path": "a.py", "diff": "@@..."}],
                },
            )
        )
        result = await client.call_tool(
            "gitlab_mr_changes",
            {"project_id": "123", "mr_iid": 1},
        )
        parsed = _parse(result)
        assert parsed["iid"] == 1
        assert len(parsed["changes"]) == 1


# ═══════════════════════════════════════════════════════
# MR Notes
# ═══════════════════════════════════════════════════════


class TestMRNotes:
    async def test_list_mr_notes(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/merge_requests/1/notes").mock(
            return_value=Response(
                200,
                json=[
                    {"id": 5, "body": "Looks good", "system": False},
                    {"id": 6, "body": "Auto-merged", "system": True},
                ],
            )
        )
        result = await client.call_tool(
            "gitlab_list_mr_notes",
            {"project_id": "123", "mr_iid": 1},
        )
        parsed = _parse(result)
        # System notes filtered out by default
        assert parsed["count"] == 1
        assert parsed["items"][0]["id"] == 5

    async def test_add_mr_note(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/merge_requests/1/notes").mock(
            return_value=Response(201, json={"id": 7, "body": "New comment", "system": False})
        )
        result = await client.call_tool(
            "gitlab_add_mr_note",
            {"project_id": "123", "mr_iid": 1, "body": "New comment"},
        )
        parsed = _parse(result)
        assert parsed["id"] == 7
        assert parsed["body"] == "New comment"

    async def test_delete_mr_note(self, tool_client):
        client, router = tool_client
        router.delete("/projects/123/merge_requests/1/notes/5").mock(return_value=Response(204))
        result = await client.call_tool(
            "gitlab_delete_mr_note",
            {"project_id": "123", "mr_iid": 1, "note_id": 5},
        )
        parsed = _parse(result)
        assert parsed["status"] == "deleted"
        assert parsed["note_id"] == 5

    async def test_update_mr_note(self, tool_client):
        client, router = tool_client
        router.put("/projects/123/merge_requests/1/notes/5").mock(
            return_value=Response(200, json={"id": 5, "body": "Updated comment"})
        )
        result = await client.call_tool(
            "gitlab_update_mr_note",
            {"project_id": "123", "mr_iid": 1, "note_id": 5, "body": "Updated comment"},
        )
        parsed = _parse(result)
        assert parsed["id"] == 5
        assert parsed["body"] == "Updated comment"

    async def test_award_emoji(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/merge_requests/1/notes/5/award_emoji").mock(
            return_value=Response(201, json={"id": 1, "name": "thumbsup", "awardable_type": "Note"})
        )
        result = await client.call_tool(
            "gitlab_award_emoji",
            {"project_id": "123", "mr_iid": 1, "note_id": 5, "emoji": "thumbsup"},
        )
        parsed = _parse(result)
        assert parsed["id"] == 1
        assert parsed["name"] == "thumbsup"

    async def test_remove_emoji(self, tool_client):
        client, router = tool_client
        router.delete("/projects/123/merge_requests/1/notes/5/award_emoji/1").mock(
            return_value=Response(204)
        )
        result = await client.call_tool(
            "gitlab_remove_emoji",
            {"project_id": "123", "mr_iid": 1, "note_id": 5, "award_id": 1},
        )
        parsed = _parse(result)
        assert parsed["status"] == "removed"
        assert parsed["award_id"] == 1


# ═══════════════════════════════════════════════════════
# MR Discussions
# ═══════════════════════════════════════════════════════


class TestMRDiscussions:
    async def test_list_mr_discussions(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/merge_requests/1/discussions").mock(
            return_value=Response(
                200,
                json=[
                    {
                        "id": "abc",
                        "notes": [{"id": 1, "body": "Review comment", "system": False}],
                    },
                    {
                        "id": "def",
                        "notes": [{"id": 2, "body": "System action", "system": True}],
                    },
                ],
            )
        )
        result = await client.call_tool(
            "gitlab_list_mr_discussions",
            {"project_id": "123", "mr_iid": 1},
        )
        parsed = _parse(result)
        # System-only discussions filtered out
        assert parsed["count"] == 1
        assert parsed["items"][0]["id"] == "abc"

    async def test_create_mr_discussion(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/merge_requests/1/discussions").mock(
            return_value=Response(
                201,
                json={
                    "id": "ghi",
                    "notes": [{"id": 3, "body": "New discussion"}],
                },
            )
        )
        result = await client.call_tool(
            "gitlab_create_mr_discussion",
            {"project_id": "123", "mr_iid": 1, "body": "New discussion"},
        )
        parsed = _parse(result)
        assert parsed["id"] == "ghi"

    async def test_reply_to_discussion(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/merge_requests/1/discussions/abc/notes").mock(
            return_value=Response(201, json={"id": 4, "body": "Reply here"})
        )
        result = await client.call_tool(
            "gitlab_reply_to_discussion",
            {
                "project_id": "123",
                "mr_iid": 1,
                "discussion_id": "abc",
                "body": "Reply here",
            },
        )
        parsed = _parse(result)
        assert parsed["id"] == 4
        assert parsed["body"] == "Reply here"

    async def test_resolve_discussion(self, tool_client):
        client, router = tool_client
        router.put("/projects/123/merge_requests/1/discussions/abc").mock(
            return_value=Response(
                200,
                json={"id": "abc", "notes": [{"id": 1}]},
            )
        )
        result = await client.call_tool(
            "gitlab_resolve_discussion",
            {
                "project_id": "123",
                "mr_iid": 1,
                "discussion_id": "abc",
                "resolved": True,
            },
        )
        parsed = _parse(result)
        assert parsed["id"] == "abc"


# ═══════════════════════════════════════════════════════
# Pipelines (write operations)
# ═══════════════════════════════════════════════════════


class TestPipelineWrites:
    async def test_create_pipeline(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/pipeline").mock(
            return_value=Response(201, json={"id": 200, "status": "pending", "ref": "main"})
        )
        result = await client.call_tool(
            "gitlab_create_pipeline",
            {"project_id": "123", "ref": "main"},
        )
        parsed = _parse(result)
        assert parsed["id"] == 200
        assert parsed["status"] == "pending"

    async def test_retry_pipeline(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/pipelines/100/retry").mock(
            return_value=Response(200, json={"id": 100, "status": "pending"})
        )
        result = await client.call_tool(
            "gitlab_retry_pipeline",
            {"project_id": "123", "pipeline_id": 100},
        )
        parsed = _parse(result)
        assert parsed["id"] == 100

    async def test_cancel_pipeline(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/pipelines/100/cancel").mock(
            return_value=Response(200, json={"id": 100, "status": "canceled"})
        )
        result = await client.call_tool(
            "gitlab_cancel_pipeline",
            {"project_id": "123", "pipeline_id": 100},
        )
        parsed = _parse(result)
        assert parsed["status"] == "canceled"


# ═══════════════════════════════════════════════════════
# Jobs
# ═══════════════════════════════════════════════════════


class TestJobs:
    async def test_retry_job(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/jobs/1/retry").mock(
            return_value=Response(200, json={"id": 2, "name": "build", "status": "pending"})
        )
        result = await client.call_tool(
            "gitlab_retry_job",
            {"project_id": "123", "job_id": 1},
        )
        parsed = _parse(result)
        assert parsed["id"] == 2
        assert parsed["status"] == "pending"

    async def test_play_job(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/jobs/1/play").mock(
            return_value=Response(200, json={"id": 1, "name": "deploy", "status": "pending"})
        )
        result = await client.call_tool(
            "gitlab_play_job",
            {"project_id": "123", "job_id": 1},
        )
        parsed = _parse(result)
        assert parsed["name"] == "deploy"

    async def test_cancel_job(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/jobs/1/cancel").mock(
            return_value=Response(200, json={"id": 1, "name": "build", "status": "canceled"})
        )
        result = await client.call_tool(
            "gitlab_cancel_job",
            {"project_id": "123", "job_id": 1},
        )
        parsed = _parse(result)
        assert parsed["status"] == "canceled"

    async def test_get_job_log(self, tool_client):
        client, router = tool_client
        log_content = "line1\nline2\nline3"
        router.get("/projects/123/jobs/1/trace").mock(return_value=Response(200, text=log_content))
        result = await client.call_tool(
            "gitlab_get_job_log",
            {"project_id": "123", "job_id": 1},
        )
        parsed = _parse(result)
        assert parsed["total_lines"] == 3
        assert parsed["shown_lines"] == 3
        assert "line1" in parsed["log"]
        assert "line3" in parsed["log"]


# ═══════════════════════════════════════════════════════
# Tags
# ═══════════════════════════════════════════════════════


class TestTags:
    async def test_list_tags(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/repository/tags").mock(
            return_value=Response(
                200,
                json=[
                    {"name": "v1.0", "message": "Release 1.0"},
                    {"name": "v2.0", "message": "Release 2.0"},
                ],
            )
        )
        result = await client.call_tool("gitlab_list_tags", {"project_id": "123"})
        parsed = _parse(result)
        assert parsed["count"] == 2
        assert parsed["items"][0]["name"] == "v1.0"

    async def test_get_tag(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/repository/tags/v1.0").mock(
            return_value=Response(
                200,
                json={
                    "name": "v1.0",
                    "message": "Release 1.0",
                    "commit": {"id": "abc123"},
                },
            )
        )
        result = await client.call_tool(
            "gitlab_get_tag",
            {"project_id": "123", "tag_name": "v1.0"},
        )
        parsed = _parse(result)
        assert parsed["name"] == "v1.0"
        assert parsed["commit"]["id"] == "abc123"

    async def test_create_tag(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/repository/tags").mock(
            return_value=Response(
                201,
                json={"name": "v3.0", "commit": {"id": "def456"}},
            )
        )
        result = await client.call_tool(
            "gitlab_create_tag",
            {"project_id": "123", "tag_name": "v3.0", "ref": "main"},
        )
        parsed = _parse(result)
        assert parsed["name"] == "v3.0"

    async def test_delete_tag(self, tool_client):
        client, router = tool_client
        router.delete("/projects/123/repository/tags/v1.0").mock(return_value=Response(204))
        result = await client.call_tool(
            "gitlab_delete_tag",
            {"project_id": "123", "tag_name": "v1.0"},
        )
        parsed = _parse(result)
        assert parsed["status"] == "deleted"
        assert parsed["tag"] == "v1.0"


# ═══════════════════════════════════════════════════════
# Releases
# ═══════════════════════════════════════════════════════


class TestReleases:
    async def test_list_releases(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/releases").mock(
            return_value=Response(
                200,
                json=[
                    {"tag_name": "v1.0", "name": "Release 1.0"},
                    {"tag_name": "v2.0", "name": "Release 2.0"},
                ],
            )
        )
        result = await client.call_tool("gitlab_list_releases", {"project_id": "123"})
        parsed = _parse(result)
        assert parsed["count"] == 2
        assert parsed["items"][0]["tag_name"] == "v1.0"

    async def test_get_release(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/releases/v1.0").mock(
            return_value=Response(
                200,
                json={
                    "tag_name": "v1.0",
                    "name": "Release 1.0",
                    "description": "First release",
                },
            )
        )
        result = await client.call_tool(
            "gitlab_get_release",
            {"project_id": "123", "tag_name": "v1.0"},
        )
        parsed = _parse(result)
        assert parsed["tag_name"] == "v1.0"
        assert parsed["description"] == "First release"

    async def test_create_release(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/releases").mock(
            return_value=Response(
                201,
                json={"tag_name": "v3.0", "name": "Release 3.0"},
            )
        )
        result = await client.call_tool(
            "gitlab_create_release",
            {"project_id": "123", "tag_name": "v3.0", "name": "Release 3.0"},
        )
        parsed = _parse(result)
        assert parsed["tag_name"] == "v3.0"

    async def test_update_release(self, tool_client):
        client, router = tool_client
        router.put("/projects/123/releases/v1.0").mock(
            return_value=Response(
                200,
                json={"tag_name": "v1.0", "name": "Updated Release 1.0"},
            )
        )
        result = await client.call_tool(
            "gitlab_update_release",
            {"project_id": "123", "tag_name": "v1.0", "name": "Updated Release 1.0"},
        )
        parsed = _parse(result)
        assert parsed["name"] == "Updated Release 1.0"

    async def test_delete_release(self, tool_client):
        client, router = tool_client
        router.delete("/projects/123/releases/v1.0").mock(return_value=Response(204))
        result = await client.call_tool(
            "gitlab_delete_release",
            {"project_id": "123", "tag_name": "v1.0"},
        )
        parsed = _parse(result)
        assert parsed["status"] == "deleted"
        assert parsed["tag_name"] == "v1.0"


# ═══════════════════════════════════════════════════════
# Issues (additional operations)
# ═══════════════════════════════════════════════════════


class TestIssueExtras:
    async def test_get_issue(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/issues/1").mock(
            return_value=Response(
                200,
                json={"iid": 1, "title": "Bug report", "state": "opened"},
            )
        )
        result = await client.call_tool(
            "gitlab_get_issue",
            {"project_id": "123", "issue_iid": 1},
        )
        parsed = _parse(result)
        assert parsed["iid"] == 1
        assert parsed["title"] == "Bug report"

    async def test_update_issue(self, tool_client):
        client, router = tool_client
        router.put("/projects/123/issues/1").mock(
            return_value=Response(
                200,
                json={"iid": 1, "title": "Updated Bug", "state": "opened"},
            )
        )
        result = await client.call_tool(
            "gitlab_update_issue",
            {"project_id": "123", "issue_iid": 1, "title": "Updated Bug"},
        )
        parsed = _parse(result)
        assert parsed["title"] == "Updated Bug"

    async def test_add_issue_comment(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/issues/1/notes").mock(
            return_value=Response(201, json={"id": 20, "body": "Comment on issue"})
        )
        result = await client.call_tool(
            "gitlab_add_issue_comment",
            {"project_id": "123", "issue_iid": 1, "body": "Comment on issue"},
        )
        parsed = _parse(result)
        assert parsed["id"] == 20
        assert parsed["body"] == "Comment on issue"


# ═══════════════════════════════════════════════════════
# Optional parameter coverage
# ═══════════════════════════════════════════════════════


class TestOptionalParams:
    """Exercise optional params to cover 'if X is not None' branches."""

    async def test_create_project_all_opts(self, tool_client):
        client, router = tool_client
        router.post("/projects").mock(return_value=Response(201, json={"id": 1, "name": "test"}))
        result = await client.call_tool(
            "gitlab_create_project",
            {
                "name": "test",
                "path": "test-slug",
                "namespace_id": 42,
                "description": "desc",
                "visibility": "private",
                "initialize_with_readme": True,
                "default_branch": "main",
            },
        )
        parsed = _parse(result)
        assert parsed["id"] == 1

    async def test_update_merge_settings_all_opts(self, tool_client):
        client, router = tool_client
        router.put("/projects/123").mock(return_value=Response(200, json={"id": 123}))
        result = await client.call_tool(
            "gitlab_update_project_merge_settings",
            {
                "project_id": "123",
                "only_allow_merge_if_pipeline_succeeds": True,
                "only_allow_merge_if_all_discussions_are_resolved": True,
                "remove_source_branch_after_merge": True,
                "squash_option": "always",
                "merge_method": "ff",
            },
        )
        parsed = _parse(result)
        assert parsed["id"] == 123

    async def test_update_project_approvals_all_opts(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/approvals").mock(
            return_value=Response(200, json={"approvals_before_merge": 2})
        )
        result = await client.call_tool(
            "gitlab_update_project_approvals",
            {
                "project_id": "123",
                "approvals_before_merge": 2,
                "reset_approvals_on_push": True,
                "disable_overriding_approvers_per_merge_request": False,
                "merge_requests_author_approval": False,
                "merge_requests_disable_committers_approval": True,
            },
        )
        parsed = _parse(result)
        assert parsed["approvals_before_merge"] == 2

    async def test_create_approval_rule_with_groups(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/approval_rules").mock(
            return_value=Response(201, json={"id": 1, "name": "devs"})
        )
        result = await client.call_tool(
            "gitlab_create_project_approval_rule",
            {
                "project_id": "123",
                "name": "devs",
                "approvals_required": 1,
                "user_ids": [10],
                "group_ids": [20],
            },
        )
        parsed = _parse(result)
        assert parsed["name"] == "devs"

    async def test_update_approval_rule_all_opts(self, tool_client):
        client, router = tool_client
        router.put("/projects/123/approval_rules/1").mock(
            return_value=Response(200, json={"id": 1, "name": "updated"})
        )
        result = await client.call_tool(
            "gitlab_update_project_approval_rule",
            {
                "project_id": "123",
                "rule_id": 1,
                "name": "updated",
                "approvals_required": 2,
                "user_ids": [10, 20],
                "group_ids": [30],
            },
        )
        parsed = _parse(result)
        assert parsed["name"] == "updated"

    async def test_create_mr_approval_rule_all_opts(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/merge_requests/1/approval_rules").mock(
            return_value=Response(201, json={"id": 1, "name": "mr-rule"})
        )
        result = await client.call_tool(
            "gitlab_create_mr_approval_rule",
            {
                "project_id": "123",
                "mr_iid": 1,
                "name": "mr-rule",
                "approvals_required": 1,
                "user_ids": [5],
                "group_ids": [6],
            },
        )
        parsed = _parse(result)
        assert parsed["name"] == "mr-rule"

    async def test_update_mr_approval_rule_all_opts(self, tool_client):
        client, router = tool_client
        router.put("/projects/123/merge_requests/1/approval_rules/1").mock(
            return_value=Response(200, json={"id": 1})
        )
        result = await client.call_tool(
            "gitlab_update_mr_approval_rule",
            {
                "project_id": "123",
                "mr_iid": 1,
                "rule_id": 1,
                "name": "updated",
                "approvals_required": 3,
                "user_ids": [10],
                "group_ids": [20],
            },
        )
        parsed = _parse(result)
        assert parsed["id"] == 1

    async def test_list_groups_with_params(self, tool_client):
        client, router = tool_client
        router.get("/groups").mock(return_value=Response(200, json=[{"id": 10, "name": "g1"}]))
        result = await client.call_tool(
            "gitlab_list_groups",
            {"search": "team", "per_page": 50},
        )
        parsed = _parse(result)
        assert parsed["count"] == 1

    async def test_share_project_with_access_level_name(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/share").mock(return_value=Response(204))
        result = await client.call_tool(
            "gitlab_share_project_with_group",
            {"project_id": "123", "group_id": 10, "access_level": "developer"},
        )
        parsed = _parse(result)
        assert parsed["status"] == "shared"

    async def test_list_commits_with_params(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/repository/commits").mock(
            return_value=Response(200, json=[{"id": "abc", "title": "fix"}])
        )
        result = await client.call_tool(
            "gitlab_list_commits",
            {"project_id": "123", "ref_name": "main", "per_page": 10},
        )
        parsed = _parse(result)
        assert parsed["count"] == 1

    async def test_get_commit_with_diff(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/repository/commits/abc123").mock(
            return_value=Response(200, json={"id": "abc123", "title": "fix"})
        )
        router.get("/projects/123/repository/commits/abc123/diff").mock(
            return_value=Response(
                200, json=[{"old_path": "a.py", "new_path": "a.py", "diff": "@@ -1 +1 @@"}]
            )
        )
        result = await client.call_tool(
            "gitlab_get_commit",
            {"project_id": "123", "sha": "abc123", "include_diff": True},
        )
        parsed = _parse(result)
        assert parsed["id"] == "abc123"
        assert "diffs" in parsed

    async def test_list_mrs_all_filters(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/merge_requests").mock(
            return_value=Response(200, json=[{"iid": 1, "title": "MR"}])
        )
        result = await client.call_tool(
            "gitlab_list_mrs",
            {
                "project_id": "123",
                "state": "opened",
                "scope": "all",
                "source_branch": "feat/x",
                "target_branch": "main",
                "search": "login",
                "labels": "bug,P1",
                "per_page": 50,
            },
        )
        parsed = _parse(result)
        assert parsed["count"] == 1

    async def test_create_mr_all_opts(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/merge_requests").mock(
            return_value=Response(201, json={"iid": 10, "title": "MR"})
        )
        result = await client.call_tool(
            "gitlab_create_mr",
            {
                "project_id": "123",
                "source_branch": "feat/x",
                "target_branch": "main",
                "title": "MR",
                "description": "desc",
                "draft": True,
                "squash": True,
                "remove_source_branch": True,
                "labels": "bug",
            },
        )
        parsed = _parse(result)
        assert parsed["iid"] == 10

    async def test_update_mr_all_opts(self, tool_client):
        client, router = tool_client
        router.put("/projects/123/merge_requests/1").mock(
            return_value=Response(200, json={"iid": 1, "title": "Updated"})
        )
        result = await client.call_tool(
            "gitlab_update_mr",
            {
                "project_id": "123",
                "mr_iid": 1,
                "title": "Updated",
                "description": "new desc",
                "target_branch": "develop",
                "labels": "ready",
                "squash": True,
                "remove_source_branch": True,
                "draft": False,
                "state_event": "close",
            },
        )
        parsed = _parse(result)
        assert parsed["title"] == "Updated"

    async def test_merge_mr_all_opts(self, tool_client):
        client, router = tool_client
        router.put("/projects/123/merge_requests/1/merge").mock(
            return_value=Response(200, json={"iid": 1, "state": "merged"})
        )
        result = await client.call_tool(
            "gitlab_merge_mr",
            {
                "project_id": "123",
                "mr_iid": 1,
                "squash": True,
                "delete_source_branch": True,
                "merge_commit_message": "Merge feat",
                "squash_commit_message": "squash msg",
                "merge_when_pipeline_succeeds": True,
            },
        )
        parsed = _parse(result)
        assert parsed["state"] == "merged"

    async def test_merge_mr_sequence_all_opts(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/merge_requests/1").mock(
            return_value=Response(200, json={"iid": 1, "detailed_merge_status": "mergeable"})
        )
        router.get("/projects/123/merge_requests/2").mock(
            return_value=Response(200, json={"iid": 2, "detailed_merge_status": "mergeable"})
        )
        router.put("/projects/123/merge_requests/1/merge").mock(
            return_value=Response(200, json={"iid": 1})
        )
        router.put("/projects/123/merge_requests/2/merge").mock(
            return_value=Response(200, json={"iid": 2})
        )
        result = await client.call_tool(
            "gitlab_merge_mr_sequence",
            {
                "project_id": "123",
                "mr_iids": [1, 2],
                "squash": True,
                "delete_source_branch": True,
                "merge_when_pipeline_succeeds": False,
            },
        )
        parsed = _parse(result)
        assert parsed["status"] == "all_merged"

    async def test_merge_mr_sequence_not_mergeable(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/merge_requests/1").mock(
            return_value=Response(200, json={"iid": 1, "detailed_merge_status": "not_open"})
        )
        result = await client.call_tool(
            "gitlab_merge_mr_sequence",
            {"project_id": "123", "mr_iids": [1]},
        )
        parsed = _parse(result)
        assert "error" in parsed
        assert "not mergeable" in parsed["error"]

    async def test_add_mr_note_internal(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/merge_requests/1/notes").mock(
            return_value=Response(201, json={"id": 1, "body": "internal note"})
        )
        result = await client.call_tool(
            "gitlab_add_mr_note",
            {
                "project_id": "123",
                "mr_iid": 1,
                "body": "internal note",
                "internal": True,
            },
        )
        parsed = _parse(result)
        assert parsed["body"] == "internal note"

    async def test_create_mr_discussion_inline(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/merge_requests/1/discussions").mock(
            return_value=Response(201, json={"id": "d1", "notes": [{"body": "nit"}]})
        )
        result = await client.call_tool(
            "gitlab_create_mr_discussion",
            {
                "project_id": "123",
                "mr_iid": 1,
                "body": "nit: rename this",
                "base_sha": "aaa",
                "head_sha": "bbb",
                "start_sha": "ccc",
                "new_path": "src/main.py",
                "old_path": "src/main.py",
                "new_line": 42,
                "old_line": 40,
            },
        )
        parsed = _parse(result)
        assert parsed["id"] == "d1"

    async def test_create_mr_discussion_multiline(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/merge_requests/1/discussions").mock(
            return_value=Response(201, json={"id": "d2"})
        )
        result = await client.call_tool(
            "gitlab_create_mr_discussion",
            {
                "project_id": "123",
                "mr_iid": 1,
                "body": "refactor this block",
                "base_sha": "aaa",
                "head_sha": "bbb",
                "start_sha": "ccc",
                "new_path": "src/main.py",
                "new_line": 50,
                "line_range_start_line": 45,
                "line_range_end_line": 55,
                "line_range_type": "new",
            },
        )
        parsed = _parse(result)
        assert parsed["id"] == "d2"

    async def test_create_pipeline_with_variables(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/pipeline").mock(
            return_value=Response(201, json={"id": 200, "ref": "main"})
        )
        result = await client.call_tool(
            "gitlab_create_pipeline",
            {
                "project_id": "123",
                "ref": "main",
                "variables": [{"key": "ENV", "value": "test"}],
            },
        )
        parsed = _parse(result)
        assert parsed["id"] == 200

    async def test_play_job_with_variables(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/jobs/1/play").mock(
            return_value=Response(200, json={"id": 1, "status": "manual"})
        )
        result = await client.call_tool(
            "gitlab_play_job",
            {
                "project_id": "123",
                "job_id": 1,
                "variables": [{"key": "DEPLOY_ENV", "value": "staging"}],
            },
        )
        parsed = _parse(result)
        assert parsed["id"] == 1

    async def test_get_job_log_with_tail(self, tool_client):
        client, router = tool_client
        lines = "\n".join(f"line {i}" for i in range(300))
        router.get("/projects/123/jobs/1/trace").mock(return_value=Response(200, text=lines))
        result = await client.call_tool(
            "gitlab_get_job_log",
            {"project_id": "123", "job_id": 1, "tail_lines": 50},
        )
        parsed = _parse(result)
        assert parsed["total_lines"] == 300
        assert parsed["shown_lines"] == 50

    async def test_list_tags_with_filters(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/repository/tags").mock(
            return_value=Response(200, json=[{"name": "v1.0"}])
        )
        result = await client.call_tool(
            "gitlab_list_tags",
            {
                "project_id": "123",
                "search": "v1",
                "order_by": "version",
                "sort": "desc",
                "per_page": 10,
            },
        )
        parsed = _parse(result)
        assert parsed["count"] == 1

    async def test_create_tag_with_message(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/repository/tags").mock(
            return_value=Response(201, json={"name": "v2.0"})
        )
        result = await client.call_tool(
            "gitlab_create_tag",
            {
                "project_id": "123",
                "tag_name": "v2.0",
                "ref": "main",
                "message": "Release v2.0",
            },
        )
        parsed = _parse(result)
        assert parsed["name"] == "v2.0"

    async def test_list_releases_with_per_page(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/releases").mock(
            return_value=Response(200, json=[{"tag_name": "v1.0"}])
        )
        result = await client.call_tool(
            "gitlab_list_releases",
            {"project_id": "123", "per_page": 5},
        )
        parsed = _parse(result)
        assert parsed["count"] == 1

    async def test_create_release_all_opts(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/releases").mock(
            return_value=Response(201, json={"tag_name": "v1.0"})
        )
        result = await client.call_tool(
            "gitlab_create_release",
            {
                "project_id": "123",
                "tag_name": "v1.0",
                "name": "Release v1.0",
                "description": "Changelog",
                "ref": "main",
                "released_at": "2025-01-01T00:00:00Z",
                "links": [{"name": "binary", "url": "https://example.com/bin"}],
            },
        )
        parsed = _parse(result)
        assert parsed["tag_name"] == "v1.0"

    async def test_update_release_all_opts(self, tool_client):
        client, router = tool_client
        router.put("/projects/123/releases/v1.0").mock(
            return_value=Response(200, json={"tag_name": "v1.0"})
        )
        result = await client.call_tool(
            "gitlab_update_release",
            {
                "project_id": "123",
                "tag_name": "v1.0",
                "name": "Updated",
                "description": "Updated changelog",
                "released_at": "2025-02-01T00:00:00Z",
            },
        )
        parsed = _parse(result)
        assert parsed["tag_name"] == "v1.0"

    async def test_create_variable_all_opts(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/variables").mock(
            return_value=Response(201, json={"key": "K", "value": "V"})
        )
        result = await client.call_tool(
            "gitlab_create_variable",
            {
                "project_id": "123",
                "key": "K",
                "value": "V",
                "variable_type": "env_var",
                "protected": True,
                "masked": True,
                "raw": False,
                "environment_scope": "production",
                "description": "desc",
            },
        )
        parsed = _parse(result)
        assert parsed["key"] == "K"

    async def test_update_variable_all_opts(self, tool_client):
        client, router = tool_client
        router.put("/projects/123/variables/K").mock(
            return_value=Response(200, json={"key": "K", "value": "V2"})
        )
        result = await client.call_tool(
            "gitlab_update_variable",
            {
                "project_id": "123",
                "key": "K",
                "value": "V2",
                "variable_type": "file",
                "protected": False,
                "masked": False,
                "raw": True,
                "environment_scope": "*",
                "description": "updated",
            },
        )
        parsed = _parse(result)
        assert parsed["value"] == "V2"

    async def test_create_group_variable_all_opts(self, tool_client):
        client, router = tool_client
        router.post("/groups/10/variables").mock(
            return_value=Response(201, json={"key": "GK", "value": "GV"})
        )
        result = await client.call_tool(
            "gitlab_create_group_variable",
            {
                "group_id": "10",
                "key": "GK",
                "value": "GV",
                "variable_type": "env_var",
                "protected": True,
                "masked": True,
                "raw": False,
                "environment_scope": "*",
                "description": "group var",
            },
        )
        parsed = _parse(result)
        assert parsed["key"] == "GK"

    async def test_update_group_variable_all_opts(self, tool_client):
        client, router = tool_client
        router.put("/groups/10/variables/GK").mock(
            return_value=Response(200, json={"key": "GK", "value": "GV2"})
        )
        result = await client.call_tool(
            "gitlab_update_group_variable",
            {
                "group_id": "10",
                "key": "GK",
                "value": "GV2",
                "variable_type": "file",
                "protected": False,
                "masked": False,
                "raw": True,
                "description": "updated",
            },
        )
        parsed = _parse(result)
        assert parsed["value"] == "GV2"

    async def test_list_issues_all_filters(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/issues").mock(return_value=Response(200, json=[{"iid": 1}]))
        result = await client.call_tool(
            "gitlab_list_issues",
            {
                "project_id": "123",
                "state": "opened",
                "labels": "bug",
                "search": "login",
                "assignee_id": 10,
                "per_page": 25,
            },
        )
        parsed = _parse(result)
        assert parsed["count"] == 1

    async def test_create_issue_all_opts(self, tool_client):
        client, router = tool_client
        router.post("/projects/123/issues").mock(
            return_value=Response(201, json={"iid": 5, "title": "Bug"})
        )
        result = await client.call_tool(
            "gitlab_create_issue",
            {
                "project_id": "123",
                "title": "Bug",
                "description": "Steps to reproduce",
                "labels": "bug,P1",
                "assignee_ids": [10],
                "milestone_id": 3,
                "confidential": True,
                "weight": 3,
            },
        )
        parsed = _parse(result)
        assert parsed["iid"] == 5

    async def test_update_issue_all_opts(self, tool_client):
        client, router = tool_client
        router.put("/projects/123/issues/1").mock(
            return_value=Response(200, json={"iid": 1, "title": "Updated"})
        )
        result = await client.call_tool(
            "gitlab_update_issue",
            {
                "project_id": "123",
                "issue_iid": 1,
                "title": "Updated",
                "description": "new desc",
                "labels": "fixed",
                "state_event": "close",
                "assignee_ids": [20],
                "weight": 5,
            },
        )
        parsed = _parse(result)
        assert parsed["title"] == "Updated"
