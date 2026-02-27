"""Tests for MCP resource registration and content."""

from __future__ import annotations

from pathlib import Path

from mcp_gitlab.servers.resources import (
    _RESOURCES_DIR,
    _load,
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
        "file": "gitlab-ci.md",
    },
    "resource://rules/git-workflow": {
        "name": "Git Workflow Standards",
        "fn": git_workflow_rules,
        "file": "git-workflow.md",
    },
    "resource://rules/mr-hygiene": {
        "name": "Merge Request Best Practices",
        "fn": mr_hygiene_rules,
        "file": "mr-hygiene.md",
    },
    "resource://rules/conventional-commits": {
        "name": "Conventional Commits Spec",
        "fn": conventional_commits_rules,
        "file": "conventional-commits.md",
    },
    "resource://guides/code-review": {
        "name": "Code Review Standards",
        "fn": code_review_guide,
        "file": "code-review.md",
    },
    "resource://guides/codeowners": {
        "name": "GitLab CODEOWNERS Reference",
        "fn": codeowners_guide,
        "file": "codeowners.md",
    },
}

RESOURCE_FILES = [
    "gitlab-ci.md",
    "git-workflow.md",
    "mr-hygiene.md",
    "conventional-commits.md",
    "code-review.md",
    "codeowners.md",
]


class TestResourceFiles:
    """Verify resource .md files exist and are valid."""

    def test_resources_dir_exists(self) -> None:
        assert Path(_RESOURCES_DIR).is_dir(), f"Resources directory missing: {_RESOURCES_DIR}"

    def test_all_files_exist(self) -> None:
        for filename in RESOURCE_FILES:
            path = Path(_RESOURCES_DIR) / filename
            assert path.is_file(), f"Missing resource file: {path}"

    def test_load_returns_content(self) -> None:
        for filename in RESOURCE_FILES:
            content = _load(filename)
            assert len(content) > 100, f"{filename} too short ({len(content)} chars)"

    def test_content_starts_with_heading(self) -> None:
        for filename in RESOURCE_FILES:
            content = _load(filename)
            assert content.lstrip().startswith("#"), (
                f"{filename} should start with markdown heading"
            )

    def test_no_python_escape_artifacts(self) -> None:
        """Ensure extracted .md files don't contain Python string artifacts."""
        for filename in RESOURCE_FILES:
            content = _load(filename)
            assert '"""' not in content, f"{filename} contains triple-quote artifact"


class TestLoadSecurity:
    """Verify _load() rejects path traversal attempts."""

    def test_rejects_directory_traversal(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="Invalid filename"):
            _load("../../../etc/passwd")

    def test_rejects_forward_slash(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="Invalid filename"):
            _load("subdir/file.md")

    def test_rejects_backslash(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="Invalid filename"):
            _load("subdir\\file.md")

    def test_rejects_dotdot_only(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="Invalid filename"):
            _load("..")


class TestResourceRegistration:
    """Verify resources are importable and return content."""

    def test_resource_count(self) -> None:
        assert len(EXPECTED_RESOURCES) == 6

    def test_each_resource_returns_file_content(self) -> None:
        for uri, info in EXPECTED_RESOURCES.items():
            result = info["fn"]()
            expected = _load(info["file"])
            assert result == expected, f"{uri} content mismatch"

    def test_resource_uris_are_unique(self) -> None:
        uris = list(EXPECTED_RESOURCES.keys())
        assert len(uris) == len(set(uris))

    def test_resource_functions_have_metadata(self) -> None:
        for uri, info in EXPECTED_RESOURCES.items():
            fn = info["fn"]
            assert hasattr(fn, "__fastmcp__"), f"{uri} function missing __fastmcp__ metadata"
