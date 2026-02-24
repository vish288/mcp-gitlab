"""MCP prompts — multi-tool workflow templates for GitLab operations."""

from __future__ import annotations

from pathlib import Path

from fastmcp.prompts.prompt import Message

from .gitlab import mcp

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "resources" / "prompts"


def _load_prompt(filename: str) -> str:
    """Load a prompt markdown file from the prompts directory."""
    if "/" in filename or "\\" in filename or ".." in filename:
        msg = f"Invalid prompt filename: {filename}"
        raise ValueError(msg)
    path = _PROMPTS_DIR / filename
    if not path.resolve().is_relative_to(_PROMPTS_DIR.resolve()):
        msg = f"Invalid prompt filename: {filename}"
        raise ValueError(msg)
    return path.read_text(encoding="utf-8")


@mcp.prompt(tags={"gitlab", "review"})
def review_mr(project_id: str, mr_iid: str) -> list[Message]:
    """Review a GitLab merge request — fetch details, check pipeline, review
    changes, and write discussion comments."""
    text = _load_prompt("review-mr.md").format(project_id=project_id, mr_iid=mr_iid)
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
def diagnose_pipeline(project_id: str, pipeline_id: str) -> list[Message]:
    """Diagnose a failed CI/CD pipeline — identify failed jobs, get logs,
    analyze errors, and suggest fixes."""
    text = _load_prompt("diagnose-pipeline.md").format(
        project_id=project_id, pipeline_id=pipeline_id
    )
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
    create tag and release."""
    text = _load_prompt("prepare-release.md").format(
        project_id=project_id, tag_name=tag_name, ref=ref
    )
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
    and create approval rules."""
    text = _load_prompt("setup-branch-protection.md").format(project_id=project_id)
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
    and suggest labels."""
    text = _load_prompt("triage-issues.md").format(project_id=project_id, label=label)
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
