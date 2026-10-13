"""Tool-level tests — call @mcp.tool functions via FastMCP Client with mocked API."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from fastmcp.exceptions import ToolError
from httpx import Response


def _parse(result: Any) -> dict | list:
    """Extract JSON from a tool call result. FastMCP's ``Client.call_tool`` always
    returns a ``CallToolResult`` whose first content block is the JSON text."""
    return json.loads(result.content[0].text)


def _err_body(result: Any) -> dict:
    """Error-path parse: the MCP error flag must be set; return the JSON body."""
    assert result.is_error is True
    body = _parse(result)
    assert isinstance(body, dict)
    return body


def _assert_unknown_tool(result: Any) -> None:
    """A write tool called under the read-only lock is hidden from the registry, so the
    client gets a protocol "Unknown tool" error rather than the guard envelope."""
    assert result.is_error is True
    assert "unknown tool" in result.content[0].text.lower()


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
        result = await client.call_tool(
            "gitlab_get_project", {"project_id": "nonexistent"}, raise_on_error=False
        )
        parsed = _err_body(result)
        assert "error" in parsed
        assert "hint" in parsed
        assert "Verify" in parsed["hint"]

    async def test_auth_error(self, tool_client):
        client, router = tool_client
        router.get("/projects/123").mock(
            return_value=Response(401, json={"message": "401 Unauthorized"})
        )
        result = await client.call_tool(
            "gitlab_get_project", {"project_id": "123"}, raise_on_error=False
        )
        parsed = _err_body(result)
        assert "error" in parsed
        assert "hint" in parsed
        assert "GITLAB_TOKEN" in parsed["hint"]


# ═══════════════════════════════════════════════════════
# Write operations in read-only mode
# ═══════════════════════════════════════════════════════


class TestReadOnlyMode:
    async def test_create_project_blocked(self, readonly_client):
        client, router = readonly_client
        result = await client.call_tool(
            "gitlab_create_project", {"name": "test"}, raise_on_error=False
        )
        _assert_unknown_tool(result)

    async def test_create_branch_blocked(self, readonly_client):
        client, router = readonly_client
        result = await client.call_tool(
            "gitlab_create_branch",
            {"project_id": "123", "branch_name": "feat/test", "ref": "main"},
            raise_on_error=False,
        )
        _assert_unknown_tool(result)

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
        assert parsed["has_more"] is False
        assert parsed["next_page"] is None

    async def test_truncated_list_says_so(self, tool_client):
        """A capped page must announce itself and say where to resume.

        Without this the caller cannot tell a complete list from a cut one.
        """
        client, router = tool_client
        router.get("/projects/123/repository/branches").mock(
            return_value=Response(200, json=[{"name": "main"}], headers={"X-Next-Page": "2"})
        )
        result = await client.call_tool("gitlab_list_branches", {"project_id": "123"})
        parsed = _parse(result)
        assert parsed["has_more"] is True
        assert parsed["next_page"] == 2

    async def test_page_argument_is_sent_upstream(self, tool_client):
        client, router = tool_client
        route = router.get("/projects/123/repository/branches").mock(
            return_value=Response(200, json=[])
        )
        await client.call_tool("gitlab_list_branches", {"project_id": "123", "page": 3})
        assert route.calls.last.request.url.params["page"] == "3"


# ═══════════════════════════════════════════════════════
# Merge Requests
# ═══════════════════════════════════════════════════════


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

    async def test_slim_pipeline_strips_extra_keys(self, tool_client):
        client, router = tool_client
        full_pipeline = {
            "id": 200,
            "status": "success",
            "ref": "main",
            "sha": "abc123",
            "failure_reason": "config_error",
            "web_url": "https://gitlab.example.com/pipelines/200",
            "user": {"id": 1, "name": "dev", "avatar_url": "https://example.com/avatar.png"},
            "detailed_status": {"icon": "status_success", "text": "passed"},
            "coverage": "85.5",
            "yaml_errors": None,
            "before_sha": "000000",
        }
        full_job = {
            "id": 10,
            "name": "build",
            "stage": "build",
            "status": "success",
            "ref": "main",
            "failure_reason": "script_failure",
            "web_url": "https://gitlab.example.com/jobs/10",
            "runner": {"id": 1, "description": "shared-runner"},
            "artifacts": [{"filename": "out.zip"}],
            "commit": {"id": "abc123", "message": "fix"},
            "pipeline": {"id": 200, "status": "success"},
            "project": {"id": 123},
        }
        router.get("/projects/123/pipelines/200").mock(
            return_value=Response(200, json=full_pipeline)
        )
        router.get("/projects/123/pipelines/200/jobs").mock(
            return_value=Response(200, json=[full_job])
        )
        result = await client.call_tool(
            "gitlab_get_pipeline",
            {"project_id": "123", "pipeline_id": 200, "include_jobs": True},
        )
        parsed = _parse(result)
        # Pipeline: extra keys stripped
        assert "user" not in parsed
        assert "detailed_status" not in parsed
        assert "coverage" not in parsed
        assert "yaml_errors" not in parsed
        assert "before_sha" not in parsed
        assert parsed["id"] == 200
        assert parsed["failure_reason"] == "config_error"
        assert parsed["web_url"] == "https://gitlab.example.com/pipelines/200"
        # Job: extra keys stripped
        job = parsed["jobs"][0]
        assert "runner" not in job
        assert "artifacts" not in job
        assert "commit" not in job
        assert "pipeline" not in job
        assert "project" not in job
        assert job["id"] == 10
        assert job["name"] == "build"
        assert job["failure_reason"] == "script_failure"
        assert job["web_url"] == "https://gitlab.example.com/jobs/10"

    async def test_slim_false_returns_full_response(self, tool_client):
        client, router = tool_client
        full_pipeline = {
            "id": 300,
            "status": "success",
            "ref": "main",
            "user": {"id": 1, "name": "dev"},
            "detailed_status": {"icon": "status_success"},
            "coverage": "90.0",
        }
        full_job = {
            "id": 20,
            "name": "test",
            "status": "success",
            "runner": {"id": 5, "description": "shared"},
            "artifacts": [{"filename": "report.xml"}],
        }
        router.get("/projects/123/pipelines/300").mock(
            return_value=Response(200, json=full_pipeline)
        )
        router.get("/projects/123/pipelines/300/jobs").mock(
            return_value=Response(200, json=[full_job])
        )
        result = await client.call_tool(
            "gitlab_get_pipeline",
            {"project_id": "123", "pipeline_id": 300, "include_jobs": True, "slim": False},
        )
        parsed = _parse(result)
        assert parsed["user"] == {"id": 1, "name": "dev"}
        assert parsed["detailed_status"] == {"icon": "status_success"}
        assert parsed["coverage"] == "90.0"
        assert parsed["jobs"][0]["runner"] == {"id": 5, "description": "shared"}
        assert parsed["jobs"][0]["artifacts"] == [{"filename": "report.xml"}]


# ═══════════════════════════════════════════════════════
# Issues
# ═══════════════════════════════════════════════════════


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
            raise_on_error=False,
        )
        parsed = _err_body(result)
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
            raise_on_error=False,
        )
        parsed = _err_body(result)
        assert parsed["status_code"] == 422
        assert "hint" in parsed
        assert "Validation" in parsed["hint"]

    async def test_429_rate_limit_hint(self, tool_client):
        client, router = tool_client
        router.get("/projects/123").mock(return_value=Response(429, text="Rate limit exceeded"))
        result = await client.call_tool(
            "gitlab_get_project", {"project_id": "123"}, raise_on_error=False
        )
        parsed = _err_body(result)
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

    async def test_delete_variable_rejects_dot_segment_key(self, tool_client):
        """R01: key='..' must not collapse to DELETE /projects/123 (project delete)."""
        client, router = tool_client
        router._assert_all_called = False
        trap = router.delete("/projects/123").mock(return_value=Response(200, json={}))
        result = await client.call_tool(
            "gitlab_delete_variable",
            {"project_id": "123", "key": ".."},
            raise_on_error=False,
        )
        parsed = _err_body(result)
        assert "error" in parsed
        assert not trap.called


# ═══════════════════════════════════════════════════════
# Projects (write operations)
# ═══════════════════════════════════════════════════════


class TestProjectWrites:
    async def test_delete_project(self, tool_client):
        client, router = tool_client
        router.delete("/projects/123").mock(return_value=Response(204))
        result = await client.call_tool("gitlab_delete_project", {"project_id": "123"})
        parsed = _parse(result)
        assert parsed["status"] == "deleted"
        assert parsed["project_id"] == "123"


# ═══════════════════════════════════════════════════════
# Approvals
# ═══════════════════════════════════════════════════════


class TestApprovals:
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
    async def test_unshare_project_with_group(self, tool_client):
        client, router = tool_client
        router.delete("/projects/123/share/10").mock(return_value=Response(204))
        result = await client.call_tool(
            "gitlab_unshare_project_with_group",
            {"project_id": "123", "group_id": 10},
        )
        parsed = _parse(result)
        assert parsed["status"] == "unshared"

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


# ═══════════════════════════════════════════════════════
# Merge Requests (additional write operations)
# ═══════════════════════════════════════════════════════


class TestMergeRequestWrites:
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

    async def test_mr_changes(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/merge_requests/1/diffs").mock(
            return_value=Response(
                200,
                json=[{"old_path": "a.py", "new_path": "a.py", "diff": "@@..."}],
                headers={"x-next-page": "2"},
            )
        )
        result = await client.call_tool(
            "gitlab_mr_changes",
            {"project_id": "123", "mr_iid": 1},
        )
        parsed = _parse(result)
        assert parsed["count"] == 1
        assert parsed["items"][0]["old_path"] == "a.py"
        assert parsed["has_more"] is True
        assert parsed["next_page"] == 2

    async def test_mr_changes_truncates_large_diff(self, tool_client):
        """R02: a file diff over the per-file cap is truncated and flagged."""
        from mcp_gitlab.servers.gitlab import _MAX_DIFF_CHARS

        client, router = tool_client
        router.get("/projects/123/merge_requests/1/diffs").mock(
            return_value=Response(
                200,
                json=[{"old_path": "big.lock", "new_path": "big.lock", "diff": "+x\n" * 40000}],
            )
        )
        result = await client.call_tool(
            "gitlab_mr_changes",
            {"project_id": "123", "mr_iid": 1},
        )
        parsed = _parse(result)
        entry = parsed["items"][0]
        assert entry["truncated"] is True
        assert len(entry["diff"]) < _MAX_DIFF_CHARS + 200
        assert "diff truncated" in entry["diff"]

    async def test_compare_truncates_large_diff(self, tool_client):
        """_cap_diffs also guards gitlab_compare, not only mr_changes."""
        from mcp_gitlab.servers.gitlab import _MAX_DIFF_CHARS

        client, router = tool_client
        router.get("/projects/123/repository/compare").mock(
            return_value=Response(
                200,
                json={"diffs": [{"new_path": "big.lock", "diff": "+x\n" * 40000}]},
            )
        )
        result = await client.call_tool(
            "gitlab_compare",
            {"project_id": "123", "from": "main", "to": "dev"},
        )
        entry = _parse(result)["diffs"][0]
        assert entry["truncated"] is True
        assert len(entry["diff"]) < _MAX_DIFF_CHARS + 200
        assert "diff truncated" in entry["diff"]

    async def test_get_commit_truncates_large_diff(self, tool_client):
        """_cap_diffs also guards gitlab_get_commit's diff payload."""
        from mcp_gitlab.servers.gitlab import _MAX_DIFF_CHARS

        client, router = tool_client
        router.get("/projects/123/repository/commits/abc").mock(
            return_value=Response(200, json={"id": "abc", "title": "t"})
        )
        router.get("/projects/123/repository/commits/abc/diff").mock(
            return_value=Response(200, json=[{"new_path": "big.lock", "diff": "+x\n" * 40000}])
        )
        result = await client.call_tool(
            "gitlab_get_commit",
            {"project_id": "123", "sha": "abc", "include_diff": True},
        )
        entry = _parse(result)["diffs"][0]
        assert entry["truncated"] is True
        assert len(entry["diff"]) < _MAX_DIFF_CHARS + 200
        assert "diff truncated" in entry["diff"]


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

    async def test_reply_to_discussion_rejects_dot_segment_id(self, tool_client):
        """R01: discussion_id='..' must not collapse the reply onto another endpoint."""
        client, router = tool_client
        router._assert_all_called = False
        trap = router.post("/projects/123/merge_requests/1/notes").mock(
            return_value=Response(201, json={"id": 9})
        )
        result = await client.call_tool(
            "gitlab_reply_to_discussion",
            {"project_id": "123", "mr_iid": 1, "discussion_id": "..", "body": "x"},
            raise_on_error=False,
        )
        parsed = _err_body(result)
        assert "error" in parsed
        assert not trap.called


# ═══════════════════════════════════════════════════════
# MR Approvals & Metadata
# ═══════════════════════════════════════════════════════


class TestMRApprovalsAndMetadata:
    async def test_approve_mr_readonly_blocked(self, readonly_client):
        client, router = readonly_client
        result = await client.call_tool(
            "gitlab_approve_mr", {"project_id": "123", "mr_iid": 1}, raise_on_error=False
        )
        _assert_unknown_tool(result)

    async def test_unapprove_mr_readonly_blocked(self, readonly_client):
        client, router = readonly_client
        result = await client.call_tool(
            "gitlab_unapprove_mr", {"project_id": "123", "mr_iid": 1}, raise_on_error=False
        )
        _assert_unknown_tool(result)

    async def test_subscribe_mr_readonly_blocked(self, readonly_client):
        client, router = readonly_client
        result = await client.call_tool(
            "gitlab_subscribe_mr", {"project_id": "123", "mr_iid": 1}, raise_on_error=False
        )
        _assert_unknown_tool(result)

    async def test_unsubscribe_mr_readonly_blocked(self, readonly_client):
        client, router = readonly_client
        result = await client.call_tool(
            "gitlab_unsubscribe_mr", {"project_id": "123", "mr_iid": 1}, raise_on_error=False
        )
        _assert_unknown_tool(result)


# ═══════════════════════════════════════════════════════
# Pipelines (write operations)
# ═══════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════
# Jobs
# ═══════════════════════════════════════════════════════


class TestJobs:
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

    async def test_get_job_log_with_tail(self, tool_client):
        """A positive tail_lines returns only the last N lines (``gitlab.py`` slice)."""
        client, router = tool_client
        log_content = "\n".join(f"line{i}" for i in range(1, 11))
        router.get("/projects/123/jobs/1/trace").mock(return_value=Response(200, text=log_content))
        result = await client.call_tool(
            "gitlab_get_job_log",
            {"project_id": "123", "job_id": 1, "tail_lines": 3},
        )
        parsed = _parse(result)
        assert parsed["total_lines"] == 10
        assert parsed["shown_lines"] == 3
        assert parsed["log"].splitlines() == ["line8", "line9", "line10"]


# ═══════════════════════════════════════════════════════
# Tags
# ═══════════════════════════════════════════════════════


class TestTags:
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


# ═══════════════════════════════════════════════════════
# Optional parameter coverage
# ═══════════════════════════════════════════════════════


class TestOptionalParams:
    """Exercise optional params to cover 'if X is not None' branches."""

    async def test_merge_mr_sequence_not_mergeable(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/merge_requests/1").mock(
            return_value=Response(200, json={"iid": 1, "detailed_merge_status": "not_open"})
        )
        result = await client.call_tool(
            "gitlab_merge_mr_sequence",
            {"project_id": "123", "mr_iids": [1]},
            raise_on_error=False,
        )
        assert result.is_error is True
        parsed = _parse(result)
        assert "error" in parsed
        assert "not mergeable" in parsed["error"]
        assert parsed["merged_so_far"] == []

    async def test_merge_mr_sequence_reports_scheduled(self, tool_client):
        """R03: an MWPS merge comes back still-open with the flag set — it is
        scheduled, not merged, and the batch status reflects that."""
        client, router = tool_client
        router.get("/projects/123/merge_requests/1").mock(
            return_value=Response(200, json={"iid": 1, "detailed_merge_status": "ci_still_running"})
        )
        router.put("/projects/123/merge_requests/1/merge").mock(
            return_value=Response(
                200, json={"iid": 1, "state": "opened", "merge_when_pipeline_succeeds": True}
            )
        )
        result = await client.call_tool(
            "gitlab_merge_mr_sequence",
            {"project_id": "123", "mr_iids": [1], "merge_when_pipeline_succeeds": True},
        )
        parsed = _parse(result)
        assert parsed["scheduled"] == [1]
        assert parsed["merged"] == []
        assert parsed["status"] == "merged_and_scheduled"

    async def test_merge_mr_sequence_repolls_unchecked(self, tool_client, monkeypatch):
        """R03: merging MR N re-marks the next MR unchecked; the sequence polls
        it to mergeable instead of bailing out."""
        import mcp_gitlab.servers.gitlab as glmod

        monkeypatch.setattr(glmod, "_MERGE_POLL_DELAY", 0)
        client, router = tool_client
        router.get("/projects/123/merge_requests/1").mock(
            side_effect=[
                Response(200, json={"iid": 1, "detailed_merge_status": "unchecked"}),
                Response(200, json={"iid": 1, "detailed_merge_status": "mergeable"}),
            ]
        )
        router.put("/projects/123/merge_requests/1/merge").mock(
            return_value=Response(200, json={"iid": 1, "state": "merged"})
        )
        result = await client.call_tool(
            "gitlab_merge_mr_sequence",
            {"project_id": "123", "mr_iids": [1]},
        )
        parsed = _parse(result)
        assert parsed["merged"] == [1]
        assert parsed["status"] == "all_merged"

    async def test_create_mr_discussion_inline(self, tool_client):
        """Gap (a): pin the inline ``position`` hash on the wire, not just the echo —
        dropping a position field (e.g. ``old_line``) is otherwise invisible."""
        client, router = tool_client
        route = router.post("/projects/123/merge_requests/1/discussions").mock(
            return_value=Response(201, json={"id": "d1"})
        )
        await client.call_tool(
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
        assert json.loads(route.calls.last.request.content) == {
            "body": "nit: rename this",
            "position": {
                "base_sha": "aaa",
                "start_sha": "ccc",
                "head_sha": "bbb",
                "position_type": "text",
                "new_path": "src/main.py",
                "old_path": "src/main.py",
                "new_line": 42,
                "old_line": 40,
            },
        }

    async def test_create_mr_discussion_multiline(self, tool_client):
        """Gap (a): a multi-line comment builds a ``line_range`` with start/end keyed by
        ``line_range_type`` (``gitlab.py`` ``_text_position``); pin it on the wire."""
        client, router = tool_client
        route = router.post("/projects/123/merge_requests/1/discussions").mock(
            return_value=Response(201, json={"id": "d2"})
        )
        await client.call_tool(
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
        assert json.loads(route.calls.last.request.content) == {
            "body": "refactor this block",
            "position": {
                "base_sha": "aaa",
                "start_sha": "ccc",
                "head_sha": "bbb",
                "position_type": "text",
                "new_path": "src/main.py",
                "old_path": "src/main.py",
                "new_line": 50,
                "line_range": {
                    "start": {"type": "new", "new_line": 45},
                    "end": {"type": "new", "new_line": 55},
                },
            },
        }


# ═══════════════════════════════════════════════════════
# Regression tests — defects found by audit
# ═══════════════════════════════════════════════════════


class TestDocstringContracts:
    """Tools whose docstrings promise a specific return shape must deliver it."""

    async def test_merge_mr_sequence_readonly_blocked(self, readonly_client):
        """A write tool, hidden under the read-only lock: the client gets "Unknown tool"."""
        client, router = readonly_client
        result = await client.call_tool(
            "gitlab_merge_mr_sequence",
            {"project_id": "123", "mr_iids": [1, 2]},
            raise_on_error=False,
        )
        _assert_unknown_tool(result)

    async def test_merge_mr_sequence_partial_failure_reports_progress(self, tool_client):
        """A mid-sequence API failure still reports which MRs already merged, plus a hint."""
        client, router = tool_client
        router.get("/projects/123/merge_requests/1").mock(
            return_value=Response(200, json={"iid": 1, "detailed_merge_status": "mergeable"})
        )
        router.put("/projects/123/merge_requests/1/merge").mock(
            return_value=Response(200, json={"iid": 1, "state": "merged"})
        )
        router.get("/projects/123/merge_requests/2").mock(
            return_value=Response(404, json={"message": "404 Not found"})
        )
        result = await client.call_tool(
            "gitlab_merge_mr_sequence",
            {"project_id": "123", "mr_iids": [1, 2]},
            raise_on_error=False,
        )
        assert result.is_error is True
        parsed = _parse(result)
        assert parsed["merged_so_far"] == [1]
        assert parsed["status_code"] == 404
        assert "hint" in parsed

    async def test_delete_tag_returns_tag_key(self, tool_client):
        """Docstring promises {status: deleted, tag} — not tag_name."""
        client, router = tool_client
        router.delete("/projects/123/repository/tags/v1.0").mock(return_value=Response(204))
        result = await client.call_tool(
            "gitlab_delete_tag", {"project_id": "123", "tag_name": "v1.0"}
        )
        parsed = _parse(result)
        assert parsed == {"status": "deleted", "tag": "v1.0"}

    async def test_delete_release_returns_confirmation_not_metadata(self, tool_client):
        """Docstring promises {status: deleted, tag_name}, not the release object."""
        client, router = tool_client
        router.delete("/projects/123/releases/v1.0").mock(return_value=Response(204))
        result = await client.call_tool(
            "gitlab_delete_release", {"project_id": "123", "tag_name": "v1.0"}
        )
        parsed = _parse(result)
        assert parsed == {"status": "deleted", "tag_name": "v1.0"}

    async def test_get_job_log_zero_tail_returns_whole_log(self, tool_client):
        """Docstring promises tail_lines=0 returns the whole log."""
        client, router = tool_client
        lines = "\n".join(f"line {i}" for i in range(300))
        router.get("/projects/123/jobs/1/trace").mock(return_value=Response(200, text=lines))
        result = await client.call_tool(
            "gitlab_get_job_log",
            {"project_id": "123", "job_id": 1, "tail_lines": 0},
        )
        parsed = _parse(result)
        assert parsed["shown_lines"] == 300
        assert parsed["total_lines"] == 300

    async def test_get_job_log_rejects_negative_tail(self, tool_client):
        """Negative tail_lines used to silently drop lines off the front; now rejected."""
        client, router = tool_client
        with pytest.raises(Exception, match="tail_lines"):
            await client.call_tool(
                "gitlab_get_job_log",
                {"project_id": "123", "job_id": 1, "tail_lines": -5},
            )

    @pytest.mark.parametrize(
        "name", ["gitlab_share_group_with_group", "gitlab_share_project_with_group"]
    )
    async def test_invalid_access_level_is_rejected_by_the_schema(self, tool_client, name):
        """A bad level is an input error, not a successful result carrying an error key."""
        client, router = tool_client
        args = {"access_level": "bogus"}
        if name == "gitlab_share_group_with_group":
            args |= {"target_group_id": "9", "source_group_id": 1}
        else:
            args |= {"project_id": "9", "group_id": 1}
        with pytest.raises(ToolError) as exc_info:
            await client.call_tool(name, args)
        assert "maintainer" in str(exc_info.value)
        assert not router.calls

    async def test_tool_descriptions_have_no_blank_line_runs(self, tool_client):
        """Docstrings ship verbatim as MCP tool descriptions — no stray blank-line runs."""
        client, router = tool_client
        tools = await client.list_tools()
        offenders = [t.name for t in tools if t.description and "\n\n\n" in t.description]
        assert offenders == []

    async def test_update_docstrings_only_name_real_params(self, tool_client):
        """Docstrings must not advertise parameters the tool does not accept."""
        client, router = tool_client
        tools = {t.name: t for t in await client.list_tools()}
        for name in ("gitlab_update_mr", "gitlab_update_issue", "gitlab_update_release"):
            desc = tools[name].description.lower()
            params = tools[name].input_schema["properties"]
            assert "milestone" not in desc or any("milestone" in p for p in params)
            assert "assignee" not in desc or any("assignee" in p for p in params)


# ═══════════════════════════════════════════════════════
# Repository Files
# ═══════════════════════════════════════════════════════


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


class TestGetFile:
    async def test_happy_path(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/repository/files/app.py").mock(
            return_value=Response(
                200,
                json={
                    "file_path": "app.py",
                    "size": 11,
                    "encoding": "base64",
                    "blob_id": "b1",
                    "last_commit_id": "c1",
                    "content": _b64("l1\nl2\nl3"),
                },
            )
        )
        result = await client.call_tool(
            "gitlab_get_file", {"project_id": "123", "file_path": "app.py", "ref": "main"}
        )
        parsed = _parse(result)
        assert parsed["content"] == "l1\nl2\nl3"
        assert parsed["total_lines"] == 3
        assert parsed["ref"] == "main"
        assert parsed["blob_id"] == "b1"
        assert parsed["truncated"] is False

    async def test_default_branch_resolved_when_ref_omitted(self, tool_client):
        client, router = tool_client
        router.get("/projects/123").mock(
            return_value=Response(200, json={"id": 123, "default_branch": "develop"})
        )
        files = router.get("/projects/123/repository/files/app.py").mock(
            return_value=Response(200, json={"content": _b64("x"), "encoding": "base64"})
        )
        result = await client.call_tool(
            "gitlab_get_file", {"project_id": "123", "file_path": "app.py"}
        )
        parsed = _parse(result)
        assert parsed["ref"] == "develop"
        assert dict(files.calls.last.request.url.params)["ref"] == "develop"

    async def test_url_encodes_file_path(self, tool_client):
        client, router = tool_client
        route = router.get(url__regex=r".*/repository/files/.*").mock(
            return_value=Response(200, json={"content": _b64("x"), "encoding": "base64"})
        )
        await client.call_tool(
            "gitlab_get_file",
            {"project_id": "123", "file_path": "src/app.py", "ref": "main"},
        )
        assert "files/src%2Fapp.py" in str(route.calls.last.request.url)

    async def test_line_range_slices(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/repository/files/app.py").mock(
            return_value=Response(
                200, json={"content": _b64("l1\nl2\nl3\nl4\nl5"), "encoding": "base64"}
            )
        )
        result = await client.call_tool(
            "gitlab_get_file",
            {
                "project_id": "123",
                "file_path": "app.py",
                "ref": "main",
                "start_line": 2,
                "end_line": 4,
            },
        )
        parsed = _parse(result)
        assert parsed["content"] == "l2\nl3\nl4"
        assert parsed["total_lines"] == 5

    async def test_truncation_marks_large_content(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/repository/files/app.py").mock(
            return_value=Response(200, json={"content": _b64("a" * 100_050), "encoding": "base64"})
        )
        result = await client.call_tool(
            "gitlab_get_file", {"project_id": "123", "file_path": "app.py", "ref": "main"}
        )
        parsed = _parse(result)
        assert parsed["truncated"] is True
        assert "truncated at" in parsed["content"]

    async def test_binary_refused(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/repository/files/app.py").mock(
            return_value=Response(
                200,
                json={"content": base64.b64encode(b"\x00\x01\x02").decode(), "encoding": "base64"},
            )
        )
        result = await client.call_tool(
            "gitlab_get_file",
            {"project_id": "123", "file_path": "app.py", "ref": "main"},
            raise_on_error=False,
        )
        parsed = _err_body(result)
        assert "error" in parsed
        assert "binary" in parsed["error"].lower()

    async def test_invalid_utf8_refused(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/repository/files/app.py").mock(
            return_value=Response(
                200,
                json={"content": base64.b64encode(b"\xff\xfe").decode(), "encoding": "base64"},
            )
        )
        result = await client.call_tool(
            "gitlab_get_file",
            {"project_id": "123", "file_path": "app.py", "ref": "main"},
            raise_on_error=False,
        )
        parsed = _err_body(result)
        assert "error" in parsed
        assert "utf-8" in parsed["error"].lower()

    async def test_not_found_hint(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/repository/files/missing.py").mock(
            return_value=Response(404, json={"message": "404 File Not Found"})
        )
        result = await client.call_tool(
            "gitlab_get_file",
            {"project_id": "123", "file_path": "missing.py", "ref": "main"},
            raise_on_error=False,
        )
        parsed = _err_body(result)
        assert parsed["status_code"] == 404
        assert "Verify" in parsed["hint"]


class TestListTree:
    async def test_happy_path(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/repository/tree").mock(
            return_value=Response(
                200,
                json=[{"id": "a", "name": "src", "type": "tree", "path": "src", "mode": "040000"}],
            )
        )
        result = await client.call_tool("gitlab_list_tree", {"project_id": "123", "ref": "main"})
        parsed = _parse(result)
        assert parsed["count"] == 1
        assert parsed["items"][0]["type"] == "tree"
        assert parsed["has_more"] is False

    async def test_pagination_and_recursive(self, tool_client):
        client, router = tool_client
        route = router.get("/projects/123/repository/tree").mock(
            return_value=Response(200, json=[{"path": "a"}], headers={"X-Next-Page": "2"})
        )
        result = await client.call_tool(
            "gitlab_list_tree", {"project_id": "123", "ref": "main", "recursive": True}
        )
        parsed = _parse(result)
        assert parsed["has_more"] is True
        assert parsed["next_page"] == 2
        assert dict(route.calls.last.request.url.params)["recursive"] == "true"


class TestSearchCode:
    async def test_slim_shape_and_trimmed_data(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/search").mock(
            return_value=Response(
                200,
                json=[
                    {
                        "path": "a.py",
                        "ref": "main",
                        "startline": 10,
                        "data": "x" * 1000,
                        "extra": "dropped",
                    }
                ],
            )
        )
        result = await client.call_tool(
            "gitlab_search_code", {"project_id": "123", "search": "foo"}
        )
        parsed = _parse(result)
        item = parsed["items"][0]
        assert item == {"path": "a.py", "ref": "main", "startline": 10, "data": "x" * 500}


class TestGetBlame:
    async def test_slim_ranges(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/repository/files/app.py/blame").mock(
            return_value=Response(
                200,
                json=[
                    {
                        "commit": {
                            "id": "deadbeef",
                            "author_name": "Dev",
                            "authored_date": "2026-01-01",
                            "message": "fix: thing\n\nbody",
                        },
                        "lines": ["line one"],
                    }
                ],
            )
        )
        result = await client.call_tool(
            "gitlab_get_blame", {"project_id": "123", "file_path": "app.py", "ref": "main"}
        )
        parsed = _parse(result)
        r = parsed["ranges"][0]
        assert r["commit_id"] == "deadbeef"
        assert r["author"] == "Dev"
        assert r["message"] == "fix: thing"
        assert r["lines"] == ["line one"]

    async def test_range_params_forwarded(self, tool_client):
        client, router = tool_client
        route = router.get("/projects/123/repository/files/app.py/blame").mock(
            return_value=Response(200, json=[])
        )
        await client.call_tool(
            "gitlab_get_blame",
            {
                "project_id": "123",
                "file_path": "app.py",
                "ref": "main",
                "start_line": 5,
                "end_line": 20,
            },
        )
        params = dict(route.calls.last.request.url.params)
        assert params["range[start]"] == "5"
        assert params["range[end]"] == "20"


# ═══════════════════════════════════════════════════════
# Draft Notes
# ═══════════════════════════════════════════════════════


class TestDraftNotes:
    async def test_create_body_only(self, tool_client):
        client, router = tool_client
        route = router.post("/projects/123/merge_requests/1/draft_notes").mock(
            return_value=Response(201, json={"id": 7, "note": "looks good"})
        )
        result = await client.call_tool(
            "gitlab_create_draft_note",
            {"project_id": "123", "mr_iid": 1, "body": "looks good"},
        )
        parsed = _parse(result)
        assert parsed["id"] == 7
        assert json.loads(route.calls.last.request.content) == {"note": "looks good"}

    async def test_create_inline_autofills_shas_from_versions(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/merge_requests/1/versions").mock(
            return_value=Response(
                200,
                json=[
                    {
                        "base_commit_sha": "base1",
                        "head_commit_sha": "head1",
                        "start_commit_sha": "start1",
                    }
                ],
            )
        )
        route = router.post("/projects/123/merge_requests/1/draft_notes").mock(
            return_value=Response(201, json={"id": 8})
        )
        result = await client.call_tool(
            "gitlab_create_draft_note",
            {"project_id": "123", "mr_iid": 1, "body": "nit", "new_path": "app.py", "new_line": 42},
        )
        parsed = _parse(result)
        assert parsed["id"] == 8
        pos = json.loads(route.calls.last.request.content)["position"]
        assert pos["base_sha"] == "base1"
        assert pos["head_sha"] == "head1"
        assert pos["start_sha"] == "start1"
        assert pos["new_path"] == "app.py"
        assert pos["new_line"] == 42

    async def test_create_blocked_readonly(self, readonly_client):
        client, _router = readonly_client
        result = await client.call_tool(
            "gitlab_create_draft_note",
            {"project_id": "123", "mr_iid": 1, "body": "x"},
            raise_on_error=False,
        )
        _assert_unknown_tool(result)

    async def test_list(self, tool_client):
        client, router = tool_client
        router.get("/projects/123/merge_requests/1/draft_notes").mock(
            return_value=Response(200, json=[{"id": 1, "note": "a"}, {"id": 2, "note": "b"}])
        )
        result = await client.call_tool(
            "gitlab_list_draft_notes", {"project_id": "123", "mr_iid": 1}
        )
        parsed = _parse(result)
        assert parsed["count"] == 2

    async def test_publish_all(self, tool_client):
        client, router = tool_client
        route = router.post("/projects/123/merge_requests/1/draft_notes/bulk_publish").mock(
            return_value=Response(204)
        )
        result = await client.call_tool(
            "gitlab_publish_draft_notes", {"project_id": "123", "mr_iid": 1}
        )
        parsed = _parse(result)
        assert parsed["status"] == "published"
        assert route.called

    async def test_publish_blocked_readonly(self, readonly_client):
        client, _router = readonly_client
        result = await client.call_tool(
            "gitlab_publish_draft_notes",
            {"project_id": "123", "mr_iid": 1},
            raise_on_error=False,
        )
        _assert_unknown_tool(result)

    async def test_delete(self, tool_client):
        client, router = tool_client
        router.delete("/projects/123/merge_requests/1/draft_notes/5").mock(
            return_value=Response(204)
        )
        result = await client.call_tool(
            "gitlab_delete_draft_note",
            {"project_id": "123", "mr_iid": 1, "draft_note_id": 5},
        )
        parsed = _parse(result)
        assert parsed["status"] == "deleted"
        assert parsed["draft_note_id"] == 5

    async def test_delete_blocked_readonly(self, readonly_client):
        client, _router = readonly_client
        result = await client.call_tool(
            "gitlab_delete_draft_note",
            {"project_id": "123", "mr_iid": 1, "draft_note_id": 5},
            raise_on_error=False,
        )
        _assert_unknown_tool(result)


# ═══════════════════════════════════════════════════════
# Local sign-in: stored-credential scope enforcement + lifespan precedence
# ═══════════════════════════════════════════════════════

from contextlib import asynccontextmanager  # noqa: E402

import respx  # noqa: E402
from fastmcp import Client  # noqa: E402

from mcp_gitlab.client import GitLabClient  # noqa: E402
from mcp_gitlab.config import GitLabConfig  # noqa: E402
from mcp_gitlab.local_auth import CredentialStore  # noqa: E402
from mcp_gitlab.servers.gitlab import lifespan, mcp  # noqa: E402

_TEST_URL = "https://gitlab.example.com"
_API_BASE = f"{_TEST_URL}/api/v4"


class _StubCreds:
    def __init__(self, scopes):
        self.scopes = scopes
        self.access_token = "at"

    async def bearer(self):
        return self.access_token

    async def aclose(self):
        pass


@asynccontextmanager
async def _creds_tool_client(scopes):
    creds = _StubCreds(scopes)
    config = GitLabConfig(url=_TEST_URL, token="", credentials=creds)
    gl = GitLabClient(config)

    @asynccontextmanager
    async def mock_lifespan(server):
        try:
            yield {"client": gl, "config": config}
        finally:
            await gl.close()

    original = mcp._lifespan
    mcp._lifespan = mock_lifespan
    try:
        with respx.mock(base_url=_API_BASE) as router:
            async with Client(mcp) as c:
                yield c, router
    finally:
        mcp._lifespan = original


class TestStoredCredentialScope:
    async def test_check_write_blocks_read_api_credentials(self):
        async with _creds_tool_client(["read_api"]) as (client, router):
            router.get("/projects/123").mock(return_value=Response(200, json={"id": 123}))
            write = _err_body(
                await client.call_tool("gitlab_create_project", {"name": "x"}, raise_on_error=False)
            )
            assert "error" in write
            assert "--scopes api" in write["hint"]
            read = _parse(await client.call_tool("gitlab_get_project", {"project_id": "123"}))
            assert read["id"] == 123

    async def test_api_scope_credentials_allow_writes(self):
        async with _creds_tool_client(["api"]) as (client, router):
            router.post("/projects").mock(return_value=Response(201, json={"id": 5, "name": "x"}))
            created = _parse(await client.call_tool("gitlab_create_project", {"name": "x"}))
            assert created["id"] == 5


class TestLifespanPrecedence:
    """R4 precedence matrix, exercised through the real lifespan."""

    async def test_env_token_ignores_store(self, tmp_path, monkeypatch):
        for var in ("GITLAB_PAT", "GITLAB_PERSONAL_ACCESS_TOKEN", "GITLAB_API_TOKEN"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.setenv("GITLAB_URL", _TEST_URL)
        monkeypatch.setenv("GITLAB_TOKEN", "pat-xyz")
        monkeypatch.delenv("GITLAB_AUTH", raising=False)
        CredentialStore().save(
            _TEST_URL,
            {
                "client_id": "c",
                "access_token": "a",
                "refresh_token": "r",
                "expires_at": 9999999999,
                "scopes": ["api"],
            },
        )
        cm = lifespan(mcp)
        ctx = await cm.__aenter__()
        try:
            assert ctx["config"].credentials is None
            assert ctx["client"]._auth_headers.get("PRIVATE-TOKEN") == "pat-xyz"
        finally:
            await cm.__aexit__(None, None, None)

    async def test_no_env_uses_store_bearer(self, tmp_path, monkeypatch):
        for var in (
            "GITLAB_TOKEN",
            "GITLAB_PAT",
            "GITLAB_PERSONAL_ACCESS_TOKEN",
            "GITLAB_API_TOKEN",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.setenv("GITLAB_URL", _TEST_URL)
        monkeypatch.delenv("GITLAB_AUTH", raising=False)
        CredentialStore().save(
            _TEST_URL,
            {
                "client_id": "c",
                "access_token": "a",
                "refresh_token": "r",
                "expires_at": 9999999999,
                "scopes": ["api"],
            },
        )
        cm = lifespan(mcp)
        ctx = await cm.__aenter__()
        try:
            assert ctx["config"].credentials is not None
            assert ctx["client"]._credentials is not None
            assert ctx["client"]._auth_headers == {}
        finally:
            await cm.__aexit__(None, None, None)

    async def test_no_env_no_file_raises_login_hint(self, tmp_path, monkeypatch):
        for var in (
            "GITLAB_TOKEN",
            "GITLAB_PAT",
            "GITLAB_PERSONAL_ACCESS_TOKEN",
            "GITLAB_API_TOKEN",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.setenv("GITLAB_URL", _TEST_URL)
        monkeypatch.delenv("GITLAB_AUTH", raising=False)
        with pytest.raises(ValueError, match="mcp-gitlab auth login"):
            await lifespan(mcp).__aenter__()
