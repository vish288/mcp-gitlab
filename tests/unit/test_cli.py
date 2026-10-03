"""CLI entry point tests."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from mcp_gitlab import main


def test_sse_deprecation_warning():
    runner = CliRunner()
    with (
        patch("mcp_gitlab.asyncio.run") as mock_run,
        patch.dict(
            "os.environ",
            {"GITLAB_URL": "https://gitlab.example.com", "GITLAB_TOKEN": "test-token"},
        ),
    ):
        result = runner.invoke(main, ["--transport", "sse"])
        assert result.exit_code == 0
        assert (
            "Warning: --transport sse uses the HTTP+SSE transport, deprecated in MCP 2026-07-28"
            in result.output
        )
        assert "Use --transport streamable-http" in result.output
        mock_run.assert_called_once()
