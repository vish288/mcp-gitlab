"""GitLab MCP server — all tool registrations."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import Field

from ..client import GitLabClient
from ..config import GitLabConfig
from ..exceptions import GitLabWriteDisabledError

ACCESS_LEVELS = {
    "guest": 10,
    "reporter": 20,
    "developer": 30,
    "maintainer": 40,
    "owner": 50,
}


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    config = GitLabConfig.from_env()
    config.validate()
    client = GitLabClient(config)
    try:
        yield {"client": client, "config": config}
    finally:
        await client.close()


mcp = FastMCP(
    name="GitLab MCP Server",
    instructions=(
        "Provides tools for interacting with GitLab API"
        " — projects, MRs, pipelines, CI/CD, approvals, and more."
    ),
    lifespan=lifespan,
)


def _get_client(ctx: Context) -> GitLabClient:
    return ctx.request_context.lifespan_context["client"]


def _get_config(ctx: Context) -> GitLabConfig:
    return ctx.request_context.lifespan_context["config"]


def _check_write(ctx: Context) -> None:
    if _get_config(ctx).read_only:
        raise GitLabWriteDisabledError


def _ok(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def _paginated(items: list, total: int | None = None) -> str:
    """Wrap a list response with pagination metadata."""
    return json.dumps(
        {
            "items": items,
            "count": len(items),
            "total": total,
            "has_more": total is not None and len(items) < total,
        },
        indent=2,
        ensure_ascii=False,
    )


def _err(error: Exception) -> str:
    detail: dict[str, Any] = {"error": str(error)}
    from ..exceptions import (
        GitLabApiError,
        GitLabAuthError,
        GitLabNotFoundError,
        GitLabWriteDisabledError,
    )

    if isinstance(error, GitLabNotFoundError):
        detail["status_code"] = error.status_code
        detail["body"] = error.body
        detail["hint"] = "Verify the resource ID/path. Use gitlab_get_project to confirm it exists."
    elif isinstance(error, GitLabAuthError):
        detail["status_code"] = error.status_code
        detail["body"] = error.body
        detail["hint"] = "Check GITLAB_TOKEN permissions. Token needs 'api' scope."
    elif isinstance(error, GitLabWriteDisabledError):
        detail["hint"] = "Server is in read-only mode. Set GITLAB_READ_ONLY=false to enable writes."
    elif isinstance(error, GitLabApiError):
        detail["status_code"] = error.status_code
        detail["body"] = error.body
        if error.status_code == 409:
            detail["hint"] = "Conflict — resource may already exist or be locked."
        elif error.status_code == 422:
            detail["hint"] = "Validation failed — check required fields and formats."
        elif error.status_code == 429:
            detail["hint"] = "Rate limited. Wait before retrying."
    return json.dumps(detail, indent=2, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════════
# Projects
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "projects", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_get_project(
    ctx: Context,
    project_id: Annotated[
        str,
        Field(
            description="Project ID or URL-encoded path (e.g. 'my-group/my-project')", min_length=1
        ),
    ],
) -> str:
    """Get details of a GitLab project."""
    try:
        data = await _get_client(ctx).get_project(project_id)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "projects", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_create_project(
    ctx: Context,
    name: Annotated[str, Field(description="Project name", min_length=1)],
    path: Annotated[str | None, Field(description="Project path/slug")] = None,
    namespace_id: Annotated[int | None, Field(description="Namespace/group ID")] = None,
    description: Annotated[str | None, Field(description="Project description")] = None,
    visibility: Annotated[str | None, Field(description="private, internal, or public")] = None,
    initialize_with_readme: Annotated[bool | None, Field(description="Create with README")] = None,
    default_branch: Annotated[str | None, Field(description="Default branch name")] = None,
) -> str:
    """Create a new GitLab project."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {"name": name}
        if path is not None:
            params["path"] = path
        if namespace_id is not None:
            params["namespace_id"] = namespace_id
        if description is not None:
            params["description"] = description
        if visibility is not None:
            params["visibility"] = visibility
        if initialize_with_readme is not None:
            params["initialize_with_readme"] = initialize_with_readme
        if default_branch is not None:
            params["default_branch"] = default_branch
        data = await _get_client(ctx).create_project(params)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "projects", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_delete_project(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
) -> str:
    """Delete a GitLab project. This action is irreversible."""
    try:
        _check_write(ctx)
        await _get_client(ctx).delete_project(project_id)
        return _ok({"status": "deleted", "project_id": project_id})
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "projects", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_update_project_merge_settings(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    only_allow_merge_if_pipeline_succeeds: Annotated[
        bool | None, Field(description="Require passing pipeline")
    ] = None,
    only_allow_merge_if_all_discussions_are_resolved: Annotated[
        bool | None, Field(description="Require all discussions resolved")
    ] = None,
    remove_source_branch_after_merge: Annotated[
        bool | None, Field(description="Auto-delete source branch")
    ] = None,
    squash_option: Annotated[
        str | None, Field(description="never, always, default_on, or default_off")
    ] = None,
    merge_method: Annotated[str | None, Field(description="merge, rebase_merge, or ff")] = None,
) -> str:
    """Update merge settings for a project."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {}
        if only_allow_merge_if_pipeline_succeeds is not None:
            params["only_allow_merge_if_pipeline_succeeds"] = only_allow_merge_if_pipeline_succeeds
        if only_allow_merge_if_all_discussions_are_resolved is not None:
            params["only_allow_merge_if_all_discussions_are_resolved"] = (
                only_allow_merge_if_all_discussions_are_resolved
            )
        if remove_source_branch_after_merge is not None:
            params["remove_source_branch_after_merge"] = remove_source_branch_after_merge
        if squash_option is not None:
            params["squash_option"] = squash_option
        if merge_method is not None:
            params["merge_method"] = merge_method
        data = await _get_client(ctx).update_project(project_id, params)
        return _ok(data)
    except Exception as e:
        return _err(e)


# ════════════════════════════════════════════════════════════════════
# Project Approvals
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "approvals", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_get_project_approvals(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
) -> str:
    """Get project-level approval configuration."""
    try:
        data = await _get_client(ctx).get_project_approvals(project_id)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "approvals", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_update_project_approvals(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    approvals_before_merge: Annotated[
        int | None, Field(description="Required approvals count")
    ] = None,
    reset_approvals_on_push: Annotated[
        bool | None, Field(description="Reset approvals on new push")
    ] = None,
    disable_overriding_approvers_per_merge_request: Annotated[
        bool | None, Field(description="Disable per-MR approver override")
    ] = None,
    merge_requests_author_approval: Annotated[
        bool | None, Field(description="Allow author self-approval")
    ] = None,
    merge_requests_disable_committers_approval: Annotated[
        bool | None, Field(description="Disable committer approval")
    ] = None,
) -> str:
    """Update project-level approval settings."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {}
        if approvals_before_merge is not None:
            params["approvals_before_merge"] = approvals_before_merge
        if reset_approvals_on_push is not None:
            params["reset_approvals_on_push"] = reset_approvals_on_push
        if disable_overriding_approvers_per_merge_request is not None:
            params["disable_overriding_approvers_per_merge_request"] = (
                disable_overriding_approvers_per_merge_request
            )
        if merge_requests_author_approval is not None:
            params["merge_requests_author_approval"] = merge_requests_author_approval
        if merge_requests_disable_committers_approval is not None:
            params["merge_requests_disable_committers_approval"] = (
                merge_requests_disable_committers_approval
            )
        data = await _get_client(ctx).update_project_approvals(project_id, params)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "approvals", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_list_project_approval_rules(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
) -> str:
    """List project-level approval rules."""
    try:
        data = await _get_client(ctx).list_project_approval_rules(project_id)
        return _paginated(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "approvals", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_create_project_approval_rule(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    name: Annotated[str, Field(description="Rule name", min_length=1)],
    approvals_required: Annotated[int, Field(description="Number of approvals required", ge=0)],
    user_ids: Annotated[list[int] | None, Field(description="User IDs for the rule")] = None,
    group_ids: Annotated[list[int] | None, Field(description="Group IDs for the rule")] = None,
) -> str:
    """Create a project-level approval rule."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {
            "name": name,
            "approvals_required": approvals_required,
        }
        if user_ids:
            params["user_ids"] = user_ids
        if group_ids:
            params["group_ids"] = group_ids
        data = await _get_client(ctx).create_project_approval_rule(project_id, params)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "approvals", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_update_project_approval_rule(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    rule_id: Annotated[int, Field(description="Approval rule ID")],
    name: Annotated[str | None, Field(description="Rule name", min_length=1)] = None,
    approvals_required: Annotated[
        int | None, Field(description="Number of approvals required", ge=0)
    ] = None,
    user_ids: Annotated[list[int] | None, Field(description="User IDs for the rule")] = None,
    group_ids: Annotated[list[int] | None, Field(description="Group IDs for the rule")] = None,
) -> str:
    """Update a project-level approval rule."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {}
        if name is not None:
            params["name"] = name
        if approvals_required is not None:
            params["approvals_required"] = approvals_required
        if user_ids is not None:
            params["user_ids"] = user_ids
        if group_ids is not None:
            params["group_ids"] = group_ids
        data = await _get_client(ctx).update_project_approval_rule(project_id, rule_id, params)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "approvals", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_delete_project_approval_rule(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    rule_id: Annotated[int, Field(description="Approval rule ID")],
) -> str:
    """Delete a project-level approval rule."""
    try:
        _check_write(ctx)
        await _get_client(ctx).delete_project_approval_rule(project_id, rule_id)
        return _ok({"status": "deleted", "rule_id": rule_id})
    except Exception as e:
        return _err(e)


# ════════════════════════════════════════════════════════════════════
# MR Approval Rules
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "approvals", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_list_mr_approval_rules(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
) -> str:
    """List merge request approval rules."""
    try:
        data = await _get_client(ctx).list_mr_approval_rules(project_id, mr_iid)
        return _paginated(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "approvals", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_create_mr_approval_rule(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    name: Annotated[str, Field(description="Rule name", min_length=1)],
    approvals_required: Annotated[int, Field(description="Number of approvals required", ge=0)],
    user_ids: Annotated[list[int] | None, Field(description="User IDs")] = None,
    group_ids: Annotated[list[int] | None, Field(description="Group IDs")] = None,
) -> str:
    """Create a merge request approval rule."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {
            "name": name,
            "approvals_required": approvals_required,
        }
        if user_ids:
            params["user_ids"] = user_ids
        if group_ids:
            params["group_ids"] = group_ids
        data = await _get_client(ctx).create_mr_approval_rule(project_id, mr_iid, params)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "approvals", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_update_mr_approval_rule(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    rule_id: Annotated[int, Field(description="Approval rule ID")],
    name: Annotated[str | None, Field(description="Rule name", min_length=1)] = None,
    approvals_required: Annotated[int | None, Field(description="Approvals required")] = None,
    user_ids: Annotated[list[int] | None, Field(description="User IDs")] = None,
    group_ids: Annotated[list[int] | None, Field(description="Group IDs")] = None,
) -> str:
    """Update a merge request approval rule."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {}
        if name is not None:
            params["name"] = name
        if approvals_required is not None:
            params["approvals_required"] = approvals_required
        if user_ids is not None:
            params["user_ids"] = user_ids
        if group_ids is not None:
            params["group_ids"] = group_ids
        data = await _get_client(ctx).update_mr_approval_rule(project_id, mr_iid, rule_id, params)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "approvals", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_delete_mr_approval_rule(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    rule_id: Annotated[int, Field(description="Approval rule ID")],
) -> str:
    """Delete a merge request approval rule."""
    try:
        _check_write(ctx)
        await _get_client(ctx).delete_mr_approval_rule(project_id, mr_iid, rule_id)
        return _ok({"status": "deleted", "rule_id": rule_id})
    except Exception as e:
        return _err(e)


# ════════════════════════════════════════════════════════════════════
# Groups
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "groups", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_list_groups(
    ctx: Context,
    search: Annotated[str | None, Field(description="Search by name")] = None,
    per_page: Annotated[
        int | None, Field(description="Results per page (1-100)", ge=1, le=100)
    ] = None,
) -> str:
    """List GitLab groups."""
    try:
        params: dict[str, Any] = {}
        if search:
            params["search"] = search
        if per_page:
            params["per_page"] = per_page
        data = await _get_client(ctx).list_groups(params or None)
        return _paginated(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "groups", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_get_group(
    ctx: Context,
    group_id: Annotated[str, Field(description="Group ID or URL-encoded path", min_length=1)],
) -> str:
    """Get details of a GitLab group."""
    try:
        data = await _get_client(ctx).get_group(group_id)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "groups", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_share_project_with_group(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    group_id: Annotated[int, Field(description="Group ID to share with")],
    access_level: Annotated[
        str, Field(description="guest, reporter, developer, maintainer, or owner")
    ],
) -> str:
    """Share a project with a group."""
    try:
        _check_write(ctx)
        level = ACCESS_LEVELS.get(access_level.lower())
        if level is None:
            return _ok(
                {"error": f"Invalid access level: {access_level}. Use: {', '.join(ACCESS_LEVELS)}"}
            )
        await _get_client(ctx).share_project_with_group(project_id, group_id, level)
        return _ok({"status": "shared", "project_id": project_id, "group_id": group_id})
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "groups", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_unshare_project_with_group(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    group_id: Annotated[int, Field(description="Group ID to unshare")],
) -> str:
    """Remove group sharing from a project."""
    try:
        _check_write(ctx)
        await _get_client(ctx).unshare_project_with_group(project_id, group_id)
        return _ok({"status": "unshared", "project_id": project_id, "group_id": group_id})
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "groups", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_share_group_with_group(
    ctx: Context,
    target_group_id: Annotated[str, Field(description="Target group ID or path")],
    source_group_id: Annotated[int, Field(description="Source group ID to share")],
    access_level: Annotated[
        str, Field(description="guest, reporter, developer, maintainer, or owner")
    ],
) -> str:
    """Share a group with another group."""
    try:
        _check_write(ctx)
        level = ACCESS_LEVELS.get(access_level.lower())
        if level is None:
            return _ok({"error": f"Invalid access level: {access_level}"})
        await _get_client(ctx).share_group_with_group(target_group_id, source_group_id, level)
        return _ok({"status": "shared"})
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "groups", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_unshare_group_with_group(
    ctx: Context,
    target_group_id: Annotated[str, Field(description="Target group ID or path")],
    source_group_id: Annotated[int, Field(description="Source group ID to remove")],
) -> str:
    """Remove group sharing between groups."""
    try:
        _check_write(ctx)
        await _get_client(ctx).unshare_group_with_group(target_group_id, source_group_id)
        return _ok({"status": "unshared"})
    except Exception as e:
        return _err(e)


# ════════════════════════════════════════════════════════════════════
# Branches
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "branches", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_list_branches(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    search: Annotated[str | None, Field(description="Filter by branch name")] = None,
    per_page: Annotated[
        int | None, Field(description="Results per page (1-100)", ge=1, le=100)
    ] = None,
) -> str:
    """List repository branches."""
    try:
        params: dict[str, Any] = {}
        if search:
            params["search"] = search
        if per_page:
            params["per_page"] = per_page
        data = await _get_client(ctx).list_branches(project_id, params or None)
        return _paginated(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "branches", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_create_branch(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    branch_name: Annotated[str, Field(description="New branch name", min_length=1)],
    ref: Annotated[str, Field(description="Source branch or commit SHA", min_length=1)],
) -> str:
    """Create a new branch."""
    try:
        _check_write(ctx)
        data = await _get_client(ctx).create_branch(project_id, branch_name, ref)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "branches", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_delete_branch(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    branch_name: Annotated[str, Field(description="Branch name to delete", min_length=1)],
) -> str:
    """Delete a branch."""
    try:
        _check_write(ctx)
        await _get_client(ctx).delete_branch(project_id, branch_name)
        return _ok({"status": "deleted", "branch": branch_name})
    except Exception as e:
        return _err(e)


# ════════════════════════════════════════════════════════════════════
# Commits
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "commits", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_list_commits(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    ref_name: Annotated[str | None, Field(description="Branch or tag name")] = None,
    since: Annotated[str | None, Field(description="ISO 8601 date, commits after")] = None,
    until: Annotated[str | None, Field(description="ISO 8601 date, commits before")] = None,
    path: Annotated[str | None, Field(description="File path filter")] = None,
    per_page: Annotated[
        int | None, Field(description="Results per page (1-100)", ge=1, le=100)
    ] = None,
) -> str:
    """List repository commits."""
    try:
        params: dict[str, Any] = {}
        if ref_name:
            params["ref_name"] = ref_name
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        if path:
            params["path"] = path
        if per_page:
            params["per_page"] = per_page
        data = await _get_client(ctx).list_commits(project_id, params or None)
        return _paginated(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "commits", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_get_commit(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    sha: Annotated[str, Field(description="Commit SHA", min_length=1)],
    include_diff: Annotated[bool, Field(description="Include file diffs")] = False,
) -> str:
    """Get a specific commit, optionally with diff."""
    try:
        client = _get_client(ctx)
        commit = await client.get_commit(project_id, sha)
        if include_diff:
            diff = await client.get_commit_diff(project_id, sha)
            commit["diffs"] = diff
        return _ok(commit)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "commits", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_create_commit(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    branch: Annotated[str, Field(description="Target branch", min_length=1)],
    commit_message: Annotated[str, Field(description="Commit message", min_length=1)],
    actions: Annotated[
        list[dict[str, Any]],
        Field(
            description=(
                "List of file actions: [{action: create|delete|move|update|chmod,"
                " file_path: str, content?: str}]"
            )
        ),
    ],
    start_branch: Annotated[str | None, Field(description="Branch to start from")] = None,
) -> str:
    """Create a commit with multiple file actions."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {
            "branch": branch,
            "commit_message": commit_message,
            "actions": actions,
        }
        if start_branch:
            params["start_branch"] = start_branch
        data = await _get_client(ctx).create_commit(project_id, params)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "commits", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_compare(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    from_ref: Annotated[
        str, Field(description="Source branch/tag/SHA", alias="from", min_length=1)
    ],
    to_ref: Annotated[str, Field(description="Target branch/tag/SHA", alias="to", min_length=1)],
) -> str:
    """Compare two branches, tags, or commits."""
    try:
        data = await _get_client(ctx).compare(project_id, from_ref, to_ref)
        return _ok(data)
    except Exception as e:
        return _err(e)


# ════════════════════════════════════════════════════════════════════
# Merge Requests
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "merge_requests", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_list_mrs(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    state: Annotated[str | None, Field(description="opened, closed, merged, or all")] = None,
    scope: Annotated[str | None, Field(description="created_by_me, assigned_to_me, or all")] = None,
    source_branch: Annotated[str | None, Field(description="Filter by source branch")] = None,
    target_branch: Annotated[str | None, Field(description="Filter by target branch")] = None,
    search: Annotated[str | None, Field(description="Search in title/description")] = None,
    labels: Annotated[str | None, Field(description="Comma-separated labels")] = None,
    per_page: Annotated[
        int | None, Field(description="Results per page (1-100)", ge=1, le=100)
    ] = None,
) -> str:
    """List merge requests for a project."""
    try:
        params: dict[str, Any] = {}
        if state:
            params["state"] = state
        if scope:
            params["scope"] = scope
        if source_branch:
            params["source_branch"] = source_branch
        if target_branch:
            params["target_branch"] = target_branch
        if search:
            params["search"] = search
        if labels:
            params["labels"] = labels
        if per_page:
            params["per_page"] = per_page
        data = await _get_client(ctx).list_merge_requests(project_id, params or None)
        return _paginated(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "merge_requests", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_get_mr(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
) -> str:
    """Get merge request details.

    Returns title, state, source/target branches, author, diff_refs, and merge status.
    """
    try:
        data = await _get_client(ctx).get_merge_request(project_id, mr_iid)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "merge_requests", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_create_mr(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    source_branch: Annotated[str, Field(description="Source branch", min_length=1)],
    target_branch: Annotated[str, Field(description="Target branch", min_length=1)],
    title: Annotated[str, Field(description="MR title", min_length=1)],
    description: Annotated[str | None, Field(description="MR description")] = None,
    draft: Annotated[bool | None, Field(description="Create as draft")] = None,
    squash: Annotated[bool | None, Field(description="Squash commits on merge")] = None,
    remove_source_branch: Annotated[
        bool | None, Field(description="Delete source branch on merge")
    ] = None,
    labels: Annotated[str | None, Field(description="Comma-separated labels")] = None,
) -> str:
    """Create a new merge request."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
        }
        if description is not None:
            params["description"] = description
        if draft is not None:
            params["draft"] = draft
        if squash is not None:
            params["squash"] = squash
        if remove_source_branch is not None:
            params["remove_source_branch"] = remove_source_branch
        if labels is not None:
            params["labels"] = labels
        data = await _get_client(ctx).create_merge_request(project_id, params)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "merge_requests", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_update_mr(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    title: Annotated[str | None, Field(description="New title")] = None,
    description: Annotated[str | None, Field(description="New description")] = None,
    target_branch: Annotated[str | None, Field(description="New target branch")] = None,
    labels: Annotated[str | None, Field(description="Comma-separated labels")] = None,
    squash: Annotated[bool | None, Field(description="Squash commits on merge")] = None,
    remove_source_branch: Annotated[
        bool | None, Field(description="Delete source branch on merge")
    ] = None,
    draft: Annotated[bool | None, Field(description="Set draft status")] = None,
    state_event: Annotated[str | None, Field(description="close or reopen")] = None,
) -> str:
    """Update a merge request."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {}
        if title is not None:
            params["title"] = title
        if description is not None:
            params["description"] = description
        if target_branch is not None:
            params["target_branch"] = target_branch
        if labels is not None:
            params["labels"] = labels
        if squash is not None:
            params["squash"] = squash
        if remove_source_branch is not None:
            params["remove_source_branch"] = remove_source_branch
        if draft is not None:
            params["draft"] = draft
        if state_event is not None:
            params["state_event"] = state_event
        data = await _get_client(ctx).update_merge_request(project_id, mr_iid, params)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "merge_requests", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_merge_mr(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    squash: Annotated[bool | None, Field(description="Squash commits")] = None,
    delete_source_branch: Annotated[
        bool | None, Field(description="Delete source branch after merge")
    ] = None,
    merge_commit_message: Annotated[
        str | None, Field(description="Custom merge commit message")
    ] = None,
    squash_commit_message: Annotated[
        str | None, Field(description="Custom squash commit message")
    ] = None,
    merge_when_pipeline_succeeds: Annotated[
        bool | None, Field(description="Merge when pipeline passes")
    ] = None,
) -> str:
    """Merge a merge request."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {}
        if squash is not None:
            params["squash"] = squash
        if delete_source_branch is not None:
            params["should_remove_source_branch"] = delete_source_branch
        if merge_commit_message is not None:
            params["merge_commit_message"] = merge_commit_message
        if squash_commit_message is not None:
            params["squash_commit_message"] = squash_commit_message
        if merge_when_pipeline_succeeds is not None:
            params["merge_when_pipeline_succeeds"] = merge_when_pipeline_succeeds
        data = await _get_client(ctx).merge_merge_request(project_id, mr_iid, params or None)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "merge_requests", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_merge_mr_sequence(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iids: Annotated[list[int], Field(description="List of MR IIDs to merge in order")],
    squash: Annotated[bool | None, Field(description="Squash commits")] = None,
    delete_source_branch: Annotated[bool | None, Field(description="Delete source branch")] = None,
    merge_when_pipeline_succeeds: Annotated[
        bool | None, Field(description="Merge when pipeline passes")
    ] = None,
    require_mergeable_status: Annotated[
        bool, Field(description="Check mergeable status first")
    ] = True,
) -> str:
    """Merge multiple MRs in sequence. Stops on first failure."""
    try:
        _check_write(ctx)
        client = _get_client(ctx)
        merged: list[int] = []
        params: dict[str, Any] = {}
        if squash is not None:
            params["squash"] = squash
        if delete_source_branch is not None:
            params["should_remove_source_branch"] = delete_source_branch
        if merge_when_pipeline_succeeds is not None:
            params["merge_when_pipeline_succeeds"] = merge_when_pipeline_succeeds

        for iid in mr_iids:
            if require_mergeable_status:
                mr = await client.get_merge_request(project_id, iid)
                status = mr.get("detailed_merge_status", mr.get("merge_status", ""))
                if status not in ("mergeable", "can_be_merged"):
                    return _ok(
                        {
                            "error": f"MR !{iid} is not mergeable (status: {status})",
                            "merged_so_far": merged,
                        }
                    )
            await client.merge_merge_request(project_id, iid, params or None)
            merged.append(iid)

        return _ok({"status": "all_merged", "merged": merged})
    except Exception as e:
        detail: dict[str, Any] = {"error": str(e), "merged_so_far": merged}
        from ..exceptions import GitLabApiError

        if isinstance(e, GitLabApiError):
            detail["status_code"] = e.status_code
            detail["body"] = e.body
        return json.dumps(detail, indent=2, ensure_ascii=False)


@mcp.tool(
    tags={"gitlab", "merge_requests", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_rebase_mr(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    skip_ci: Annotated[bool, Field(description="Skip CI pipeline for rebase")] = False,
) -> str:
    """Rebase a merge request."""
    try:
        _check_write(ctx)
        data = await _get_client(ctx).rebase_merge_request(project_id, mr_iid, skip_ci)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "merge_requests", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_mr_changes(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
) -> str:
    """Get file changes of a merge request. Returns list of diffs with old/new paths and content."""
    try:
        data = await _get_client(ctx).get_merge_request_changes(project_id, mr_iid)
        return _ok(data)
    except Exception as e:
        return _err(e)


# ════════════════════════════════════════════════════════════════════
# MR Notes
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "notes", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_list_mr_notes(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    include_system: Annotated[bool, Field(description="Include system-generated notes")] = False,
) -> str:
    """List notes (comments) on a merge request."""
    try:
        data = await _get_client(ctx).list_mr_notes(project_id, mr_iid)
        if not include_system:
            data = [n for n in data if not n.get("system", False)]
        return _paginated(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "notes", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_add_mr_note(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    body: Annotated[str, Field(description="Comment body (markdown)", min_length=1)],
    internal: Annotated[
        bool, Field(description="Internal note (not visible to non-members)")
    ] = False,
) -> str:
    """Add a note (comment) to a merge request."""
    try:
        _check_write(ctx)
        data = await _get_client(ctx).add_mr_note(project_id, mr_iid, body, internal)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "notes", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_delete_mr_note(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    note_id: Annotated[int, Field(description="Note ID to delete")],
) -> str:
    """Delete a note from a merge request."""
    try:
        _check_write(ctx)
        await _get_client(ctx).delete_mr_note(project_id, mr_iid, note_id)
        return _ok({"status": "deleted", "note_id": note_id})
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "notes", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_update_mr_note(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    note_id: Annotated[int, Field(description="Note ID to update")],
    body: Annotated[str, Field(description="New note body", min_length=1)],
) -> str:
    """Update a note on a merge request."""
    try:
        _check_write(ctx)
        data = await _get_client(ctx).update_mr_note(project_id, mr_iid, note_id, body)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "notes", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_award_emoji(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    note_id: Annotated[int, Field(description="Note ID")],
    emoji: Annotated[str, Field(description="Emoji name (e.g. thumbsup, 100, eyes)", min_length=1)],
) -> str:
    """Award an emoji reaction to a note."""
    try:
        _check_write(ctx)
        data = await _get_client(ctx).award_emoji(project_id, mr_iid, note_id, emoji)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "notes", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_remove_emoji(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    note_id: Annotated[int, Field(description="Note ID")],
    award_id: Annotated[int, Field(description="Award emoji ID to remove")],
) -> str:
    """Remove an emoji reaction from a note."""
    try:
        _check_write(ctx)
        await _get_client(ctx).delete_award_emoji(project_id, mr_iid, note_id, award_id)
        return _ok({"status": "removed", "award_id": award_id})
    except Exception as e:
        return _err(e)


# ════════════════════════════════════════════════════════════════════
# MR Discussions
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "discussions", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_list_mr_discussions(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
) -> str:
    """List discussions on a merge request.

    Returns discussion threads with notes, excluding system notes.
    """
    try:
        data = await _get_client(ctx).list_mr_discussions(project_id, mr_iid)
        # Filter out system-only discussions
        filtered = []
        for d in data:
            notes = d.get("notes", [])
            if any(not n.get("system", False) for n in notes):
                filtered.append(d)
        return _paginated(filtered)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "discussions", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_create_mr_discussion(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    body: Annotated[str, Field(description="Discussion body (markdown)", min_length=1)],
    base_sha: Annotated[str | None, Field(description="Base commit SHA (from diff_refs)")] = None,
    head_sha: Annotated[str | None, Field(description="Head commit SHA (from diff_refs)")] = None,
    start_sha: Annotated[str | None, Field(description="Start commit SHA (from diff_refs)")] = None,
    new_path: Annotated[str | None, Field(description="File path for inline comment")] = None,
    old_path: Annotated[str | None, Field(description="Old file path (for renames)")] = None,
    new_line: Annotated[int | None, Field(description="Line number in new file")] = None,
    old_line: Annotated[int | None, Field(description="Line number in old file")] = None,
    line_range_start_line: Annotated[
        int | None, Field(description="Multi-line range start")
    ] = None,
    line_range_end_line: Annotated[int | None, Field(description="Multi-line range end")] = None,
    line_range_type: Annotated[
        str | None, Field(description="'new' or 'old' for line range")
    ] = None,
) -> str:
    """Create a discussion on a merge request.

    For inline comments, provide diff_refs and line info.
    """
    try:
        _check_write(ctx)
        params: dict[str, Any] = {"body": body}

        # Build position for inline comments
        if base_sha and head_sha and start_sha and new_path:
            position: dict[str, Any] = {
                "base_sha": base_sha,
                "start_sha": start_sha,
                "head_sha": head_sha,
                "position_type": "text",
                "new_path": new_path,
                "old_path": old_path or new_path,
            }
            if new_line is not None:
                position["new_line"] = new_line
            if old_line is not None:
                position["old_line"] = old_line

            # Multi-line range
            if line_range_start_line is not None and line_range_end_line is not None:
                range_type = line_range_type or "new"
                line_key = "new_line" if range_type == "new" else "old_line"
                position["line_range"] = {
                    "start": {"type": range_type, line_key: line_range_start_line},
                    "end": {"type": range_type, line_key: line_range_end_line},
                }

            params["position"] = position

        data = await _get_client(ctx).create_mr_discussion(project_id, mr_iid, params)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "discussions", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_reply_to_discussion(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    discussion_id: Annotated[str, Field(description="Discussion ID", min_length=1)],
    body: Annotated[str, Field(description="Reply body (markdown)", min_length=1)],
) -> str:
    """Reply to an existing discussion."""
    try:
        _check_write(ctx)
        data = await _get_client(ctx).reply_to_discussion(project_id, mr_iid, discussion_id, body)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "discussions", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_resolve_discussion(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    discussion_id: Annotated[str, Field(description="Discussion ID", min_length=1)],
    resolved: Annotated[bool, Field(description="True to resolve, False to unresolve")],
) -> str:
    """Resolve or unresolve a discussion."""
    try:
        _check_write(ctx)
        data = await _get_client(ctx).resolve_discussion(
            project_id, mr_iid, discussion_id, resolved
        )
        return _ok(data)
    except Exception as e:
        return _err(e)


# ════════════════════════════════════════════════════════════════════
# Pipelines
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "pipelines", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_list_pipelines(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    ref: Annotated[str | None, Field(description="Filter by branch/tag")] = None,
    status: Annotated[
        str | None,
        Field(description="Filter by status (running, pending, success, failed, etc.)"),
    ] = None,
    source: Annotated[
        str | None, Field(description="Filter by source (push, web, trigger, etc.)")
    ] = None,
    per_page: Annotated[
        int | None, Field(description="Results per page (1-100)", ge=1, le=100)
    ] = None,
) -> str:
    """List pipelines for a project. Returns id, status, ref, source, created_at."""
    try:
        params: dict[str, Any] = {}
        if ref:
            params["ref"] = ref
        if status:
            params["status"] = status
        if source:
            params["source"] = source
        if per_page:
            params["per_page"] = per_page
        data = await _get_client(ctx).list_pipelines(project_id, params or None)
        return _paginated(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "pipelines", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_get_pipeline(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    pipeline_id: Annotated[int, Field(description="Pipeline ID")],
    include_jobs: Annotated[bool, Field(description="Include pipeline jobs")] = False,
) -> str:
    """Get pipeline details, optionally with jobs."""
    try:
        client = _get_client(ctx)
        pipeline = await client.get_pipeline(project_id, pipeline_id)
        if include_jobs:
            jobs = await client.list_pipeline_jobs(project_id, pipeline_id)
            pipeline["jobs"] = jobs
        return _ok(pipeline)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "pipelines", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_create_pipeline(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    ref: Annotated[str, Field(description="Branch or tag to run pipeline on", min_length=1)],
    variables: Annotated[
        list[dict[str, str]] | None,
        Field(description="Pipeline variables: [{key: str, value: str, variable_type?: str}]"),
    ] = None,
) -> str:
    """Create (trigger) a new pipeline."""
    try:
        _check_write(ctx)
        data = await _get_client(ctx).create_pipeline(project_id, ref, variables)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "pipelines", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_retry_pipeline(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    pipeline_id: Annotated[int, Field(description="Pipeline ID")],
) -> str:
    """Retry all failed jobs in a pipeline."""
    try:
        _check_write(ctx)
        data = await _get_client(ctx).retry_pipeline(project_id, pipeline_id)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "pipelines", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_cancel_pipeline(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    pipeline_id: Annotated[int, Field(description="Pipeline ID")],
) -> str:
    """Cancel a running pipeline."""
    try:
        _check_write(ctx)
        data = await _get_client(ctx).cancel_pipeline(project_id, pipeline_id)
        return _ok(data)
    except Exception as e:
        return _err(e)


# ════════════════════════════════════════════════════════════════════
# Jobs
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "jobs", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_retry_job(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    job_id: Annotated[int, Field(description="Job ID")],
) -> str:
    """Retry a failed job."""
    try:
        _check_write(ctx)
        data = await _get_client(ctx).retry_job(project_id, job_id)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "jobs", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_play_job(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    job_id: Annotated[int, Field(description="Job ID")],
    variables: Annotated[
        list[dict[str, str]] | None,
        Field(description="Job variables: [{key: str, value: str}]"),
    ] = None,
) -> str:
    """Trigger a manual job."""
    try:
        _check_write(ctx)
        data = await _get_client(ctx).play_job(project_id, job_id, variables)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "jobs", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_cancel_job(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    job_id: Annotated[int, Field(description="Job ID")],
) -> str:
    """Cancel a running job."""
    try:
        _check_write(ctx)
        data = await _get_client(ctx).cancel_job(project_id, job_id)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "jobs", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_get_job_log(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    job_id: Annotated[int, Field(description="Job ID")],
    tail_lines: Annotated[int, Field(description="Number of lines from the end to return")] = 200,
) -> str:
    """Get the log (trace) output of a job."""
    try:
        log_text = await _get_client(ctx).get_job_log(project_id, job_id)
        lines = log_text.splitlines()
        if tail_lines and len(lines) > tail_lines:
            lines = lines[-tail_lines:]
        return _ok(
            {
                "log": "\n".join(lines),
                "total_lines": len(log_text.splitlines()),
                "shown_lines": len(lines),
            }
        )
    except Exception as e:
        return _err(e)


# ════════════════════════════════════════════════════════════════════
# Tags
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "tags", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_list_tags(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    search: Annotated[str | None, Field(description="Filter by tag name")] = None,
    order_by: Annotated[str | None, Field(description="name, updated, or version")] = None,
    sort: Annotated[str | None, Field(description="asc or desc")] = None,
    per_page: Annotated[
        int | None, Field(description="Results per page (1-100)", ge=1, le=100)
    ] = None,
) -> str:
    """List repository tags."""
    try:
        params: dict[str, Any] = {}
        if search:
            params["search"] = search
        if order_by:
            params["order_by"] = order_by
        if sort:
            params["sort"] = sort
        if per_page:
            params["per_page"] = per_page
        data = await _get_client(ctx).list_tags(project_id, params or None)
        return _paginated(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "tags", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_get_tag(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    tag_name: Annotated[str, Field(description="Tag name", min_length=1)],
) -> str:
    """Get details of a specific tag."""
    try:
        data = await _get_client(ctx).get_tag(project_id, tag_name)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "tags", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_create_tag(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    tag_name: Annotated[str, Field(description="Tag name", min_length=1)],
    ref: Annotated[str, Field(description="Branch or commit SHA to tag", min_length=1)],
    message: Annotated[str | None, Field(description="Annotated tag message")] = None,
) -> str:
    """Create a new tag."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {"tag_name": tag_name, "ref": ref}
        if message:
            params["message"] = message
        data = await _get_client(ctx).create_tag(project_id, params)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "tags", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_delete_tag(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    tag_name: Annotated[str, Field(description="Tag name to delete", min_length=1)],
) -> str:
    """Delete a tag."""
    try:
        _check_write(ctx)
        await _get_client(ctx).delete_tag(project_id, tag_name)
        return _ok({"status": "deleted", "tag": tag_name})
    except Exception as e:
        return _err(e)


# ════════════════════════════════════════════════════════════════════
# Releases
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "releases", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_list_releases(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    per_page: Annotated[
        int | None, Field(description="Results per page (1-100)", ge=1, le=100)
    ] = None,
) -> str:
    """List project releases."""
    try:
        params: dict[str, Any] = {}
        if per_page:
            params["per_page"] = per_page
        data = await _get_client(ctx).list_releases(project_id, params or None)
        return _paginated(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "releases", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_get_release(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    tag_name: Annotated[str, Field(description="Tag name of the release", min_length=1)],
) -> str:
    """Get details of a specific release."""
    try:
        data = await _get_client(ctx).get_release(project_id, tag_name)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "releases", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_create_release(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    tag_name: Annotated[str, Field(description="Tag name for the release", min_length=1)],
    name: Annotated[str | None, Field(description="Release name")] = None,
    description: Annotated[str | None, Field(description="Release description (markdown)")] = None,
    ref: Annotated[str | None, Field(description="Branch/commit if tag doesn't exist yet")] = None,
    released_at: Annotated[str | None, Field(description="ISO 8601 release date")] = None,
    links: Annotated[
        list[dict[str, str]] | None,
        Field(description="Asset links: [{name, url, link_type?}]"),
    ] = None,
) -> str:
    """Create a new release."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {"tag_name": tag_name}
        if name is not None:
            params["name"] = name
        if description is not None:
            params["description"] = description
        if ref is not None:
            params["ref"] = ref
        if released_at is not None:
            params["released_at"] = released_at
        if links is not None:
            params["assets"] = {"links": links}
        data = await _get_client(ctx).create_release(project_id, params)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "releases", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_update_release(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    tag_name: Annotated[str, Field(description="Tag name of the release", min_length=1)],
    name: Annotated[str | None, Field(description="New release name")] = None,
    description: Annotated[str | None, Field(description="New release description")] = None,
    released_at: Annotated[str | None, Field(description="New release date (ISO 8601)")] = None,
) -> str:
    """Update an existing release."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {}
        if name is not None:
            params["name"] = name
        if description is not None:
            params["description"] = description
        if released_at is not None:
            params["released_at"] = released_at
        data = await _get_client(ctx).update_release(project_id, tag_name, params)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "releases", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_delete_release(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    tag_name: Annotated[str, Field(description="Tag name of the release", min_length=1)],
) -> str:
    """Delete a release (does not delete the tag)."""
    try:
        _check_write(ctx)
        await _get_client(ctx).delete_release(project_id, tag_name)
        return _ok({"status": "deleted", "tag_name": tag_name})
    except Exception as e:
        return _err(e)


# ════════════════════════════════════════════════════════════════════
# CI/CD Variables (Project)
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "variables", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_list_variables(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
) -> str:
    """List project CI/CD variables. Masked values shown as '***MASKED***'."""
    try:
        data = await _get_client(ctx).list_variables(project_id)
        for var in data:
            if var.get("masked"):
                var["value"] = "***MASKED***"
        return _paginated(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "variables", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_create_variable(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    key: Annotated[str, Field(description="Variable key", min_length=1)],
    value: Annotated[str, Field(description="Variable value")],
    variable_type: Annotated[str | None, Field(description="env_var or file")] = None,
    protected: Annotated[
        bool | None, Field(description="Only available on protected branches")
    ] = None,
    masked: Annotated[bool | None, Field(description="Mask in job logs")] = None,
    raw: Annotated[bool | None, Field(description="Do not expand variable references")] = None,
    environment_scope: Annotated[
        str | None, Field(description="Environment scope (default: *)")
    ] = None,
    description: Annotated[str | None, Field(description="Variable description")] = None,
) -> str:
    """Create a project CI/CD variable."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {"key": key, "value": value}
        if variable_type is not None:
            params["variable_type"] = variable_type
        if protected is not None:
            params["protected"] = protected
        if masked is not None:
            params["masked"] = masked
        if raw is not None:
            params["raw"] = raw
        if environment_scope is not None:
            params["environment_scope"] = environment_scope
        if description is not None:
            params["description"] = description
        data = await _get_client(ctx).create_variable(project_id, params)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "variables", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_update_variable(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    key: Annotated[str, Field(description="Variable key", min_length=1)],
    value: Annotated[str, Field(description="New variable value")],
    variable_type: Annotated[str | None, Field(description="env_var or file")] = None,
    protected: Annotated[bool | None, Field(description="Protected branches only")] = None,
    masked: Annotated[bool | None, Field(description="Mask in logs")] = None,
    raw: Annotated[bool | None, Field(description="Do not expand references")] = None,
    environment_scope: Annotated[str | None, Field(description="Environment scope")] = None,
    description: Annotated[str | None, Field(description="Variable description")] = None,
) -> str:
    """Update a project CI/CD variable."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {"value": value}
        if variable_type is not None:
            params["variable_type"] = variable_type
        if protected is not None:
            params["protected"] = protected
        if masked is not None:
            params["masked"] = masked
        if raw is not None:
            params["raw"] = raw
        if description is not None:
            params["description"] = description
        data = await _get_client(ctx).update_variable(
            project_id, key, params, environment_scope=environment_scope
        )
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "variables", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_delete_variable(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    key: Annotated[str, Field(description="Variable key", min_length=1)],
    environment_scope: Annotated[str | None, Field(description="Environment scope filter")] = None,
) -> str:
    """Delete a project CI/CD variable."""
    try:
        _check_write(ctx)
        await _get_client(ctx).delete_variable(project_id, key, environment_scope)
        return _ok({"status": "deleted", "key": key})
    except Exception as e:
        return _err(e)


# ════════════════════════════════════════════════════════════════════
# CI/CD Variables (Group)
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "variables", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_list_group_variables(
    ctx: Context,
    group_id: Annotated[str, Field(description="Group ID or path", min_length=1)],
) -> str:
    """List group CI/CD variables. Masked values shown as '***MASKED***'."""
    try:
        data = await _get_client(ctx).list_group_variables(group_id)
        for var in data:
            if var.get("masked"):
                var["value"] = "***MASKED***"
        return _paginated(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "variables", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_create_group_variable(
    ctx: Context,
    group_id: Annotated[str, Field(description="Group ID or path", min_length=1)],
    key: Annotated[str, Field(description="Variable key", min_length=1)],
    value: Annotated[str, Field(description="Variable value")],
    variable_type: Annotated[str | None, Field(description="env_var or file")] = None,
    protected: Annotated[bool | None, Field(description="Protected branches only")] = None,
    masked: Annotated[bool | None, Field(description="Mask in logs")] = None,
    raw: Annotated[bool | None, Field(description="Do not expand references")] = None,
    environment_scope: Annotated[str | None, Field(description="Environment scope")] = None,
    description: Annotated[str | None, Field(description="Variable description")] = None,
) -> str:
    """Create a group CI/CD variable."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {"key": key, "value": value}
        if variable_type is not None:
            params["variable_type"] = variable_type
        if protected is not None:
            params["protected"] = protected
        if masked is not None:
            params["masked"] = masked
        if raw is not None:
            params["raw"] = raw
        if environment_scope is not None:
            params["environment_scope"] = environment_scope
        if description is not None:
            params["description"] = description
        data = await _get_client(ctx).create_group_variable(group_id, params)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "variables", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_update_group_variable(
    ctx: Context,
    group_id: Annotated[str, Field(description="Group ID or path", min_length=1)],
    key: Annotated[str, Field(description="Variable key", min_length=1)],
    value: Annotated[str, Field(description="New variable value")],
    variable_type: Annotated[str | None, Field(description="env_var or file")] = None,
    protected: Annotated[bool | None, Field(description="Protected branches only")] = None,
    masked: Annotated[bool | None, Field(description="Mask in logs")] = None,
    raw: Annotated[bool | None, Field(description="Do not expand references")] = None,
    description: Annotated[str | None, Field(description="Variable description")] = None,
) -> str:
    """Update a group CI/CD variable."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {"value": value}
        if variable_type is not None:
            params["variable_type"] = variable_type
        if protected is not None:
            params["protected"] = protected
        if masked is not None:
            params["masked"] = masked
        if raw is not None:
            params["raw"] = raw
        if description is not None:
            params["description"] = description
        data = await _get_client(ctx).update_group_variable(group_id, key, params)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "variables", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_delete_group_variable(
    ctx: Context,
    group_id: Annotated[str, Field(description="Group ID or path", min_length=1)],
    key: Annotated[str, Field(description="Variable key", min_length=1)],
) -> str:
    """Delete a group CI/CD variable."""
    try:
        _check_write(ctx)
        await _get_client(ctx).delete_group_variable(group_id, key)
        return _ok({"status": "deleted", "key": key})
    except Exception as e:
        return _err(e)


# ════════════════════════════════════════════════════════════════════
# Issues
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "issues", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_list_issues(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    state: Annotated[str | None, Field(description="opened, closed, or all")] = None,
    labels: Annotated[str | None, Field(description="Comma-separated labels")] = None,
    search: Annotated[str | None, Field(description="Search in title/description")] = None,
    assignee_id: Annotated[int | None, Field(description="Filter by assignee ID")] = None,
    per_page: Annotated[
        int | None, Field(description="Results per page (1-100)", ge=1, le=100)
    ] = None,
) -> str:
    """List issues for a project."""
    try:
        params: dict[str, Any] = {}
        if state:
            params["state"] = state
        if labels:
            params["labels"] = labels
        if search:
            params["search"] = search
        if assignee_id:
            params["assignee_id"] = assignee_id
        if per_page:
            params["per_page"] = per_page
        data = await _get_client(ctx).list_issues(project_id, params or None)
        return _paginated(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "issues", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_get_issue(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    issue_iid: Annotated[int, Field(description="Issue IID")],
) -> str:
    """Get details of a specific issue."""
    try:
        data = await _get_client(ctx).get_issue(project_id, issue_iid)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "issues", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_create_issue(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    title: Annotated[str, Field(description="Issue title", min_length=1)],
    description: Annotated[str | None, Field(description="Issue description (markdown)")] = None,
    labels: Annotated[str | None, Field(description="Comma-separated labels")] = None,
    assignee_ids: Annotated[list[int] | None, Field(description="Assignee user IDs")] = None,
    milestone_id: Annotated[int | None, Field(description="Milestone ID")] = None,
    confidential: Annotated[bool | None, Field(description="Mark as confidential")] = None,
    weight: Annotated[int | None, Field(description="Issue weight")] = None,
) -> str:
    """Create a new issue."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {"title": title}
        if description is not None:
            params["description"] = description
        if labels is not None:
            params["labels"] = labels
        if assignee_ids is not None:
            params["assignee_ids"] = assignee_ids
        if milestone_id is not None:
            params["milestone_id"] = milestone_id
        if confidential is not None:
            params["confidential"] = confidential
        if weight is not None:
            params["weight"] = weight
        data = await _get_client(ctx).create_issue(project_id, params)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "issues", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def gitlab_update_issue(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    issue_iid: Annotated[int, Field(description="Issue IID")],
    title: Annotated[str | None, Field(description="New title")] = None,
    description: Annotated[str | None, Field(description="New description")] = None,
    labels: Annotated[str | None, Field(description="Comma-separated labels")] = None,
    assignee_ids: Annotated[list[int] | None, Field(description="Assignee user IDs")] = None,
    state_event: Annotated[str | None, Field(description="close or reopen")] = None,
    weight: Annotated[int | None, Field(description="Issue weight")] = None,
) -> str:
    """Update an existing issue."""
    try:
        _check_write(ctx)
        params: dict[str, Any] = {}
        if title is not None:
            params["title"] = title
        if description is not None:
            params["description"] = description
        if labels is not None:
            params["labels"] = labels
        if assignee_ids is not None:
            params["assignee_ids"] = assignee_ids
        if state_event is not None:
            params["state_event"] = state_event
        if weight is not None:
            params["weight"] = weight
        data = await _get_client(ctx).update_issue(project_id, issue_iid, params)
        return _ok(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    tags={"gitlab", "issues", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
async def gitlab_add_issue_comment(
    ctx: Context,
    project_id: Annotated[str, Field(description="Project ID or path", min_length=1)],
    issue_iid: Annotated[int, Field(description="Issue IID")],
    body: Annotated[str, Field(description="Comment body (markdown)", min_length=1)],
) -> str:
    """Add a comment to an issue."""
    try:
        _check_write(ctx)
        data = await _get_client(ctx).add_issue_comment(project_id, issue_iid, body)
        return _ok(data)
    except Exception as e:
        return _err(e)
