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

import pytest
from httpx import Response

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
    ("gitlab_mr_changes", {"project_id": "123", "mr_iid": 1}, "GET", f"{MR}/changes", {}, None),
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

    parsed = _parse(await client.call_tool(name, args))

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

    parsed = _parse(await client.call_tool(name, args))

    assert NOT_FOUND_KEYS <= parsed.keys()
    assert parsed["status_code"] == 404


async def test_every_tool_has_a_row(tool_client):
    client, _router = tool_client
    assert {r[0] for r in ROWS} == {t.name for t in await client.list_tools()}
