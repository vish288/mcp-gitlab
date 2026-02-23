"""MCP resources for GitLab — curated rules and guides for Git/GitLab workflows."""

from __future__ import annotations

from pathlib import Path

from .gitlab import mcp

_RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"


def _load(filename: str) -> str:
    """Load a resource markdown file from the resources directory."""
    return (_RESOURCES_DIR / filename).read_text(encoding="utf-8")


# ════════════════════════════════════════════════════════════════════
# Rules
# ════════════════════════════════════════════════════════════════════


@mcp.resource(
    "resource://rules/gitlab-ci",
    name="GitLab CI/CD Pipeline Patterns",
    description=(
        "Workflow rules, DAG with needs, caching, artifact expiry, "
        "secrets, environment tracking, and anti-patterns for .gitlab-ci.yml"
    ),
    mime_type="text/markdown",
    tags={"rule", "gitlab", "ci"},
)
def gitlab_ci_rules() -> str:
    """GitLab CI/CD pipeline authoring patterns and anti-patterns."""
    return _load("gitlab-ci.md")


@mcp.resource(
    "resource://rules/git-workflow",
    name="Git Workflow Standards",
    description=(
        "Trunk-based development, branch naming, rebase discipline, "
        "safe force-push, feature flags, and merge strategy"
    ),
    mime_type="text/markdown",
    tags={"rule", "gitlab", "git"},
)
def git_workflow_rules() -> str:
    """Git workflow standards for trunk-based development."""
    return _load("git-workflow.md")


@mcp.resource(
    "resource://rules/mr-hygiene",
    name="Merge Request Best Practices",
    description=(
        "MR size limits, description template, author/reviewer responsibilities, "
        "thread resolution, approval rules, and merge readiness"
    ),
    mime_type="text/markdown",
    tags={"rule", "gitlab", "merge-request"},
)
def mr_hygiene_rules() -> str:
    """Merge request best practices and review etiquette."""
    return _load("mr-hygiene.md")


@mcp.resource(
    "resource://rules/conventional-commits",
    name="Conventional Commits Spec",
    description=(
        "Commit types, breaking changes, footers, scope conventions, "
        "and semantic-release integration"
    ),
    mime_type="text/markdown",
    tags={"rule", "gitlab", "git", "commits"},
)
def conventional_commits_rules() -> str:
    """Conventional Commits specification and semantic-release mapping."""
    return _load("conventional-commits.md")


# ════════════════════════════════════════════════════════════════════
# Guides
# ════════════════════════════════════════════════════════════════════


@mcp.resource(
    "resource://guides/code-review",
    name="Code Review Standards",
    description=(
        "Review priority order (Google Engineering Practices), "
        "Conventional Comments labels, turnaround expectations, and anti-patterns"
    ),
    mime_type="text/markdown",
    tags={"guide", "gitlab", "review"},
)
def code_review_guide() -> str:
    """Code review standards with Conventional Comments and priority order."""
    return _load("code-review.md")


@mcp.resource(
    "resource://guides/codeowners",
    name="GitLab CODEOWNERS Reference",
    description=(
        "CODEOWNERS syntax, sections with required approvals, "
        "optional sections, owner types, and governance patterns"
    ),
    mime_type="text/markdown",
    tags={"guide", "gitlab", "codeowners"},
)
def codeowners_guide() -> str:
    """GitLab CODEOWNERS file reference and governance."""
    return _load("codeowners.md")
