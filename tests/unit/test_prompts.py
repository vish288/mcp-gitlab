"""Tests for MCP prompt registration and content."""

from __future__ import annotations

import pytest

from mcp_gitlab.servers.prompts import (
    _PROMPTS_DIR,
    _load_prompt,
    diagnose_pipeline,
    prepare_release,
    review_mr,
    setup_branch_protection,
    triage_issues,
)

EXPECTED_PROMPTS = {
    "review_mr": {
        "fn": review_mr,
        "file": "review-mr.md",
        "args": {"project_id": "123", "mr_iid": "42"},
    },
    "diagnose_pipeline": {
        "fn": diagnose_pipeline,
        "file": "diagnose-pipeline.md",
        "args": {"project_id": "123", "pipeline_id": "999"},
    },
    "prepare_release": {
        "fn": prepare_release,
        "file": "prepare-release.md",
        "args": {"project_id": "123", "tag_name": "v1.0.0", "ref": "main"},
    },
    "setup_branch_protection": {
        "fn": setup_branch_protection,
        "file": "setup-branch-protection.md",
        "args": {"project_id": "123"},
    },
    "triage_issues": {
        "fn": triage_issues,
        "file": "triage-issues.md",
        "args": {"project_id": "123", "label": "bug"},
    },
}

PROMPT_FILES = [info["file"] for info in EXPECTED_PROMPTS.values()]


class TestPromptFiles:
    """Verify prompt .md files exist and are valid."""

    def test_prompts_dir_exists(self) -> None:
        assert _PROMPTS_DIR.is_dir(), f"Prompts directory missing: {_PROMPTS_DIR}"

    def test_all_files_exist(self) -> None:
        for filename in PROMPT_FILES:
            path = _PROMPTS_DIR / filename
            assert path.is_file(), f"Missing prompt file: {path}"

    def test_load_returns_content(self) -> None:
        for filename in PROMPT_FILES:
            content = _load_prompt(filename)
            assert len(content) > 100, f"{filename} too short ({len(content)} chars)"

    def test_content_starts_with_heading(self) -> None:
        for filename in PROMPT_FILES:
            content = _load_prompt(filename)
            assert content.lstrip().startswith("#"), (
                f"{filename} should start with markdown heading"
            )

    def test_no_python_escape_artifacts(self) -> None:
        """Ensure .md files don't contain Python string artifacts."""
        for filename in PROMPT_FILES:
            content = _load_prompt(filename)
            assert '"""' not in content, f"{filename} contains triple-quote artifact"


class TestLoadPromptSecurity:
    """Verify _load_prompt() rejects path traversal attempts."""

    def test_rejects_directory_traversal(self) -> None:
        with pytest.raises(ValueError, match="Invalid prompt filename"):
            _load_prompt("../../../etc/passwd")

    def test_rejects_forward_slash(self) -> None:
        with pytest.raises(ValueError, match="Invalid prompt filename"):
            _load_prompt("subdir/file.md")

    def test_rejects_backslash(self) -> None:
        with pytest.raises(ValueError, match="Invalid prompt filename"):
            _load_prompt("subdir\\file.md")

    def test_rejects_dotdot_only(self) -> None:
        with pytest.raises(ValueError, match="Invalid prompt filename"):
            _load_prompt("..")


class TestPromptRegistration:
    """Verify prompts are registered and return valid messages."""

    def test_prompt_count(self) -> None:
        assert len(EXPECTED_PROMPTS) == 5

    def test_each_prompt_returns_messages(self) -> None:
        for name, info in EXPECTED_PROMPTS.items():
            result = info["fn"](**info["args"])
            assert isinstance(result, list), f"{name} should return a list"
            assert len(result) == 2, f"{name} should return 2 messages"

    def test_first_message_is_user_role(self) -> None:
        for name, info in EXPECTED_PROMPTS.items():
            result = info["fn"](**info["args"])
            assert result[0].role == "user", f"{name} first message should be user role"

    def test_second_message_is_assistant_role(self) -> None:
        for name, info in EXPECTED_PROMPTS.items():
            result = info["fn"](**info["args"])
            assert result[1].role == "assistant", f"{name} second message should be assistant role"

    def test_args_are_interpolated(self) -> None:
        result = review_mr(project_id="456", mr_iid="78")
        assert "456" in result[0].content.text
        assert "78" in result[0].content.text
        assert "78" in result[1].content.text

    def test_prepare_release_default_ref(self) -> None:
        result = prepare_release(project_id="123", tag_name="v2.0.0")
        assert "main" in result[0].content.text

    def test_triage_issues_empty_label(self) -> None:
        result = triage_issues(project_id="123", label="")
        assert isinstance(result, list)
        assert len(result) == 2

    def test_prompt_functions_have_metadata(self) -> None:
        for name, info in EXPECTED_PROMPTS.items():
            fn = info["fn"]
            assert hasattr(fn, "__fastmcp__"), f"{name} function missing __fastmcp__ metadata"


class TestPromptRendering:
    """Verify prompts render via FastMCP."""

    @pytest.mark.asyncio
    async def test_list_prompts(self) -> None:
        from mcp_gitlab.servers.gitlab import mcp

        prompts = await mcp.list_prompts()
        prompt_names = {p.name for p in prompts}
        for name in EXPECTED_PROMPTS:
            assert name in prompt_names, f"Prompt {name} not listed"

    @pytest.mark.asyncio
    async def test_render_review_mr(self) -> None:
        from mcp_gitlab.servers.gitlab import mcp

        result = await mcp.render_prompt(
            "review_mr", arguments={"project_id": "123", "mr_iid": "42"}
        )
        assert len(result.messages) == 2
        assert "42" in result.messages[0].content.text
