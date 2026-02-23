"""Tests for MCP resource registration and content."""

from __future__ import annotations

from mcp_gitlab.servers.resources import (
    _CODE_REVIEW_CONTENT,
    _CODEOWNERS_CONTENT,
    _CONVENTIONAL_COMMITS_CONTENT,
    _GIT_WORKFLOW_CONTENT,
    _GITLAB_CI_CONTENT,
    _MR_HYGIENE_CONTENT,
    code_review_guide,
    codeowners_guide,
    conventional_commits_rules,
    git_workflow_rules,
    gitlab_ci_rules,
    mr_hygiene_rules,
)

EXPECTED_RESOURCES = {
    "resource://rules/gitlab-ci": {
        "name": "GitLab CI/CD Pipeline Patterns",
        "fn": gitlab_ci_rules,
        "content_var": _GITLAB_CI_CONTENT,
    },
    "resource://rules/git-workflow": {
        "name": "Git Workflow Standards",
        "fn": git_workflow_rules,
        "content_var": _GIT_WORKFLOW_CONTENT,
    },
    "resource://rules/mr-hygiene": {
        "name": "Merge Request Best Practices",
        "fn": mr_hygiene_rules,
        "content_var": _MR_HYGIENE_CONTENT,
    },
    "resource://rules/conventional-commits": {
        "name": "Conventional Commits Spec",
        "fn": conventional_commits_rules,
        "content_var": _CONVENTIONAL_COMMITS_CONTENT,
    },
    "resource://guides/code-review": {
        "name": "Code Review Standards",
        "fn": code_review_guide,
        "content_var": _CODE_REVIEW_CONTENT,
    },
    "resource://guides/codeowners": {
        "name": "GitLab CODEOWNERS Reference",
        "fn": codeowners_guide,
        "content_var": _CODEOWNERS_CONTENT,
    },
}


class TestResourceRegistration:
    """Verify resources are importable and return content."""

    def test_resource_count(self) -> None:
        """All 6 resources are defined."""
        assert len(EXPECTED_RESOURCES) == 6

    def test_each_resource_returns_content(self) -> None:
        """Each resource function returns its content constant."""
        for uri, info in EXPECTED_RESOURCES.items():
            result = info["fn"]()
            assert result == info["content_var"], f"{uri} content mismatch"

    def test_content_is_non_empty_markdown(self) -> None:
        """Each content constant is non-empty and starts with a markdown heading."""
        for uri, info in EXPECTED_RESOURCES.items():
            content = info["content_var"]
            assert len(content) > 100, f"{uri} content too short"
            assert content.lstrip().startswith("#"), f"{uri} should start with markdown heading"

    def test_resource_uris_are_unique(self) -> None:
        """No duplicate URIs."""
        uris = list(EXPECTED_RESOURCES.keys())
        assert len(uris) == len(set(uris))

    def test_resource_functions_have_metadata(self) -> None:
        """Each function has the __fastmcp__ attribute from the decorator."""
        for uri, info in EXPECTED_RESOURCES.items():
            fn = info["fn"]
            assert hasattr(fn, "__fastmcp__"), f"{uri} function missing __fastmcp__ metadata"
