"""Boot the server through its real lifespan and check what it registers.

The count of ``@mcp.tool`` / ``@mcp.resource`` / ``@mcp.prompt`` decorators is read
from ``src/`` at test time, so a tool that silently drops out of the registry (a
decorator that breaks introspection, a module that stops being imported) fails here
rather than in a client.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

from fastmcp import Client

from mcp_gitlab.servers.gitlab import mcp

SRC = Path(__file__).resolve().parents[2] / "src"


def _decorators(kind: str) -> int:
    pattern = re.compile(rf"^@mcp\.{kind}\b", re.M)
    return sum(len(pattern.findall(p.read_text())) for p in SRC.rglob("*.py"))


async def test_real_lifespan_registers_everything(monkeypatch):
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "test-token")
    monkeypatch.delenv("GITLAB_READ_ONLY", raising=False)
    # main() imports these for their decorators; do the same here.
    for module in ("mcp_gitlab.servers.resources", "mcp_gitlab.servers.prompts"):
        importlib.import_module(module)

    async with Client(mcp) as client:
        assert len(await client.list_tools()) == _decorators("tool")
        resources = await client.list_resources()
        assert len(resources) == _decorators("resource") > 0
        assert len(await client.list_prompts()) == _decorators("prompt") > 0
        for resource in resources:
            (content,) = await client.read_resource(resource.uri)
            assert content.text.lstrip().startswith("#"), resource.uri
