"""GitLab MCP server — all tool registrations."""

from __future__ import annotations

import functools
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from ..client import GitLabClient
from ..config import GitLabConfig
from ..exceptions import (
    GitLabApiError,
    GitLabAuthError,
    GitLabError,
    GitLabNotFoundError,
    GitLabWriteDisabledError,
)

_log = logging.getLogger(__name__)

ACCESS_LEVELS = {
    "guest": 10,
    "reporter": 20,
    "developer": 30,
    "maintainer": 40,
    "owner": 50,
}

# The schema rejects anything outside the five names, so the tools no longer
# validate this by hand and return the rejection as a successful result.
AccessLevel = Annotated[
    Literal["guest", "reporter", "developer", "maintainer", "owner"],
    Field(description="Access level to grant"),
]

ProjectId = Annotated[str, Field(description="Project ID, path, or full GitLab URL", min_length=1)]

PerPage = Annotated[int | None, Field(description="Results per page (1-100)", ge=1, le=100)]


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    config = GitLabConfig.from_env()
    config.validate()
    pkg_version = version("mcp-gitlab")
    _log.info("mcp-gitlab %s starting", pkg_version)
    _log.info("GitLab: %s (read-only: %s)", config.url, config.read_only)
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


# Encode a project/group id (numeric, path, or full URL) for a path segment.
_enc = GitLabClient._encode_id


def _get_config(ctx: Context) -> GitLabConfig:
    return ctx.request_context.lifespan_context["config"]


def _check_write(ctx: Context) -> None:
    if _get_config(ctx).read_only:
        raise GitLabWriteDisabledError


def _ok(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def _paginated(items: list, next_page: int | None = None) -> str:
    """Wrap a list response with its real pagination state.

    ``count`` is the size of *this* page, never a grand total. ``next_page``
    comes from GitLab's X-Next-Page header and is None on the last page.

    Previously this returned only items and a count while the docstring claimed
    to carry pagination metadata: the headers were discarded in the client, so a
    capped list was indistinguishable from a complete one and there was no way
    to request the rest.
    """
    return json.dumps(
        {
            "items": items,
            "count": len(items),
            "has_more": next_page is not None,
            "next_page": next_page,
        },
        indent=2,
        ensure_ascii=False,
    )


_PIPELINE_KEYS = (
    "id",
    "iid",
    "status",
    "ref",
    "sha",
    "source",
    "created_at",
    "updated_at",
    "started_at",
    "finished_at",
    "duration",
    "queued_duration",
    "failure_reason",
    "web_url",
    "name",
)

_JOB_KEYS = (
    "id",
    "name",
    "stage",
    "status",
    "ref",
    "created_at",
    "started_at",
    "finished_at",
    "duration",
    "queued_duration",
    "allow_failure",
    "failure_reason",
    "web_url",
    "when",
)


def _slim(d: dict, keys: tuple) -> dict:
    return {k: d[k] for k in keys if k in d}


def _err(error: Exception) -> str:
    detail: dict[str, Any] = {"error": str(error)}
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


def _params(**kw: Any) -> dict[str, Any]:
    """Request params from tool arguments, with unset (None) ones dropped."""
    return {k: v for k, v in kw.items() if v is not None}


def _variable_params(
    value: str | None = None,
    variable_type: str | None = None,
    protected: bool | None = None,
    masked: bool | None = None,
    raw: bool | None = None,
    environment_scope: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Build CI/CD variable request params from optional parameters."""
    return _params(
        value=value,
        variable_type=variable_type,
        protected=protected,
        masked=masked,
        raw=raw,
        environment_scope=environment_scope,
        description=description,
    )


_Tool = Callable[..., Awaitable[str]]


def tool_result(fn: _Tool | None = None, *, write: bool = False) -> Any:
    """Apply under ``@mcp.tool``. Expected failures become the JSON envelope;
    anything else is a bug and is raised as a tool error.

    ``GitLabError`` covers what the API can legitimately answer (401/403/404,
    409/422/429, read-only). Every other exception used to be caught by the
    same ``except Exception`` and returned as a successful result with no log
    line, so a ``KeyError`` in a tool body looked like a 404 to the caller.
    Now it is logged with its traceback and surfaces as ``isError: true``.

    ``write=True`` runs the read-only guard first; its failure is expected and
    takes the envelope path like any other ``GitLabError``.
    """

    def wrap(f: _Tool) -> _Tool:
        @functools.wraps(f)
        async def inner(ctx: Context, *args: Any, **kwargs: Any) -> str:
            try:
                if write:
                    _check_write(ctx)
                return await f(ctx, *args, **kwargs)
            except GitLabError as e:
                return _err(e)
            except Exception as e:
                _log.exception("%s failed", f.__name__)
                msg = f"{type(e).__name__}: {e}"
                raise ToolError(msg) from e

        return inner

    return wrap(fn) if fn is not None else wrap


# ════════════════════════════════════════════════════════════════════
# Projects
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "projects", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_get_project(
    ctx: Context,
    project_id: Annotated[
        str,
        Field(
            description=(
                "Project ID, URL-encoded path (e.g. 'my-group/my-project'), or a full GitLab URL"
            ),
            min_length=1,
        ),
    ],
) -> str:
    """Get a project's details.

    Returns id, name, path_with_namespace, visibility, default_branch, web_url, description.
    """
    return _ok(await _get_client(ctx).get(f"/projects/{_enc(project_id)}"))


@mcp.tool(
    tags={"gitlab", "projects", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
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
    """Create a new project.

    Returns the new project's id, name, path_with_namespace, web_url, and default settings.
    """
    return _ok(
        await _get_client(ctx).post(
            "/projects",
            _params(
                name=name,
                path=path,
                namespace_id=namespace_id,
                description=description,
                visibility=visibility,
                initialize_with_readme=initialize_with_readme,
                default_branch=default_branch,
            ),
        )
    )


@mcp.tool(
    tags={"gitlab", "projects", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_delete_project(
    ctx: Context,
    project_id: ProjectId,
) -> str:
    """Permanently delete a project. Irreversible.

    Returns a {status: deleted, project_id} confirmation.
    """
    await _get_client(ctx).delete(f"/projects/{_enc(project_id)}")
    return _ok({"status": "deleted", "project_id": project_id})


@mcp.tool(
    tags={"gitlab", "projects", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_update_project_merge_settings(
    ctx: Context,
    project_id: ProjectId,
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
    """Update merge-related project settings (squash, fast-forward, pipeline gating).

    Returns the updated project object.
    """
    return _ok(
        await _get_client(ctx).put(
            f"/projects/{_enc(project_id)}",
            _params(
                only_allow_merge_if_pipeline_succeeds=only_allow_merge_if_pipeline_succeeds,
                only_allow_merge_if_all_discussions_are_resolved=only_allow_merge_if_all_discussions_are_resolved,
                remove_source_branch_after_merge=remove_source_branch_after_merge,
                squash_option=squash_option,
                merge_method=merge_method,
            ),
        )
    )


# ════════════════════════════════════════════════════════════════════
# Project Approvals
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "approvals", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_get_project_approvals(
    ctx: Context,
    project_id: ProjectId,
) -> str:
    """Get project-level approval configuration.

    Returns approvals_before_merge, reset_approvals_on_push, and self-approval rules.
    """
    return _ok(await _get_client(ctx).get(f"/projects/{_enc(project_id)}/approvals"))


@mcp.tool(
    tags={"gitlab", "approvals", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_update_project_approvals(
    ctx: Context,
    project_id: ProjectId,
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
    """Update project-level approval settings. Returns the updated approval configuration."""
    return _ok(
        await _get_client(ctx).post(
            f"/projects/{_enc(project_id)}/approvals",
            _params(
                approvals_before_merge=approvals_before_merge,
                reset_approvals_on_push=reset_approvals_on_push,
                disable_overriding_approvers_per_merge_request=disable_overriding_approvers_per_merge_request,
                merge_requests_author_approval=merge_requests_author_approval,
                merge_requests_disable_committers_approval=merge_requests_disable_committers_approval,
            ),
        )
    )


@mcp.tool(
    tags={"gitlab", "approvals", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_list_project_approval_rules(
    ctx: Context,
    project_id: ProjectId,
) -> str:
    """List project-level approval rules.

    Returns rules with id, name, approvals_required, and eligible approvers/groups.
    """
    data = await _get_client(ctx).get(f"/projects/{_enc(project_id)}/approval_rules")
    return _paginated(data)


@mcp.tool(
    tags={"gitlab", "approvals", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_create_project_approval_rule(
    ctx: Context,
    project_id: ProjectId,
    name: Annotated[str, Field(description="Rule name", min_length=1)],
    approvals_required: Annotated[int, Field(description="Number of approvals required", ge=0)],
    user_ids: Annotated[list[int] | None, Field(description="User IDs for the rule")] = None,
    group_ids: Annotated[list[int] | None, Field(description="Group IDs for the rule")] = None,
) -> str:
    """Create a project-level approval rule.

    Returns the new rule's id, name, approvals_required, and target users/groups.
    """
    return _ok(
        await _get_client(ctx).post(
            f"/projects/{_enc(project_id)}/approval_rules",
            _params(
                name=name,
                approvals_required=approvals_required,
                user_ids=user_ids,
                group_ids=group_ids,
            ),
        )
    )


@mcp.tool(
    tags={"gitlab", "approvals", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_update_project_approval_rule(
    ctx: Context,
    project_id: ProjectId,
    rule_id: Annotated[int, Field(description="Approval rule ID")],
    name: Annotated[str | None, Field(description="Rule name", min_length=1)] = None,
    approvals_required: Annotated[
        int | None, Field(description="Number of approvals required", ge=0)
    ] = None,
    user_ids: Annotated[list[int] | None, Field(description="User IDs for the rule")] = None,
    group_ids: Annotated[list[int] | None, Field(description="Group IDs for the rule")] = None,
) -> str:
    """Update a project-level approval rule. Returns the updated rule object."""
    return _ok(
        await _get_client(ctx).put(
            f"/projects/{_enc(project_id)}/approval_rules/{rule_id}",
            _params(
                name=name,
                approvals_required=approvals_required,
                user_ids=user_ids,
                group_ids=group_ids,
            ),
        )
    )


@mcp.tool(
    tags={"gitlab", "approvals", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_delete_project_approval_rule(
    ctx: Context,
    project_id: ProjectId,
    rule_id: Annotated[int, Field(description="Approval rule ID")],
) -> str:
    """Delete a project-level approval rule. Returns a {status: deleted, rule_id} confirmation."""
    await _get_client(ctx).delete(f"/projects/{_enc(project_id)}/approval_rules/{rule_id}")
    return _ok({"status": "deleted", "rule_id": rule_id})


# ════════════════════════════════════════════════════════════════════
# MR Approval Rules
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "approvals", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_list_mr_approval_rules(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
) -> str:
    """List approval rules attached to a merge request.

    Returns rules with id, name, approvals_required, and approvers.
    """
    data = await _get_client(ctx).get(
        f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/approval_rules"
    )
    return _paginated(data)


@mcp.tool(
    tags={"gitlab", "approvals", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_create_mr_approval_rule(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    name: Annotated[str, Field(description="Rule name", min_length=1)],
    approvals_required: Annotated[int, Field(description="Number of approvals required", ge=0)],
    user_ids: Annotated[list[int] | None, Field(description="User IDs")] = None,
    group_ids: Annotated[list[int] | None, Field(description="Group IDs")] = None,
) -> str:
    """Add an approval rule to a merge request.

    Returns the new rule's id, name, approvals_required, and approvers.
    """
    return _ok(
        await _get_client(ctx).post(
            f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/approval_rules",
            _params(
                name=name,
                approvals_required=approvals_required,
                user_ids=user_ids,
                group_ids=group_ids,
            ),
        )
    )


@mcp.tool(
    tags={"gitlab", "approvals", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_update_mr_approval_rule(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    rule_id: Annotated[int, Field(description="Approval rule ID")],
    name: Annotated[str | None, Field(description="Rule name", min_length=1)] = None,
    approvals_required: Annotated[int | None, Field(description="Approvals required")] = None,
    user_ids: Annotated[list[int] | None, Field(description="User IDs")] = None,
    group_ids: Annotated[list[int] | None, Field(description="Group IDs")] = None,
) -> str:
    """Update a merge-request-level approval rule. Returns the updated rule object."""
    return _ok(
        await _get_client(ctx).put(
            f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/approval_rules/{rule_id}",
            _params(
                name=name,
                approvals_required=approvals_required,
                user_ids=user_ids,
                group_ids=group_ids,
            ),
        )
    )


@mcp.tool(
    tags={"gitlab", "approvals", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_delete_mr_approval_rule(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    rule_id: Annotated[int, Field(description="Approval rule ID")],
) -> str:
    """Delete an approval rule from a merge request.

    Returns a {status: deleted, rule_id} confirmation.
    """
    await _get_client(ctx).delete(
        f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/approval_rules/{rule_id}"
    )
    return _ok({"status": "deleted", "rule_id": rule_id})


# ════════════════════════════════════════════════════════════════════
# Groups
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "groups", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_list_groups(
    ctx: Context,
    search: Annotated[str | None, Field(description="Search by name")] = None,
    per_page: PerPage = None,
    page: Annotated[int, Field(description="Page number (follow next_page to continue)", ge=1)] = 1,
) -> str:
    """List groups visible to the caller.

    Returns id, name, full_path, parent_id, visibility, web_url per group.
    """
    data, next_page = await _get_client(ctx).get_paged(
        "/groups", {"per_page": 50, **_params(search=search, per_page=per_page, page=page)}
    )
    return _paginated(data, next_page)


@mcp.tool(
    tags={"gitlab", "groups", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_get_group(
    ctx: Context,
    group_id: Annotated[str, Field(description="Group ID or URL-encoded path", min_length=1)],
) -> str:
    """Get a group's details.

    Returns id, name, full_path, visibility, web_url, and subgroup/membership counts.
    """
    return _ok(await _get_client(ctx).get(f"/groups/{_enc(group_id)}"))


@mcp.tool(
    tags={"gitlab", "groups", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_share_project_with_group(
    ctx: Context,
    project_id: ProjectId,
    group_id: Annotated[int, Field(description="Group ID to share with")],
    access_level: AccessLevel,
) -> str:
    """Grant a group access to a project at the given access level.

    Returns a {status: shared, project_id, group_id} confirmation.
    """
    await _get_client(ctx).post(
        f"/projects/{_enc(project_id)}/share",
        {"group_id": group_id, "group_access": ACCESS_LEVELS[access_level]},
    )
    return _ok({"status": "shared", "project_id": project_id, "group_id": group_id})


@mcp.tool(
    tags={"gitlab", "groups", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_unshare_project_with_group(
    ctx: Context,
    project_id: ProjectId,
    group_id: Annotated[int, Field(description="Group ID to unshare")],
) -> str:
    """Revoke a group's access to a project.

    Returns a {status: unshared, project_id, group_id} confirmation.
    """
    await _get_client(ctx).delete(f"/projects/{_enc(project_id)}/share/{group_id}")
    return _ok({"status": "unshared", "project_id": project_id, "group_id": group_id})


@mcp.tool(
    tags={"gitlab", "groups", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_share_group_with_group(
    ctx: Context,
    target_group_id: Annotated[str, Field(description="Target group ID or path")],
    source_group_id: Annotated[int, Field(description="Source group ID to share")],
    access_level: AccessLevel,
) -> str:
    """Grant one group access to another group at the given access level.

    Returns the share record.
    """
    await _get_client(ctx).post(
        f"/groups/{_enc(target_group_id)}/share",
        {"group_id": source_group_id, "group_access": ACCESS_LEVELS[access_level]},
    )
    return _ok({"status": "shared"})


@mcp.tool(
    tags={"gitlab", "groups", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_unshare_group_with_group(
    ctx: Context,
    target_group_id: Annotated[str, Field(description="Target group ID or path")],
    source_group_id: Annotated[int, Field(description="Source group ID to remove")],
) -> str:
    """Revoke a group-to-group share. Returns a {status: unshared} confirmation."""
    await _get_client(ctx).delete(f"/groups/{_enc(target_group_id)}/share/{source_group_id}")
    return _ok({"status": "unshared"})


# ════════════════════════════════════════════════════════════════════
# Branches
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "branches", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_list_branches(
    ctx: Context,
    project_id: ProjectId,
    search: Annotated[str | None, Field(description="Filter by branch name")] = None,
    per_page: PerPage = None,
    page: Annotated[int, Field(description="Page number (follow next_page to continue)", ge=1)] = 1,
) -> str:
    """List branches in a project.

    Returns name, commit sha, protected, default, and merged flags per branch.
    """
    data, next_page = await _get_client(ctx).get_paged(
        f"/projects/{_enc(project_id)}/repository/branches",
        {"per_page": 100, **_params(search=search, per_page=per_page, page=page)},
    )
    return _paginated(data, next_page)


@mcp.tool(
    tags={"gitlab", "branches", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_create_branch(
    ctx: Context,
    project_id: ProjectId,
    branch_name: Annotated[str, Field(description="New branch name", min_length=1)],
    ref: Annotated[str, Field(description="Source branch or commit SHA", min_length=1)],
) -> str:
    """Create a branch from an existing ref.

    Returns the new branch's name, commit sha, and protection status.
    """
    return _ok(
        await _get_client(ctx).post(
            f"/projects/{_enc(project_id)}/repository/branches",
            {"branch": branch_name, "ref": ref},
        )
    )


@mcp.tool(
    tags={"gitlab", "branches", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_delete_branch(
    ctx: Context,
    project_id: ProjectId,
    branch_name: Annotated[str, Field(description="Branch name to delete", min_length=1)],
) -> str:
    """Delete a branch from a project. Returns a {status: deleted, branch} confirmation."""
    await _get_client(ctx).delete(
        f"/projects/{_enc(project_id)}/repository/branches/{quote(branch_name, safe='')}"
    )
    return _ok({"status": "deleted", "branch": branch_name})


# ════════════════════════════════════════════════════════════════════
# Commits
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "commits", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_list_commits(
    ctx: Context,
    project_id: ProjectId,
    ref_name: Annotated[str | None, Field(description="Branch or tag name")] = None,
    since: Annotated[str | None, Field(description="ISO 8601 date, commits after")] = None,
    until: Annotated[str | None, Field(description="ISO 8601 date, commits before")] = None,
    path: Annotated[str | None, Field(description="File path filter")] = None,
    per_page: PerPage = None,
    page: Annotated[int, Field(description="Page number (follow next_page to continue)", ge=1)] = 1,
) -> str:
    """List commits on a ref (branch, tag, or sha).

    Returns id, short_id, title, author_name, authored_date, web_url per commit.
    """
    data, next_page = await _get_client(ctx).get_paged(
        f"/projects/{_enc(project_id)}/repository/commits",
        {
            "per_page": 40,
            **_params(
                ref_name=ref_name, since=since, until=until, path=path, per_page=per_page, page=page
            ),
        },
    )
    return _paginated(data, next_page)


@mcp.tool(
    tags={"gitlab", "commits", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_get_commit(
    ctx: Context,
    project_id: ProjectId,
    sha: Annotated[str, Field(description="Commit SHA", min_length=1)],
    include_diff: Annotated[bool, Field(description="Include file diffs")] = False,
) -> str:
    """Get a single commit, optionally with diff.

    Returns id, short_id, title, message, author, committed_date, web_url
    (and diffs when include_diff=true).
    """
    client = _get_client(ctx)
    base = f"/projects/{_enc(project_id)}/repository/commits/{quote(sha, safe='')}"
    commit = await client.get(base)
    if include_diff:
        commit["diffs"] = await client.get(f"{base}/diff")
    return _ok(commit)


@mcp.tool(
    tags={"gitlab", "commits", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_create_commit(
    ctx: Context,
    project_id: ProjectId,
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
    """Create a commit applying create/update/delete/move/chmod file actions in one call.

    Returns the new commit's id, short_id, title, and parent_ids.
    """
    return _ok(
        await _get_client(ctx).post(
            f"/projects/{_enc(project_id)}/repository/commits",
            _params(
                branch=branch,
                commit_message=commit_message,
                actions=actions,
                start_branch=start_branch,
            ),
        )
    )


@mcp.tool(
    tags={"gitlab", "commits", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_compare(
    ctx: Context,
    project_id: ProjectId,
    from_ref: Annotated[
        str, Field(description="Source branch/tag/SHA", alias="from", min_length=1)
    ],
    to_ref: Annotated[str, Field(description="Target branch/tag/SHA", alias="to", min_length=1)],
) -> str:
    """Compare two refs (branch, tag, or sha).

    Returns commits, diffs, compare_timeout, and compare_same_ref flags.
    """
    return _ok(
        await _get_client(ctx).get(
            f"/projects/{_enc(project_id)}/repository/compare",
            {"from": from_ref, "to": to_ref},
        )
    )


# ════════════════════════════════════════════════════════════════════
# Merge Requests
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "merge_requests", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_list_mrs(
    ctx: Context,
    project_id: ProjectId,
    state: Annotated[str | None, Field(description="opened, closed, merged, or all")] = None,
    scope: Annotated[str | None, Field(description="created_by_me, assigned_to_me, or all")] = None,
    source_branch: Annotated[str | None, Field(description="Filter by source branch")] = None,
    target_branch: Annotated[str | None, Field(description="Filter by target branch")] = None,
    search: Annotated[str | None, Field(description="Search in title/description")] = None,
    labels: Annotated[str | None, Field(description="Comma-separated labels")] = None,
    per_page: PerPage = None,
    page: Annotated[int, Field(description="Page number (follow next_page to continue)", ge=1)] = 1,
) -> str:
    """List merge requests in a project, filterable by state/labels/author.

    Returns iid, title, state, source_branch, target_branch, author, web_url per MR.
    """
    data, next_page = await _get_client(ctx).get_paged(
        f"/projects/{_enc(project_id)}/merge_requests",
        {
            "per_page": 20,
            **_params(
                state=state,
                scope=scope,
                source_branch=source_branch,
                target_branch=target_branch,
                search=search,
                labels=labels,
                per_page=per_page,
                page=page,
            ),
        },
    )
    return _paginated(data, next_page)


@mcp.tool(
    tags={"gitlab", "merge_requests", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_get_mr(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
) -> str:
    """Get merge request details.

    Returns title, state, source/target branches, author, diff_refs, and merge status.
    """
    return _ok(await _get_client(ctx).get_merge_request(project_id, mr_iid))


@mcp.tool(
    tags={"gitlab", "merge_requests", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_create_mr(
    ctx: Context,
    project_id: ProjectId,
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
    """Create a merge request.

    Returns the new MR's iid, title, state, source_branch, target_branch, and web_url.
    """
    return _ok(
        await _get_client(ctx).post(
            f"/projects/{_enc(project_id)}/merge_requests",
            _params(
                source_branch=source_branch,
                target_branch=target_branch,
                title=title,
                description=description,
                draft=draft,
                squash=squash,
                remove_source_branch=remove_source_branch,
                labels=labels,
            ),
        )
    )


@mcp.tool(
    tags={"gitlab", "merge_requests", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_update_mr(
    ctx: Context,
    project_id: ProjectId,
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
    """Update an MR's title, description, target branch, labels, squash/draft flags, or state.

    Returns the updated MR object.
    """
    return _ok(
        await _get_client(ctx).put(
            f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}",
            _params(
                title=title,
                description=description,
                target_branch=target_branch,
                labels=labels,
                squash=squash,
                remove_source_branch=remove_source_branch,
                draft=draft,
                state_event=state_event,
            ),
        )
    )


@mcp.tool(
    tags={"gitlab", "merge_requests", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_merge_mr(
    ctx: Context,
    project_id: ProjectId,
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
    """Merge a merge request, optionally only when the pipeline succeeds.

    Returns the merged MR with state=merged and merge_commit_sha.
    """
    return _ok(
        await _get_client(ctx).merge_merge_request(
            project_id,
            mr_iid,
            _params(
                squash=squash,
                should_remove_source_branch=delete_source_branch,
                merge_commit_message=merge_commit_message,
                squash_commit_message=squash_commit_message,
                merge_when_pipeline_succeeds=merge_when_pipeline_succeeds,
            ),
        )
    )


@mcp.tool(
    tags={"gitlab", "merge_requests", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result
async def gitlab_merge_mr_sequence(
    ctx: Context,
    project_id: ProjectId,
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
    """Merge several MRs sequentially, stopping at the first failure.

    Returns a per-MR result list with merged/failed status and any error.
    """
    # Keeps its own expected-error handler: the envelope must say which MRs
    # already merged before the failure. Bugs still fall through to tool_result.
    merged: list[int] = []
    try:
        _check_write(ctx)
        client = _get_client(ctx)
        params = _params(
            squash=squash,
            should_remove_source_branch=delete_source_branch,
            merge_when_pipeline_succeeds=merge_when_pipeline_succeeds,
        )
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
            await client.merge_merge_request(project_id, iid, params)
            merged.append(iid)
        return _ok({"status": "all_merged", "merged": merged})
    except GitLabError as e:
        detail = json.loads(_err(e))
        detail["merged_so_far"] = merged
        return _ok(detail)


@mcp.tool(
    tags={"gitlab", "merge_requests", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_rebase_mr(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    skip_ci: Annotated[bool, Field(description="Skip CI pipeline for rebase")] = False,
) -> str:
    """Trigger a server-side rebase of an MR onto its target branch.

    Returns {rebase_in_progress: true}.
    """
    return _ok(
        await _get_client(ctx).put(
            f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/rebase",
            {"skip_ci": skip_ci},
        )
    )


@mcp.tool(
    tags={"gitlab", "merge_requests", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_mr_changes(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
) -> str:
    """Get file changes of a merge request. Returns list of diffs with old/new paths and content."""
    return _ok(
        await _get_client(ctx).get(f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/changes")
    )


# ════════════════════════════════════════════════════════════════════
# MR Notes
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "notes", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_list_mr_notes(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    include_system: Annotated[bool, Field(description="Include system-generated notes")] = False,
    page: Annotated[int, Field(description="Page number (follow next_page to continue)", ge=1)] = 1,
) -> str:
    """List notes (comments) on a merge request.

    Returns id, body, author, created_at, and system flag per note.

    `count` is the number of notes left after the system-note filter, while
    `has_more` describes the unfiltered server page. A page of nothing but
    system notes therefore returns count 0 with has_more true -- keep following
    next_page rather than concluding the MR has no comments.
    """
    data, next_page = await _get_client(ctx).get_paged(
        f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/notes",
        {"per_page": 100, "page": page},
    )
    if not include_system:
        data = [n for n in data if not n.get("system", False)]
    return _paginated(data, next_page)


@mcp.tool(
    tags={"gitlab", "notes", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_add_mr_note(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    body: Annotated[str, Field(description="Comment body (markdown)", min_length=1)],
    internal: Annotated[
        bool, Field(description="Internal note (not visible to non-members)")
    ] = False,
) -> str:
    """Post a new comment on a merge request.

    Returns the new note's id, body, author, and created_at.
    """
    data: dict[str, Any] = {"body": body}
    if internal:
        data["internal"] = True
    return _ok(
        await _get_client(ctx).post(
            f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/notes", data
        )
    )


@mcp.tool(
    tags={"gitlab", "notes", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_delete_mr_note(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    note_id: Annotated[int, Field(description="Note ID to delete")],
) -> str:
    """Delete a comment from a merge request. Returns a {status: deleted, note_id} confirmation."""
    await _get_client(ctx).delete(
        f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/notes/{note_id}"
    )
    return _ok({"status": "deleted", "note_id": note_id})


@mcp.tool(
    tags={"gitlab", "notes", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_update_mr_note(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    note_id: Annotated[int, Field(description="Note ID to update")],
    body: Annotated[str, Field(description="New note body", min_length=1)],
) -> str:
    """Edit an existing MR comment's body.

    Returns the updated note's id, body, author, and updated_at.
    """
    return _ok(
        await _get_client(ctx).put(
            f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/notes/{note_id}",
            {"body": body},
        )
    )


@mcp.tool(
    tags={"gitlab", "notes", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_award_emoji(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    note_id: Annotated[int, Field(description="Note ID")],
    emoji: Annotated[str, Field(description="Emoji name (e.g. thumbsup, 100, eyes)", min_length=1)],
) -> str:
    """Add an emoji reaction to an MR note. Returns the new award's id, name, and user."""
    return _ok(
        await _get_client(ctx).post(
            f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/notes/{note_id}/award_emoji",
            {"name": emoji},
        )
    )


@mcp.tool(
    tags={"gitlab", "notes", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_remove_emoji(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    note_id: Annotated[int, Field(description="Note ID")],
    award_id: Annotated[int, Field(description="Award emoji ID to remove")],
) -> str:
    """Remove an emoji reaction from an MR note. Returns a {status: removed} confirmation."""
    await _get_client(ctx).delete(
        f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/notes/{note_id}/award_emoji/{award_id}"
    )
    return _ok({"status": "removed", "award_id": award_id})


# ════════════════════════════════════════════════════════════════════
# MR Discussions
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "discussions", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_list_mr_discussions(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    page: Annotated[int, Field(description="Page number (follow next_page to continue)", ge=1)] = 1,
) -> str:
    """List discussions on a merge request.

    Returns discussion threads with notes, excluding system-only threads.

    `count` is post-filter while `has_more` describes the unfiltered server
    page, so a page of only system threads returns count 0 with has_more true.
    """
    data, next_page = await _get_client(ctx).get_paged(
        f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/discussions",
        {"per_page": 100, "page": page},
    )
    # Filter out system-only discussions
    filtered = []
    for d in data:
        notes = d.get("notes", [])
        if any(not n.get("system", False) for n in notes):
            filtered.append(d)
    return _paginated(filtered, next_page)


@mcp.tool(
    tags={"gitlab", "discussions", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_create_mr_discussion(
    ctx: Context,
    project_id: ProjectId,
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

    return _ok(
        await _get_client(ctx).post(
            f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/discussions", params
        )
    )


@mcp.tool(
    tags={"gitlab", "discussions", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_reply_to_discussion(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    discussion_id: Annotated[str, Field(description="Discussion ID", min_length=1)],
    body: Annotated[str, Field(description="Reply body (markdown)", min_length=1)],
) -> str:
    """Reply to an existing MR discussion thread.

    Returns the new note's id, body, author, and created_at.
    """
    return _ok(
        await _get_client(ctx).post(
            f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/discussions/{discussion_id}/notes",
            {"body": body},
        )
    )


@mcp.tool(
    tags={"gitlab", "discussions", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_resolve_discussion(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    discussion_id: Annotated[str, Field(description="Discussion ID", min_length=1)],
    resolved: Annotated[bool, Field(description="True to resolve, False to unresolve")],
) -> str:
    """Mark an MR discussion as resolved or unresolved.

    Returns the updated discussion with its resolved flag and notes.
    """
    data = await _get_client(ctx).put(
        f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/discussions/{discussion_id}",
        {"resolved": resolved},
    )
    return _ok(data)


# ════════════════════════════════════════════════════════════════════
# MR Approvals & Metadata
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "merge_requests", "approvals", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": False},
)
@tool_result(write=True)
async def gitlab_approve_mr(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    sha: Annotated[
        str | None,
        Field(description="Expected HEAD SHA — returns 409 if mismatched (safety check)"),
    ] = None,
) -> str:
    """Approve a merge request, optionally gating on a sha so HEAD hasn't changed.

    Returns the updated approval state (approved_by, approvals_left).
    """
    data: dict[str, Any] = {}
    if sha:
        data["sha"] = sha
    return _ok(
        await _get_client(ctx).post(
            f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/approve", data or None
        )
    )


@mcp.tool(
    tags={"gitlab", "merge_requests", "approvals", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": False},
)
@tool_result(write=True)
async def gitlab_unapprove_mr(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
) -> str:
    """Remove the current user's approval from a merge request.

    Returns the updated approval state.
    """
    return _ok(
        await _get_client(ctx).post(
            f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/unapprove"
        )
    )


@mcp.tool(
    tags={"gitlab", "merge_requests", "approvals", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_get_mr_approvals(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
) -> str:
    """Get the approval state of a merge request.

    Returns approved_by, approvals_required, approvals_left, and matching rules.
    """
    return _ok(
        await _get_client(ctx).get(
            f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/approvals"
        )
    )


@mcp.tool(
    tags={"gitlab", "merge_requests", "pipelines", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_list_mr_pipelines(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    slim: Annotated[bool, Field(description="Strip verbose fields from response")] = True,
    page: Annotated[int, Field(description="Page number (follow next_page to continue)", ge=1)] = 1,
) -> str:
    """List pipelines associated with a merge request.

    Returns id, status, ref, sha, source, web_url per pipeline.
    """
    data, next_page = await _get_client(ctx).get_paged(
        f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/pipelines", {"page": page}
    )
    return _paginated([_slim(p, _PIPELINE_KEYS) for p in data] if slim else data, next_page)


@mcp.tool(
    tags={"gitlab", "merge_requests", "commits", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_list_mr_commits(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
    page: Annotated[int, Field(description="Page number (follow next_page to continue)", ge=1)] = 1,
) -> str:
    """List commits included in a merge request.

    Returns id, short_id, title, author_name, authored_date per commit.
    """
    data, next_page = await _get_client(ctx).get_paged(
        f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/commits", {"page": page}
    )
    return _paginated(data, next_page)


@mcp.tool(
    tags={"gitlab", "merge_requests", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": False},
)
@tool_result(write=True)
async def gitlab_subscribe_mr(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
) -> str:
    """Subscribe the authenticated user to notifications for a merge request.

    Returns the updated MR object.
    """
    return _ok(
        await _get_client(ctx).post(
            f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/subscribe"
        )
    )


@mcp.tool(
    tags={"gitlab", "merge_requests", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": False},
)
@tool_result(write=True)
async def gitlab_unsubscribe_mr(
    ctx: Context,
    project_id: ProjectId,
    mr_iid: Annotated[int, Field(description="Merge request IID")],
) -> str:
    """Unsubscribe the authenticated user from notifications for a merge request.

    Returns the updated MR object.
    """
    return _ok(
        await _get_client(ctx).post(
            f"/projects/{_enc(project_id)}/merge_requests/{mr_iid}/unsubscribe"
        )
    )


# ════════════════════════════════════════════════════════════════════
# Pipelines
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "pipelines", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_list_pipelines(
    ctx: Context,
    project_id: ProjectId,
    ref: Annotated[str | None, Field(description="Filter by branch/tag")] = None,
    status: Annotated[
        str | None,
        Field(description="Filter by status (running, pending, success, failed, etc.)"),
    ] = None,
    source: Annotated[
        str | None, Field(description="Filter by source (push, web, trigger, etc.)")
    ] = None,
    per_page: PerPage = None,
    slim: Annotated[bool, Field(description="Strip verbose fields from response")] = True,
    page: Annotated[int, Field(description="Page number (follow next_page to continue)", ge=1)] = 1,
) -> str:
    """List pipelines for a project. Returns id, status, ref, source, timing, web_url."""
    data, next_page = await _get_client(ctx).get_paged(
        f"/projects/{_enc(project_id)}/pipelines",
        {
            "per_page": 20,
            **_params(ref=ref, status=status, source=source, per_page=per_page, page=page),
        },
    )
    return _paginated([_slim(p, _PIPELINE_KEYS) for p in data] if slim else data, next_page)


@mcp.tool(
    tags={"gitlab", "pipelines", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_get_pipeline(
    ctx: Context,
    project_id: ProjectId,
    pipeline_id: Annotated[int, Field(description="Pipeline ID")],
    include_jobs: Annotated[bool, Field(description="Include pipeline jobs")] = False,
    slim: Annotated[bool, Field(description="Strip verbose fields from response")] = True,
) -> str:
    """Get pipeline details, optionally with jobs.

    Returns id, status, ref, timing, web_url.
    Jobs include id, name, stage, status, timing, failure_reason, web_url.
    """
    client = _get_client(ctx)
    base = f"/projects/{_enc(project_id)}/pipelines/{pipeline_id}"
    pipeline = await client.get(base)
    if slim:
        pipeline = _slim(pipeline, _PIPELINE_KEYS)
    if include_jobs:
        jobs, _ = await client.get_paged(f"{base}/jobs", {"per_page": 100, "page": 1})
        pipeline["jobs"] = [_slim(j, _JOB_KEYS) for j in jobs] if slim else jobs
    return _ok(pipeline)


@mcp.tool(
    tags={"gitlab", "pipelines", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_create_pipeline(
    ctx: Context,
    project_id: ProjectId,
    ref: Annotated[str, Field(description="Branch or tag to run pipeline on", min_length=1)],
    variables: Annotated[
        list[dict[str, str]] | None,
        Field(description="Pipeline variables: [{key: str, value: str, variable_type?: str}]"),
    ] = None,
) -> str:
    """Trigger a new pipeline on the given ref, optionally with variables.

    Returns the new pipeline's id, status, ref, sha, source, web_url.
    """
    data: dict[str, Any] = {"ref": ref}
    if variables:
        data["variables"] = variables
    result = await _get_client(ctx).post(f"/projects/{_enc(project_id)}/pipeline", data)
    return _ok(_slim(result, _PIPELINE_KEYS))


@mcp.tool(
    tags={"gitlab", "pipelines", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_retry_pipeline(
    ctx: Context,
    project_id: ProjectId,
    pipeline_id: Annotated[int, Field(description="Pipeline ID")],
) -> str:
    """Retry all failed or canceled jobs in a pipeline.

    Returns the updated pipeline with status and timing.
    """
    return _ok(
        _slim(
            await _get_client(ctx).post(
                f"/projects/{_enc(project_id)}/pipelines/{pipeline_id}/retry"
            ),
            _PIPELINE_KEYS,
        )
    )


@mcp.tool(
    tags={"gitlab", "pipelines", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_cancel_pipeline(
    ctx: Context,
    project_id: ProjectId,
    pipeline_id: Annotated[int, Field(description="Pipeline ID")],
) -> str:
    """Cancel a running pipeline. Returns the updated pipeline with status=canceled."""
    return _ok(
        _slim(
            await _get_client(ctx).post(
                f"/projects/{_enc(project_id)}/pipelines/{pipeline_id}/cancel"
            ),
            _PIPELINE_KEYS,
        )
    )


# ════════════════════════════════════════════════════════════════════
# Jobs
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "jobs", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_retry_job(
    ctx: Context,
    project_id: ProjectId,
    job_id: Annotated[int, Field(description="Job ID")],
) -> str:
    """Retry a failed job. Returns the new job's id, status, name, stage, and web_url."""
    result = await _get_client(ctx).post(f"/projects/{_enc(project_id)}/jobs/{job_id}/retry")
    return _ok(_slim(result, _JOB_KEYS))


@mcp.tool(
    tags={"gitlab", "jobs", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_play_job(
    ctx: Context,
    project_id: ProjectId,
    job_id: Annotated[int, Field(description="Job ID")],
    variables: Annotated[
        list[dict[str, str]] | None,
        Field(description="Job variables: [{key: str, value: str}]"),
    ] = None,
) -> str:
    """Trigger a manual job, optionally with job variables.

    Returns the started job's id, status, name, and web_url.
    """
    data: dict[str, Any] = {}
    if variables:
        data["job_variables_attributes"] = variables
    return _ok(
        _slim(
            await _get_client(ctx).post(
                f"/projects/{_enc(project_id)}/jobs/{job_id}/play", data or None
            ),
            _JOB_KEYS,
        )
    )


@mcp.tool(
    tags={"gitlab", "jobs", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_cancel_job(
    ctx: Context,
    project_id: ProjectId,
    job_id: Annotated[int, Field(description="Job ID")],
) -> str:
    """Cancel a running job. Returns the updated job with status=canceled."""
    result = await _get_client(ctx).post(f"/projects/{_enc(project_id)}/jobs/{job_id}/cancel")
    return _ok(_slim(result, _JOB_KEYS))


@mcp.tool(
    tags={"gitlab", "jobs", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_get_job_log(
    ctx: Context,
    project_id: ProjectId,
    job_id: Annotated[int, Field(description="Job ID")],
    tail_lines: Annotated[
        int,
        Field(description="Lines to return from the end of the log; 0 returns the whole log", ge=0),
    ] = 200,
) -> str:
    """Get a job's log trace, truncated to the last tail_lines lines (default 200).

    Returns {log, total_lines, shown_lines}. Pass tail_lines=0 for the whole log.
    """
    log_text = await _get_client(ctx).get(
        f"/projects/{_enc(project_id)}/jobs/{job_id}/trace", raw=True
    )
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


# ════════════════════════════════════════════════════════════════════
# Tags
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "tags", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_list_tags(
    ctx: Context,
    project_id: ProjectId,
    search: Annotated[str | None, Field(description="Filter by tag name")] = None,
    order_by: Annotated[str | None, Field(description="name, updated, or version")] = None,
    sort: Annotated[str | None, Field(description="asc or desc")] = None,
    per_page: PerPage = None,
    page: Annotated[int, Field(description="Page number (follow next_page to continue)", ge=1)] = 1,
) -> str:
    """List repository tags.

    Returns name, message, target sha, commit summary, and any attached release per tag.
    """
    data, next_page = await _get_client(ctx).get_paged(
        f"/projects/{_enc(project_id)}/repository/tags",
        {
            "per_page": 20,
            **_params(search=search, order_by=order_by, sort=sort, per_page=per_page, page=page),
        },
    )
    return _paginated(data, next_page)


@mcp.tool(
    tags={"gitlab", "tags", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_get_tag(
    ctx: Context,
    project_id: ProjectId,
    tag_name: Annotated[str, Field(description="Tag name", min_length=1)],
) -> str:
    """Get a tag's details. Returns name, message, target commit, and any attached release."""
    return _ok(
        await _get_client(ctx).get(
            f"/projects/{_enc(project_id)}/repository/tags/{quote(tag_name, safe='')}"
        )
    )


@mcp.tool(
    tags={"gitlab", "tags", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_create_tag(
    ctx: Context,
    project_id: ProjectId,
    tag_name: Annotated[str, Field(description="Tag name", min_length=1)],
    ref: Annotated[str, Field(description="Branch or commit SHA to tag", min_length=1)],
    message: Annotated[str | None, Field(description="Annotated tag message")] = None,
) -> str:
    """Create a tag on the given ref, optionally with a message.

    Returns the new tag's name, message, target, and commit.
    """
    return _ok(
        await _get_client(ctx).post(
            f"/projects/{_enc(project_id)}/repository/tags",
            _params(tag_name=tag_name, ref=ref, message=message),
        )
    )


@mcp.tool(
    tags={"gitlab", "tags", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_delete_tag(
    ctx: Context,
    project_id: ProjectId,
    tag_name: Annotated[str, Field(description="Tag name to delete", min_length=1)],
) -> str:
    """Delete a tag. Returns a {status: deleted, tag} confirmation."""
    await _get_client(ctx).delete(
        f"/projects/{_enc(project_id)}/repository/tags/{quote(tag_name, safe='')}"
    )
    return _ok({"status": "deleted", "tag": tag_name})


# ════════════════════════════════════════════════════════════════════
# Releases
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "releases", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_list_releases(
    ctx: Context,
    project_id: ProjectId,
    per_page: PerPage = None,
    page: Annotated[int, Field(description="Page number (follow next_page to continue)", ge=1)] = 1,
) -> str:
    """List project releases.

    Returns tag_name, name, description, created_at, released_at, and assets per release.
    """
    data, next_page = await _get_client(ctx).get_paged(
        f"/projects/{_enc(project_id)}/releases",
        {"per_page": 20, **_params(per_page=per_page, page=page)},
    )
    return _paginated(data, next_page)


@mcp.tool(
    tags={"gitlab", "releases", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_get_release(
    ctx: Context,
    project_id: ProjectId,
    tag_name: Annotated[str, Field(description="Tag name of the release", min_length=1)],
) -> str:
    """Get a release by tag.

    Returns name, description, tag_name, created_at, and assets (links, sources).
    """
    return _ok(
        await _get_client(ctx).get(
            f"/projects/{_enc(project_id)}/releases/{quote(tag_name, safe='')}"
        )
    )


@mcp.tool(
    tags={"gitlab", "releases", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_create_release(
    ctx: Context,
    project_id: ProjectId,
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
    """Create a release tied to a tag (or a new ref).

    Returns the new release with tag_name, name, description, and assets.
    """
    params = _params(
        tag_name=tag_name,
        name=name,
        description=description,
        ref=ref,
        released_at=released_at,
        assets={"links": links} if links is not None else None,
    )
    return _ok(await _get_client(ctx).post(f"/projects/{_enc(project_id)}/releases", params))


@mcp.tool(
    tags={"gitlab", "releases", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_update_release(
    ctx: Context,
    project_id: ProjectId,
    tag_name: Annotated[str, Field(description="Tag name of the release", min_length=1)],
    name: Annotated[str | None, Field(description="New release name")] = None,
    description: Annotated[str | None, Field(description="New release description")] = None,
    released_at: Annotated[str | None, Field(description="New release date (ISO 8601)")] = None,
) -> str:
    """Update a release's name, description, or release date. Returns the updated release."""
    return _ok(
        await _get_client(ctx).put(
            f"/projects/{_enc(project_id)}/releases/{quote(tag_name, safe='')}",
            _params(name=name, description=description, released_at=released_at),
        )
    )


@mcp.tool(
    tags={"gitlab", "releases", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_delete_release(
    ctx: Context,
    project_id: ProjectId,
    tag_name: Annotated[str, Field(description="Tag name of the release", min_length=1)],
) -> str:
    """Delete a release (the underlying tag is preserved).

    Returns a {status: deleted, tag_name} confirmation.
    """
    await _get_client(ctx).delete(
        f"/projects/{_enc(project_id)}/releases/{quote(tag_name, safe='')}"
    )
    return _ok({"status": "deleted", "tag_name": tag_name})


# ════════════════════════════════════════════════════════════════════
# CI/CD Variables (Project)
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "variables", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_list_variables(
    ctx: Context,
    project_id: ProjectId,
    page: Annotated[int, Field(description="Page number (follow next_page to continue)", ge=1)] = 1,
) -> str:
    """List project CI/CD variables.

    Returns key, value (shown as '***MASKED***' when masked), protected, masked,
    environment_scope per variable.
    """
    data, next_page = await _get_client(ctx).get_paged(
        f"/projects/{_enc(project_id)}/variables", {"per_page": 100, "page": page}
    )
    for var in data:
        if var.get("masked"):
            var["value"] = "***MASKED***"
    return _paginated(data, next_page)


@mcp.tool(
    tags={"gitlab", "variables", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_create_variable(
    ctx: Context,
    project_id: ProjectId,
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
    """Create a project CI/CD variable.

    Returns the new variable's key, value (masked if applicable), protected, masked,
    environment_scope.
    """
    params = _variable_params(
        value, variable_type, protected, masked, raw, environment_scope, description
    )
    return _ok(
        await _get_client(ctx).post(
            f"/projects/{_enc(project_id)}/variables",
            {"key": key, **params},
        )
    )


@mcp.tool(
    tags={"gitlab", "variables", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_update_variable(
    ctx: Context,
    project_id: ProjectId,
    key: Annotated[str, Field(description="Variable key", min_length=1)],
    value: Annotated[str, Field(description="New variable value")],
    variable_type: Annotated[str | None, Field(description="env_var or file")] = None,
    protected: Annotated[bool | None, Field(description="Protected branches only")] = None,
    masked: Annotated[bool | None, Field(description="Mask in logs")] = None,
    raw: Annotated[bool | None, Field(description="Do not expand references")] = None,
    environment_scope: Annotated[
        str | None,
        Field(description="Environment scope filter — selects which scoped variable to update"),
    ] = None,
    description: Annotated[str | None, Field(description="Variable description")] = None,
) -> str:
    """Update a project CI/CD variable. Returns the updated variable object.

    environment_scope selects which scoped variable to update; it does not change the scope.
    """
    query = {"filter[environment_scope]": environment_scope} if environment_scope else None
    data = await _get_client(ctx).put(
        f"/projects/{_enc(project_id)}/variables/{key}",
        _variable_params(value, variable_type, protected, masked, raw, None, description),
        params=query,
    )
    return _ok(data)


@mcp.tool(
    tags={"gitlab", "variables", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_delete_variable(
    ctx: Context,
    project_id: ProjectId,
    key: Annotated[str, Field(description="Variable key", min_length=1)],
    environment_scope: Annotated[str | None, Field(description="Environment scope filter")] = None,
) -> str:
    """Delete a project CI/CD variable. Returns a {status: deleted, key} confirmation."""
    query = {"filter[environment_scope]": environment_scope} if environment_scope else None
    await _get_client(ctx).delete(f"/projects/{_enc(project_id)}/variables/{key}", params=query)
    return _ok({"status": "deleted", "key": key})


# ════════════════════════════════════════════════════════════════════
# CI/CD Variables (Group)
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "variables", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_list_group_variables(
    ctx: Context,
    group_id: Annotated[str, Field(description="Group ID, path, or full GitLab URL", min_length=1)],
    page: Annotated[int, Field(description="Page number (follow next_page to continue)", ge=1)] = 1,
) -> str:
    """List group CI/CD variables.

    Returns key, value (shown as '***MASKED***' when masked), protected, masked,
    environment_scope per variable.
    """
    data, next_page = await _get_client(ctx).get_paged(
        f"/groups/{_enc(group_id)}/variables", {"per_page": 100, "page": page}
    )
    for var in data:
        if var.get("masked"):
            var["value"] = "***MASKED***"
    return _paginated(data, next_page)


@mcp.tool(
    tags={"gitlab", "variables", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_create_group_variable(
    ctx: Context,
    group_id: Annotated[str, Field(description="Group ID, path, or full GitLab URL", min_length=1)],
    key: Annotated[str, Field(description="Variable key", min_length=1)],
    value: Annotated[str, Field(description="Variable value")],
    variable_type: Annotated[str | None, Field(description="env_var or file")] = None,
    protected: Annotated[bool | None, Field(description="Protected branches only")] = None,
    masked: Annotated[bool | None, Field(description="Mask in logs")] = None,
    raw: Annotated[bool | None, Field(description="Do not expand references")] = None,
    environment_scope: Annotated[str | None, Field(description="Environment scope")] = None,
    description: Annotated[str | None, Field(description="Variable description")] = None,
) -> str:
    """Create a group CI/CD variable.

    Returns the new variable's key, value (masked if applicable), protected, masked,
    environment_scope.
    """
    params = _variable_params(
        value, variable_type, protected, masked, raw, environment_scope, description
    )
    return _ok(
        await _get_client(ctx).post(
            f"/groups/{_enc(group_id)}/variables",
            {"key": key, **params},
        )
    )


@mcp.tool(
    tags={"gitlab", "variables", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_update_group_variable(
    ctx: Context,
    group_id: Annotated[str, Field(description="Group ID, path, or full GitLab URL", min_length=1)],
    key: Annotated[str, Field(description="Variable key", min_length=1)],
    value: Annotated[str, Field(description="New variable value")],
    variable_type: Annotated[str | None, Field(description="env_var or file")] = None,
    protected: Annotated[bool | None, Field(description="Protected branches only")] = None,
    masked: Annotated[bool | None, Field(description="Mask in logs")] = None,
    raw: Annotated[bool | None, Field(description="Do not expand references")] = None,
    description: Annotated[str | None, Field(description="Variable description")] = None,
) -> str:
    """Update a group CI/CD variable. Returns the updated variable object."""
    return _ok(
        await _get_client(ctx).put(
            f"/groups/{_enc(group_id)}/variables/{key}",
            _variable_params(value, variable_type, protected, masked, raw, None, description),
        )
    )


@mcp.tool(
    tags={"gitlab", "variables", "write"},
    annotations={"destructiveHint": True, "readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_delete_group_variable(
    ctx: Context,
    group_id: Annotated[str, Field(description="Group ID, path, or full GitLab URL", min_length=1)],
    key: Annotated[str, Field(description="Variable key", min_length=1)],
) -> str:
    """Delete a group CI/CD variable. Returns a {status: deleted, key} confirmation."""
    await _get_client(ctx).delete(f"/groups/{_enc(group_id)}/variables/{key}")
    return _ok({"status": "deleted", "key": key})


# ════════════════════════════════════════════════════════════════════
# Issues
# ════════════════════════════════════════════════════════════════════


@mcp.tool(
    tags={"gitlab", "issues", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_list_issues(
    ctx: Context,
    project_id: ProjectId,
    state: Annotated[str | None, Field(description="opened, closed, or all")] = None,
    labels: Annotated[str | None, Field(description="Comma-separated labels")] = None,
    search: Annotated[str | None, Field(description="Search in title/description")] = None,
    assignee_id: Annotated[int | None, Field(description="Filter by assignee ID")] = None,
    per_page: PerPage = None,
    page: Annotated[int, Field(description="Page number (follow next_page to continue)", ge=1)] = 1,
) -> str:
    """List issues in a project, filterable by state/labels/assignee.

    Returns iid, title, state, labels, author, web_url per issue.
    """
    data, next_page = await _get_client(ctx).get_paged(
        f"/projects/{_enc(project_id)}/issues",
        {
            "per_page": 20,
            **_params(
                state=state,
                labels=labels,
                search=search,
                assignee_id=assignee_id,
                per_page=per_page,
                page=page,
            ),
        },
    )
    return _paginated(data, next_page)


@mcp.tool(
    tags={"gitlab", "issues", "read"},
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
)
@tool_result
async def gitlab_get_issue(
    ctx: Context,
    project_id: ProjectId,
    issue_iid: Annotated[int, Field(description="Issue IID")],
) -> str:
    """Get a single issue.

    Returns iid, title, description, state, labels, assignees, author, milestone, due_date, web_url.
    """
    return _ok(await _get_client(ctx).get(f"/projects/{_enc(project_id)}/issues/{issue_iid}"))


@mcp.tool(
    tags={"gitlab", "issues", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_create_issue(
    ctx: Context,
    project_id: ProjectId,
    title: Annotated[str, Field(description="Issue title", min_length=1)],
    description: Annotated[str | None, Field(description="Issue description (markdown)")] = None,
    labels: Annotated[str | None, Field(description="Comma-separated labels")] = None,
    assignee_ids: Annotated[list[int] | None, Field(description="Assignee user IDs")] = None,
    milestone_id: Annotated[int | None, Field(description="Milestone ID")] = None,
    confidential: Annotated[bool | None, Field(description="Mark as confidential")] = None,
    weight: Annotated[int | None, Field(description="Issue weight")] = None,
) -> str:
    """Create a new issue.

    Returns the new issue's iid, title, state, labels, assignees, author, web_url.
    """
    return _ok(
        await _get_client(ctx).post(
            f"/projects/{_enc(project_id)}/issues",
            _params(
                title=title,
                description=description,
                labels=labels,
                assignee_ids=assignee_ids,
                milestone_id=milestone_id,
                confidential=confidential,
                weight=weight,
            ),
        )
    )


@mcp.tool(
    tags={"gitlab", "issues", "write"},
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_update_issue(
    ctx: Context,
    project_id: ProjectId,
    issue_iid: Annotated[int, Field(description="Issue IID")],
    title: Annotated[str | None, Field(description="New title")] = None,
    description: Annotated[str | None, Field(description="New description")] = None,
    labels: Annotated[str | None, Field(description="Comma-separated labels")] = None,
    assignee_ids: Annotated[list[int] | None, Field(description="Assignee user IDs")] = None,
    state_event: Annotated[str | None, Field(description="close or reopen")] = None,
    weight: Annotated[int | None, Field(description="Issue weight")] = None,
) -> str:
    """Update an issue's title, description, labels, assignees, weight, or state event.

    Returns the updated issue object.
    """
    return _ok(
        await _get_client(ctx).put(
            f"/projects/{_enc(project_id)}/issues/{issue_iid}",
            _params(
                title=title,
                description=description,
                labels=labels,
                assignee_ids=assignee_ids,
                state_event=state_event,
                weight=weight,
            ),
        )
    )


@mcp.tool(
    tags={"gitlab", "issues", "write"},
    annotations={"readOnlyHint": False, "openWorldHint": True},
)
@tool_result(write=True)
async def gitlab_add_issue_comment(
    ctx: Context,
    project_id: ProjectId,
    issue_iid: Annotated[int, Field(description="Issue IID")],
    body: Annotated[str, Field(description="Comment body (markdown)", min_length=1)],
) -> str:
    """Post a comment on an issue. Returns the new note's id, body, author, and created_at."""
    return _ok(
        await _get_client(ctx).post(
            f"/projects/{_enc(project_id)}/issues/{issue_iid}/notes", {"body": body}
        )
    )
