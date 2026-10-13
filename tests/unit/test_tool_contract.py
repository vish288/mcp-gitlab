"""Wire contract for every ``@mcp.tool``: the request it sends, the envelope it returns.

One row per tool: ``(tool_name, call_args, method, path, expected_query, expected_json_body)``.
Rows were derived by reading each tool body and the ``GitLabClient`` method it calls, not
guessed. They are what makes collapsing the tool bodies -- and later the one-caller client
methods -- a mechanical change rather than a leap.

``test_request_shape`` pins what goes over the wire on success; ``test_forced_failure``
drives the same route to 404 so every tool's ``except`` arm actually executes and its
``_err`` envelope is checked. ``test_every_tool_has_a_row`` keeps the table honest.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import httpx
import pytest
from httpx import Response

from mcp_gitlab.config import GitLabConfig
from mcp_gitlab.servers.gitlab import mcp

P = "/projects/123"
MR = f"{P}/merge_requests/1"
G = "/groups/10"
VARS = [{"key": "A", "value": "1"}]
ACTIONS = [{"action": "create", "file_path": "a.txt", "content": "x"}]
LINKS = [{"name": "bin", "url": "https://example.com/bin"}]

ROWS = [
    # Projects
    ("gitlab_get_project", {"project_id": "123"}, "GET", P, {}, None),
    (
        "gitlab_create_project",
        {"name": "proj", "visibility": "private"},
        "POST",
        "/projects",
        {},
        {"name": "proj", "visibility": "private"},
    ),
    ("gitlab_delete_project", {"project_id": "123"}, "DELETE", P, {}, None),
    (
        "gitlab_update_project_merge_settings",
        {"project_id": "123", "merge_method": "ff"},
        "PUT",
        P,
        {},
        {"merge_method": "ff"},
    ),
    # Project approvals
    ("gitlab_get_project_approvals", {"project_id": "123"}, "GET", f"{P}/approvals", {}, None),
    (
        "gitlab_update_project_approvals",
        {"project_id": "123", "approvals_before_merge": 2},
        "POST",
        f"{P}/approvals",
        {},
        {"approvals_before_merge": 2},
    ),
    (
        "gitlab_list_project_approval_rules",
        {"project_id": "123"},
        "GET",
        f"{P}/approval_rules",
        {},
        None,
    ),
    (
        "gitlab_create_project_approval_rule",
        {"project_id": "123", "name": "r", "approvals_required": 1, "user_ids": [5]},
        "POST",
        f"{P}/approval_rules",
        {},
        {"name": "r", "approvals_required": 1, "user_ids": [5]},
    ),
    (
        "gitlab_update_project_approval_rule",
        {"project_id": "123", "rule_id": 4, "approvals_required": 2},
        "PUT",
        f"{P}/approval_rules/4",
        {},
        {"approvals_required": 2},
    ),
    (
        "gitlab_delete_project_approval_rule",
        {"project_id": "123", "rule_id": 4},
        "DELETE",
        f"{P}/approval_rules/4",
        {},
        None,
    ),
    # MR approval rules
    (
        "gitlab_list_mr_approval_rules",
        {"project_id": "123", "mr_iid": 1},
        "GET",
        f"{MR}/approval_rules",
        {},
        None,
    ),
    (
        "gitlab_create_mr_approval_rule",
        {"project_id": "123", "mr_iid": 1, "name": "r", "approvals_required": 1},
        "POST",
        f"{MR}/approval_rules",
        {},
        {"name": "r", "approvals_required": 1},
    ),
    (
        "gitlab_update_mr_approval_rule",
        {"project_id": "123", "mr_iid": 1, "rule_id": 4, "name": "n"},
        "PUT",
        f"{MR}/approval_rules/4",
        {},
        {"name": "n"},
    ),
    (
        "gitlab_delete_mr_approval_rule",
        {"project_id": "123", "mr_iid": 1, "rule_id": 4},
        "DELETE",
        f"{MR}/approval_rules/4",
        {},
        None,
    ),
    # Groups
    (
        "gitlab_list_groups",
        {"search": "team"},
        "GET",
        "/groups",
        {"per_page": "50", "search": "team", "page": "1"},
        None,
    ),
    ("gitlab_get_group", {"group_id": "10"}, "GET", G, {}, None),
    (
        "gitlab_share_project_with_group",
        {"project_id": "123", "group_id": 10, "access_level": "developer"},
        "POST",
        f"{P}/share",
        {},
        {"group_id": 10, "group_access": 30},
    ),
    (
        "gitlab_unshare_project_with_group",
        {"project_id": "123", "group_id": 10},
        "DELETE",
        f"{P}/share/10",
        {},
        None,
    ),
    (
        "gitlab_share_group_with_group",
        {"target_group_id": "10", "source_group_id": 20, "access_level": "maintainer"},
        "POST",
        f"{G}/share",
        {},
        {"group_id": 20, "group_access": 40},
    ),
    (
        "gitlab_unshare_group_with_group",
        {"target_group_id": "10", "source_group_id": 20},
        "DELETE",
        f"{G}/share/20",
        {},
        None,
    ),
    # Branches
    (
        "gitlab_list_branches",
        {"project_id": "123", "search": "feat"},
        "GET",
        f"{P}/repository/branches",
        {"per_page": "100", "search": "feat", "page": "1"},
        None,
    ),
    (
        "gitlab_create_branch",
        {"project_id": "123", "branch_name": "feat/x", "ref": "main"},
        "POST",
        f"{P}/repository/branches",
        {},
        {"branch": "feat/x", "ref": "main"},
    ),
    (
        "gitlab_delete_branch",
        {"project_id": "123", "branch_name": "old"},
        "DELETE",
        f"{P}/repository/branches/old",
        {},
        None,
    ),
    # Commits
    (
        "gitlab_list_commits",
        {"project_id": "123", "ref_name": "main"},
        "GET",
        f"{P}/repository/commits",
        {"per_page": "40", "ref_name": "main", "page": "1"},
        None,
    ),
    (
        "gitlab_get_commit",
        {"project_id": "123", "sha": "abc"},
        "GET",
        f"{P}/repository/commits/abc",
        {},
        None,
    ),
    (
        "gitlab_create_commit",
        {"project_id": "123", "branch": "main", "commit_message": "m", "actions": ACTIONS},
        "POST",
        f"{P}/repository/commits",
        {},
        {"branch": "main", "commit_message": "m", "actions": ACTIONS},
    ),
    (
        "gitlab_compare",
        {"project_id": "123", "from": "main", "to": "dev"},
        "GET",
        f"{P}/repository/compare",
        {"from": "main", "to": "dev"},
        None,
    ),
    # Merge requests
    (
        "gitlab_list_mrs",
        {"project_id": "123", "state": "opened"},
        "GET",
        f"{P}/merge_requests",
        {"per_page": "20", "state": "opened", "page": "1"},
        None,
    ),
    ("gitlab_get_mr", {"project_id": "123", "mr_iid": 1}, "GET", MR, {}, None),
    (
        "gitlab_create_mr",
        {"project_id": "123", "source_branch": "f", "target_branch": "main", "title": "t"},
        "POST",
        f"{P}/merge_requests",
        {},
        {"source_branch": "f", "target_branch": "main", "title": "t"},
    ),
    (
        "gitlab_update_mr",
        {"project_id": "123", "mr_iid": 1, "title": "t2"},
        "PUT",
        MR,
        {},
        {"title": "t2"},
    ),
    (
        "gitlab_merge_mr",
        {"project_id": "123", "mr_iid": 1, "delete_source_branch": True},
        "PUT",
        f"{MR}/merge",
        {},
        {"should_remove_source_branch": True},
    ),
    (
        "gitlab_merge_mr_sequence",
        {"project_id": "123", "mr_iids": [7], "require_mergeable_status": False, "squash": True},
        "PUT",
        f"{P}/merge_requests/7/merge",
        {},
        {"squash": True},
    ),
    (
        "gitlab_rebase_mr",
        {"project_id": "123", "mr_iid": 1},
        "PUT",
        f"{MR}/rebase",
        {},
        {"skip_ci": False},
    ),
    (
        "gitlab_mr_changes",
        {"project_id": "123", "mr_iid": 1},
        "GET",
        f"{MR}/diffs",
        {"per_page": "20", "page": "1"},
        None,
    ),
    # MR notes
    (
        "gitlab_list_mr_notes",
        {"project_id": "123", "mr_iid": 1},
        "GET",
        f"{MR}/notes",
        {"per_page": "100", "page": "1"},
        None,
    ),
    (
        "gitlab_add_mr_note",
        {"project_id": "123", "mr_iid": 1, "body": "hi", "internal": True},
        "POST",
        f"{MR}/notes",
        {},
        {"body": "hi", "internal": True},
    ),
    (
        "gitlab_delete_mr_note",
        {"project_id": "123", "mr_iid": 1, "note_id": 5},
        "DELETE",
        f"{MR}/notes/5",
        {},
        None,
    ),
    (
        "gitlab_update_mr_note",
        {"project_id": "123", "mr_iid": 1, "note_id": 5, "body": "b"},
        "PUT",
        f"{MR}/notes/5",
        {},
        {"body": "b"},
    ),
    (
        "gitlab_award_emoji",
        {"project_id": "123", "mr_iid": 1, "note_id": 5, "emoji": "thumbsup"},
        "POST",
        f"{MR}/notes/5/award_emoji",
        {},
        {"name": "thumbsup"},
    ),
    (
        "gitlab_remove_emoji",
        {"project_id": "123", "mr_iid": 1, "note_id": 5, "award_id": 9},
        "DELETE",
        f"{MR}/notes/5/award_emoji/9",
        {},
        None,
    ),
    # MR discussions
    (
        "gitlab_list_mr_discussions",
        {"project_id": "123", "mr_iid": 1},
        "GET",
        f"{MR}/discussions",
        {"per_page": "100", "page": "1"},
        None,
    ),
    (
        "gitlab_create_mr_discussion",
        {"project_id": "123", "mr_iid": 1, "body": "nit"},
        "POST",
        f"{MR}/discussions",
        {},
        {"body": "nit"},
    ),
    (
        "gitlab_reply_to_discussion",
        {"project_id": "123", "mr_iid": 1, "discussion_id": "abc", "body": "r"},
        "POST",
        f"{MR}/discussions/abc/notes",
        {},
        {"body": "r"},
    ),
    (
        "gitlab_resolve_discussion",
        {"project_id": "123", "mr_iid": 1, "discussion_id": "abc", "resolved": True},
        "PUT",
        f"{MR}/discussions/abc",
        {},
        {"resolved": True},
    ),
    # MR approvals and metadata
    (
        "gitlab_approve_mr",
        {"project_id": "123", "mr_iid": 1, "sha": "abc"},
        "POST",
        f"{MR}/approve",
        {},
        {"sha": "abc"},
    ),
    (
        "gitlab_unapprove_mr",
        {"project_id": "123", "mr_iid": 1},
        "POST",
        f"{MR}/unapprove",
        {},
        None,
    ),
    (
        "gitlab_get_mr_approvals",
        {"project_id": "123", "mr_iid": 1},
        "GET",
        f"{MR}/approvals",
        {},
        None,
    ),
    (
        "gitlab_list_mr_pipelines",
        {"project_id": "123", "mr_iid": 1},
        "GET",
        f"{MR}/pipelines",
        {"page": "1"},
        None,
    ),
    (
        "gitlab_list_mr_commits",
        {"project_id": "123", "mr_iid": 1},
        "GET",
        f"{MR}/commits",
        {"page": "1"},
        None,
    ),
    (
        "gitlab_subscribe_mr",
        {"project_id": "123", "mr_iid": 1},
        "POST",
        f"{MR}/subscribe",
        {},
        None,
    ),
    (
        "gitlab_unsubscribe_mr",
        {"project_id": "123", "mr_iid": 1},
        "POST",
        f"{MR}/unsubscribe",
        {},
        None,
    ),
    # Pipelines
    (
        "gitlab_list_pipelines",
        {"project_id": "123", "status": "failed"},
        "GET",
        f"{P}/pipelines",
        {"per_page": "20", "status": "failed", "page": "1"},
        None,
    ),
    (
        "gitlab_get_pipeline",
        {"project_id": "123", "pipeline_id": 100},
        "GET",
        f"{P}/pipelines/100",
        {},
        None,
    ),
    (
        "gitlab_create_pipeline",
        {"project_id": "123", "ref": "main", "variables": VARS},
        "POST",
        f"{P}/pipeline",
        {},
        {"ref": "main", "variables": VARS},
    ),
    (
        "gitlab_retry_pipeline",
        {"project_id": "123", "pipeline_id": 100},
        "POST",
        f"{P}/pipelines/100/retry",
        {},
        None,
    ),
    (
        "gitlab_cancel_pipeline",
        {"project_id": "123", "pipeline_id": 100},
        "POST",
        f"{P}/pipelines/100/cancel",
        {},
        None,
    ),
    # Jobs
    ("gitlab_retry_job", {"project_id": "123", "job_id": 7}, "POST", f"{P}/jobs/7/retry", {}, None),
    (
        "gitlab_play_job",
        {"project_id": "123", "job_id": 7, "variables": VARS},
        "POST",
        f"{P}/jobs/7/play",
        {},
        {"job_variables_attributes": VARS},
    ),
    (
        "gitlab_cancel_job",
        {"project_id": "123", "job_id": 7},
        "POST",
        f"{P}/jobs/7/cancel",
        {},
        None,
    ),
    (
        "gitlab_get_job_log",
        {"project_id": "123", "job_id": 7},
        "GET",
        f"{P}/jobs/7/trace",
        {},
        None,
    ),
    # Tags
    (
        "gitlab_list_tags",
        {"project_id": "123", "order_by": "version"},
        "GET",
        f"{P}/repository/tags",
        {"per_page": "20", "order_by": "version", "page": "1"},
        None,
    ),
    (
        "gitlab_get_tag",
        {"project_id": "123", "tag_name": "v1.0"},
        "GET",
        f"{P}/repository/tags/v1.0",
        {},
        None,
    ),
    (
        "gitlab_create_tag",
        {"project_id": "123", "tag_name": "v1.0", "ref": "main", "message": "rel"},
        "POST",
        f"{P}/repository/tags",
        {},
        {"tag_name": "v1.0", "ref": "main", "message": "rel"},
    ),
    (
        "gitlab_delete_tag",
        {"project_id": "123", "tag_name": "v1.0"},
        "DELETE",
        f"{P}/repository/tags/v1.0",
        {},
        None,
    ),
    # Releases
    (
        "gitlab_list_releases",
        {"project_id": "123"},
        "GET",
        f"{P}/releases",
        {"per_page": "20", "page": "1"},
        None,
    ),
    (
        "gitlab_get_release",
        {"project_id": "123", "tag_name": "v1.0"},
        "GET",
        f"{P}/releases/v1.0",
        {},
        None,
    ),
    (
        "gitlab_create_release",
        {"project_id": "123", "tag_name": "v1.0", "links": LINKS},
        "POST",
        f"{P}/releases",
        {},
        {"tag_name": "v1.0", "assets": {"links": LINKS}},
    ),
    (
        "gitlab_update_release",
        {"project_id": "123", "tag_name": "v1.0", "name": "n"},
        "PUT",
        f"{P}/releases/v1.0",
        {},
        {"name": "n"},
    ),
    (
        "gitlab_delete_release",
        {"project_id": "123", "tag_name": "v1.0"},
        "DELETE",
        f"{P}/releases/v1.0",
        {},
        None,
    ),
    # Project variables
    (
        "gitlab_list_variables",
        {"project_id": "123"},
        "GET",
        f"{P}/variables",
        {"per_page": "100", "page": "1"},
        None,
    ),
    (
        "gitlab_create_variable",
        {"project_id": "123", "key": "K", "value": "V", "masked": True},
        "POST",
        f"{P}/variables",
        {},
        {"key": "K", "value": "V", "masked": True},
    ),
    (
        "gitlab_update_variable",
        {"project_id": "123", "key": "K", "value": "V", "environment_scope": "prod"},
        "PUT",
        f"{P}/variables/K",
        {"filter[environment_scope]": "prod"},
        {"value": "V"},
    ),
    (
        "gitlab_delete_variable",
        {"project_id": "123", "key": "K", "environment_scope": "prod"},
        "DELETE",
        f"{P}/variables/K",
        {"filter[environment_scope]": "prod"},
        None,
    ),
    # Group variables
    (
        "gitlab_list_group_variables",
        {"group_id": "10"},
        "GET",
        f"{G}/variables",
        {"per_page": "100", "page": "1"},
        None,
    ),
    (
        "gitlab_create_group_variable",
        {"group_id": "10", "key": "K", "value": "V"},
        "POST",
        f"{G}/variables",
        {},
        {"key": "K", "value": "V"},
    ),
    (
        "gitlab_update_group_variable",
        {"group_id": "10", "key": "K", "value": "V", "protected": True},
        "PUT",
        f"{G}/variables/K",
        {},
        {"value": "V", "protected": True},
    ),
    (
        "gitlab_delete_group_variable",
        {"group_id": "10", "key": "K"},
        "DELETE",
        f"{G}/variables/K",
        {},
        None,
    ),
    # Issues
    (
        "gitlab_list_issues",
        {"project_id": "123", "assignee_id": 4},
        "GET",
        f"{P}/issues",
        {"per_page": "20", "assignee_id": "4", "page": "1"},
        None,
    ),
    ("gitlab_get_issue", {"project_id": "123", "issue_iid": 2}, "GET", f"{P}/issues/2", {}, None),
    (
        "gitlab_create_issue",
        {"project_id": "123", "title": "t", "confidential": True},
        "POST",
        f"{P}/issues",
        {},
        {"title": "t", "confidential": True},
    ),
    (
        "gitlab_update_issue",
        {"project_id": "123", "issue_iid": 2, "state_event": "close"},
        "PUT",
        f"{P}/issues/2",
        {},
        {"state_event": "close"},
    ),
    (
        "gitlab_add_issue_comment",
        {"project_id": "123", "issue_iid": 2, "body": "c"},
        "POST",
        f"{P}/issues/2/notes",
        {},
        {"body": "c"},
    ),
    # Repository files
    (
        "gitlab_get_file",
        {"project_id": "123", "file_path": "app.py", "ref": "main"},
        "GET",
        f"{P}/repository/files/app.py",
        {"ref": "main"},
        None,
    ),
    (
        "gitlab_list_tree",
        {"project_id": "123", "ref": "main"},
        "GET",
        f"{P}/repository/tree",
        {"ref": "main", "per_page": "100", "page": "1"},
        None,
    ),
    (
        "gitlab_search_code",
        {"project_id": "123", "search": "foo"},
        "GET",
        f"{P}/search",
        {"scope": "blobs", "search": "foo", "per_page": "100", "page": "1"},
        None,
    ),
    (
        "gitlab_get_blame",
        {"project_id": "123", "file_path": "app.py", "ref": "main"},
        "GET",
        f"{P}/repository/files/app.py/blame",
        {"ref": "main"},
        None,
    ),
    # Draft notes
    (
        "gitlab_create_draft_note",
        {"project_id": "123", "mr_iid": 1, "body": "c"},
        "POST",
        f"{MR}/draft_notes",
        {},
        {"note": "c"},
    ),
    (
        "gitlab_list_draft_notes",
        {"project_id": "123", "mr_iid": 1},
        "GET",
        f"{MR}/draft_notes",
        {},
        None,
    ),
    (
        "gitlab_publish_draft_notes",
        {"project_id": "123", "mr_iid": 1},
        "POST",
        f"{MR}/draft_notes/bulk_publish",
        {},
        None,
    ),
    (
        "gitlab_delete_draft_note",
        {"project_id": "123", "mr_iid": 1, "draft_note_id": 5},
        "DELETE",
        f"{MR}/draft_notes/5",
        {},
        None,
    ),
]

# Keys _err sets for GitLabNotFoundError. gitlab_merge_mr_sequence adds merged_so_far on top.
NOT_FOUND_KEYS = {"error", "status_code", "body", "hint"}


def _parse(result) -> dict:
    return json.loads(result.content[0].text)


@pytest.mark.parametrize("row", ROWS, ids=[r[0] for r in ROWS])
async def test_request_shape(tool_client, row):
    name, args, method, path, query, body = row
    client, router = tool_client
    payload: list | dict = [] if name.startswith("gitlab_list_") else {}
    route = router.request(method, path).mock(return_value=Response(200, json=payload))

    result = await client.call_tool(name, args)
    # X2: a successful result is not an error and carries the JSON object itself as
    # structuredContent (not the old {"result": "<json string>"} wrapper), byte-for-byte
    # the same object the pretty text decodes to.
    assert result.is_error is False
    assert result.structured_content == json.loads(result.content[0].text)
    parsed = _parse(result)

    assert "error" not in parsed
    req = route.calls.last.request
    assert req.method == method
    assert req.url.raw_path.split(b"?")[0].decode() == f"/api/v4{path}"
    assert dict(req.url.params) == query
    assert (json.loads(req.content) if req.content else None) == body


@pytest.mark.parametrize("row", ROWS, ids=[r[0] for r in ROWS])
async def test_forced_failure(tool_client, row):
    name, args, method, path, _query, _body = row
    client, router = tool_client
    router.request(method, path).mock(return_value=Response(404, json={"message": "404 Not Found"}))

    result = await client.call_tool(name, args, raise_on_error=False)

    assert result.is_error is True
    parsed = _parse(result)
    assert NOT_FOUND_KEYS <= parsed.keys()
    assert parsed["status_code"] == 404


async def test_every_tool_has_a_row(tool_client):
    client, _router = tool_client
    assert {r[0] for r in ROWS} == {t.name for t in await client.list_tools()}


class _NoCallClient:
    """A GitLabClient stand-in that fails if a tool reaches it — proves the read-only
    guard refuses before any upstream call."""

    def __getattr__(self, name: str) -> object:
        msg = f"read-only guard let a write tool reach the client via .{name}"
        raise AssertionError(msg)


async def test_read_only_blocks_every_write_tool():
    """Every write tool must refuse under a read-only config with an ``isError`` result
    and reach no upstream call — the ``_check_write`` guard runs before any mutation.
    Under the lock these tools are hidden from ``tools/list`` (see test_read_only_lock),
    so this drives the guard directly: it derives the write set from the ``write`` tag
    (not a hand-kept list), so a tool that forgot its guard (e.g. dropping ``write=True``
    from ``gitlab_delete_project``) is caught here, not in production.
    """
    args_by_name = {r[0]: r[1] for r in ROWS}
    write_tools = [t for t in await mcp._list_tools() if "write" in t.tags]
    assert write_tools, "no write tools discovered — tag introspection broke"

    ctx = SimpleNamespace(
        lifespan_context={
            "config": GitLabConfig(url="u", token="t", read_only=True),  # noqa: S106
            "client": _NoCallClient(),
        }
    )
    for tool in write_tools:
        result = await tool.fn(ctx, **args_by_name[tool.name])
        assert result.is_error is True, f"{tool.name} did not refuse in read-only mode"
        body = json.loads(result.content[0].text)
        hint = body.get("hint", "").lower()
        assert "read-only" in hint, tool.name
        assert "deployer" in hint, tool.name


async def test_bug_is_a_tool_error_not_a_result(tool_client, caplog):
    """Anything that is not a GitLabError is a bug: isError with the type name, logged with
    its traceback. Before the tool_result decorator this came back as a successful result."""
    client, router = tool_client
    router.get("/projects/123").mock(side_effect=RuntimeError("boom"))

    with caplog.at_level(logging.ERROR, logger="mcp_gitlab.servers.gitlab"):
        result = await client.call_tool(
            "gitlab_get_project", {"project_id": "123"}, raise_on_error=False
        )

    assert result.is_error is True
    assert "RuntimeError: boom" in result.content[0].text
    logged = [r for r in caplog.records if r.name == "mcp_gitlab.servers.gitlab"]
    assert logged and logged[0].exc_info is not None


async def test_api_error_is_an_error_result_with_hint(tool_client):
    """A 404 comes back as an ``isError: true`` result whose text carries the hint and
    which sets no ``structuredContent`` — a strict client (TS SDK) validates
    structuredContent against the outputSchema even when isError, so the error body
    stays in the text content only."""
    client, router = tool_client
    router.get("/projects/123").mock(return_value=Response(404, json={"message": "gone"}))

    result = await client.call_tool(
        "gitlab_get_project", {"project_id": "123"}, raise_on_error=False
    )

    assert result.is_error is True
    body = json.loads(result.content[0].text)
    assert "hint" in body
    assert result.structured_content is None


@pytest.mark.parametrize("row", ROWS, ids=[r[0] for r in ROWS])
async def test_error_result_passes_strict_client(tool_client, row):
    """A strict MCP client (TS SDK) validates ``structuredContent`` against the tool's
    outputSchema even on an ``isError`` result. Every forced failure must therefore either
    carry no structuredContent or carry one that validates — otherwise the client raises
    McpError and the error text + hint are lost. Fails on pre-fix code, where every error
    result set structuredContent to the error dict, which the wrapped schema rejects."""
    import jsonschema

    name, args, method, path, _query, _body = row
    client, router = tool_client
    router.request(method, path).mock(return_value=Response(404, json={"message": "404 Not Found"}))

    schema = {t.name: t.output_schema for t in await client.list_tools()}[name]
    result = await client.call_tool(name, args, raise_on_error=False)

    if result.structured_content is not None and schema is not None:
        jsonschema.validate(result.structured_content, schema)


async def test_no_tool_advertises_a_wrapped_schema(tool_client):
    """X2: no tool may advertise the fastmcp ``{result: string}`` wrapper schema.

    Shape C returns ``ToolResult`` with no ``outputSchema``; a tool may later opt
    into an explicit object schema via ``output_schema=``. Either is fine; the
    ``-> str`` wrapper (``x-fastmcp-wrap-result``) is not. When a schema is present
    its success row's ``structuredContent`` must validate against it.

    Fails on pre-X2 code: every tool returns ``-> str`` and so carries the wrapper.
    """
    client, _router = tool_client
    for t in await client.list_tools():
        schema = t.output_schema
        assert schema is None or (
            "x-fastmcp-wrap-result" not in schema and schema.get("type") == "object"
        ), f"{t.name} still advertises a wrapped/invalid outputSchema: {schema}"


@pytest.mark.parametrize("row", ROWS, ids=[r[0] for r in ROWS])
async def test_schema_validates_structured_content(tool_client, row):
    """Forward-compatible: if a tool advertises an explicit object schema, its
    successful ``structuredContent`` must validate against it."""
    import jsonschema

    name, args, method, path, _query, _body = row
    client, router = tool_client
    payload: list | dict = [] if name.startswith("gitlab_list_") else {}
    router.request(method, path).mock(return_value=Response(200, json=payload))

    schema = {t.name: t.output_schema for t in await client.list_tools()}[name]
    result = await client.call_tool(name, args)
    if schema is not None and result.structured_content is not None:
        jsonschema.validate(result.structured_content, schema)


async def test_success_text_is_byte_identical_pretty_json(tool_client):
    """Golden pin: a success result's text is the pretty, UTF-8 JSON of the object
    (``indent=2, ensure_ascii=False``) — unchanged by the move to ``ToolResult``."""
    client, router = tool_client
    router.get("/projects/123").mock(
        return_value=Response(200, json={"id": 123, "name": "héllo", "path": "g/p"})
    )
    result = await client.call_tool("gitlab_get_project", {"project_id": "123"})
    expected = {"id": 123, "name": "héllo", "path": "g/p"}
    assert result.content[0].text == json.dumps(expected, indent=2, ensure_ascii=False)
    assert result.structured_content == expected


async def test_network_error_is_expected(tool_client, caplog):
    """D1: an unreachable upstream (an ``httpx`` transport error) is an expected failure,
    not a bug. It comes back ``isError: true`` with a ``cannot reach <URL>`` hint, carries
    no ``structuredContent``, and is NOT logged at ERROR with a traceback — a GitLab outage
    or a wrong URL is the caller's to fix, not a server defect to page on."""
    client, router = tool_client
    router.get("/projects/123").mock(side_effect=httpx.ConnectError("name resolution failed"))

    with caplog.at_level(logging.ERROR, logger="mcp_gitlab.servers.gitlab"):
        result = await client.call_tool(
            "gitlab_get_project", {"project_id": "123"}, raise_on_error=False
        )

    assert result.is_error is True
    body = json.loads(result.content[0].text)
    assert "cannot reach" in body["hint"]
    assert result.structured_content is None
    assert not [r for r in caplog.records if r.name == "mcp_gitlab.servers.gitlab"]
