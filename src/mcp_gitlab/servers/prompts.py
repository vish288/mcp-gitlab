"""MCP prompts — multi-tool workflow templates for GitLab operations."""

from __future__ import annotations

from pathlib import Path
from string import Template

from fastmcp.prompts.prompt import Message

from ._helpers import (
    _load_file,
    _parse_gitlab_mr_url,
    _parse_gitlab_pipeline_url,
    _parse_gitlab_project_url,
)
from .gitlab import mcp

_PROMPTS_DIR = str(Path(__file__).resolve().parent.parent / "resources" / "prompts")


def _load_prompt(filename: str) -> str:
    """Load a prompt markdown file from the prompts directory."""
    return _load_file(_PROMPTS_DIR, filename)


def _render(filename: str, **kwargs: str) -> str:
    """Load a prompt template and substitute variables safely.

    Uses string.Template ($var) instead of str.format({var}) to avoid
    KeyError when parameter values contain curly braces.
    """
    return Template(_load_prompt(filename)).safe_substitute(kwargs)


@mcp.prompt(tags={"gitlab", "review"})
def review_mr(project_id: str, mr_iid: str = "") -> list[Message]:
    """Review a GitLab merge request — fetch details, check pipeline, review
    changes, and write discussion comments.

    Accepts a full MR URL (e.g. https://gitlab.com/group/project/-/merge_requests/42)
    as project_id — mr_iid will be extracted automatically.
    """
    parsed_project, parsed_iid = _parse_gitlab_mr_url(project_id)
    if parsed_iid:
        project_id, mr_iid = parsed_project, parsed_iid
    text = _render("review-mr.md", project_id=project_id, mr_iid=mr_iid)
    return [
        Message(role="user", content=text),
        Message(
            role="assistant",
            content=(
                f"I'll review MR !{mr_iid} in project {project_id}. "
                "Let me start by fetching the MR details and pipeline status."
            ),
        ),
    ]


@mcp.prompt(tags={"gitlab", "ci"})
def diagnose_pipeline(project_id: str, pipeline_id: str = "") -> list[Message]:
    """Diagnose a failed CI/CD pipeline — identify failed jobs, get logs,
    analyze errors, and suggest fixes.

    Accepts a full pipeline URL (e.g. https://gitlab.com/group/project/-/pipelines/999)
    as project_id — pipeline_id will be extracted automatically.
    """
    parsed_project, parsed_pid = _parse_gitlab_pipeline_url(project_id)
    if parsed_pid:
        project_id, pipeline_id = parsed_project, parsed_pid
    text = _render("diagnose-pipeline.md", project_id=project_id, pipeline_id=pipeline_id)
    return [
        Message(role="user", content=text),
        Message(
            role="assistant",
            content=(
                f"I'll diagnose pipeline {pipeline_id} in project {project_id}. "
                "Let me fetch the pipeline details and check for failed jobs."
            ),
        ),
    ]


@mcp.prompt(tags={"gitlab", "release"})
def prepare_release(project_id: str, tag_name: str, ref: str = "main") -> list[Message]:
    """Prepare a release — compare commits since last tag, draft changelog,
    create tag and release.

    project_id accepts a full GitLab project URL.
    """
    project_id = _parse_gitlab_project_url(project_id)
    text = _render("prepare-release.md", project_id=project_id, tag_name=tag_name, ref=ref)
    return [
        Message(role="user", content=text),
        Message(
            role="assistant",
            content=(
                f"I'll prepare release {tag_name} from {ref} in project {project_id}. "
                "Let me find the previous tag and compare commits."
            ),
        ),
    ]


@mcp.prompt(tags={"gitlab", "settings"})
def setup_branch_protection(project_id: str) -> list[Message]:
    """Set up branch protection — review settings, configure merge method,
    and create approval rules.

    project_id accepts a full GitLab project URL.
    """
    project_id = _parse_gitlab_project_url(project_id)
    text = _render("setup-branch-protection.md", project_id=project_id)
    return [
        Message(role="user", content=text),
        Message(
            role="assistant",
            content=(
                f"I'll help set up branch protection for project {project_id}. "
                "Let me review the current project settings and approval configuration."
            ),
        ),
    ]


@mcp.prompt(tags={"gitlab", "issues"})
def triage_issues(project_id: str, label: str = "") -> list[Message]:
    """Triage open issues — categorize, prioritize, identify duplicates,
    and suggest labels.

    project_id accepts a full GitLab project URL.
    """
    project_id = _parse_gitlab_project_url(project_id)
    text = _render("triage-issues.md", project_id=project_id, label=label)
    return [
        Message(role="user", content=text),
        Message(
            role="assistant",
            content=(
                f"I'll triage open issues in project {project_id}"
                + (f' filtered by label "{label}"' if label else "")
                + ". Let me start by listing the open issues."
            ),
        ),
    ]


# ════════════════════════════════════════════════════════════════════
# Startup validation
# ════════════════════════════════════════════════════════════════════

_PROMPT_FILES = [
    "review-mr.md",
    "diagnose-pipeline.md",
    "prepare-release.md",
    "setup-branch-protection.md",
    "triage-issues.md",
]


def _validate_prompts() -> None:
    """Verify all expected prompt files exist at import time."""
    _dir = Path(_PROMPTS_DIR)
    missing = [f for f in _PROMPT_FILES if not (_dir / f).is_file()]
    if missing:
        msg = f"Missing prompt files (packaging error): {missing}"
        raise RuntimeError(msg)


_validate_prompts()
