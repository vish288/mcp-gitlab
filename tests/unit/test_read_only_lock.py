"""Locked read-only: the deployer-set MCP_READ_ONLY switch.

A truthy (or unrecognised) MCP_READ_ONLY or the per-server GITLAB_READ_ONLY alias
(or --read-only, which writes the alias) locks the server read-only for the process.
The lock hides every write tool and write-workflow prompt from tools/list and
prompts/list, so a client cannot call or re-enable them; the ``_check_write`` guard
stays as defence in depth. A falsy value never unlocks; it is the default. Values are
stripped and an unrecognised value fails closed (locks) with a WARNING.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from click.testing import CliRunner
from fastmcp import Client

# Importing the prompts/resources modules registers their decorators; without this
# the prompt-visibility assertions below would be vacuous and order-dependent.
import mcp_gitlab.servers.prompts  # noqa: E402, F401
import mcp_gitlab.servers.resources  # noqa: E402, F401
from mcp_gitlab import main
from mcp_gitlab.config import GitLabConfig
from mcp_gitlab.exceptions import GitLabWriteDisabledError
from mcp_gitlab.servers.gitlab import _check_write, _err, _lock_read_only, mcp

_SRC = Path(__file__).resolve().parents[2] / "src" / "mcp_gitlab"
_SERVER_SRC = _SRC / "servers" / "gitlab.py"


def _write_guarded_names() -> set[str]:
    """Write tools by their guard, read from source: any ``@mcp.tool`` whose chunk
    carries ``@tool_result(write=True)`` or an inline ``_check_write(ctx)`` call
    (``gitlab_merge_mr_sequence`` keeps its own expected-error handler)."""
    src = _SERVER_SRC.read_text(encoding="utf-8")
    guarded: set[str] = set()
    for chunk in re.split(r"\n(?=@mcp\.tool\()", src):
        if not chunk.startswith("@mcp.tool("):
            continue  # the preamble before the first tool, not a registration
        name = re.search(r"async def (\w+)\(", chunk)
        if name and ("@tool_result(write=True)" in chunk or "_check_write(ctx)" in chunk):
            guarded.add(name.group(1))
    return guarded


def _clear_read_only(monkeypatch) -> None:
    monkeypatch.delenv("MCP_READ_ONLY", raising=False)
    monkeypatch.delenv("GITLAB_READ_ONLY", raising=False)


@pytest.fixture
def lock_mcp():
    """Lock the shared ``mcp`` in-process, yielding the ``_lock_read_only`` caller and
    restoring visibility and instructions afterwards (the lock keys its idempotency off the
    restored instructions sentence, so there is no separate flag to reset)."""
    tx = len(mcp._transforms)
    instructions = mcp.instructions

    def lock(**kwargs: Any) -> object:
        _lock_read_only(mcp, **kwargs)
        return mcp

    try:
        yield lock
    finally:
        del mcp._transforms[tx:]
        mcp.instructions = instructions


# ── config: OR semantics, fail-closed, warnings ───────────────────────


def test_mcp_read_only_env_locks(monkeypatch):
    _clear_read_only(monkeypatch)
    monkeypatch.setenv("MCP_READ_ONLY", "true")
    assert GitLabConfig.from_env().read_only is True


def test_alias_false_cannot_unlock(monkeypatch, caplog):
    _clear_read_only(monkeypatch)
    monkeypatch.setenv("MCP_READ_ONLY", "true")
    monkeypatch.setenv("GITLAB_READ_ONLY", "false")
    with caplog.at_level(logging.WARNING, logger="mcp_gitlab.config"):
        config = GitLabConfig.from_env()
    assert config.read_only is True
    assert any("GITLAB_READ_ONLY" in r.message for r in caplog.records)


def test_mcp_false_cannot_unlock_alias(monkeypatch, caplog):
    _clear_read_only(monkeypatch)
    monkeypatch.setenv("GITLAB_READ_ONLY", "true")
    monkeypatch.setenv("MCP_READ_ONLY", "false")
    with caplog.at_level(logging.WARNING, logger="mcp_gitlab.config"):
        config = GitLabConfig.from_env()
    assert config.read_only is True
    assert any("MCP_READ_ONLY" in r.message for r in caplog.records)


def test_no_falsy_warning_when_unlocked(monkeypatch, caplog):
    _clear_read_only(monkeypatch)
    monkeypatch.setenv("MCP_READ_ONLY", "false")
    with caplog.at_level(logging.WARNING, logger="mcp_gitlab.config"):
        config = GitLabConfig.from_env()
    assert config.read_only is False
    assert caplog.records == []


# Full value table (on/off/empty/whitespace/"2"/TRUE): stripped, case-insensitive;
# only a clearly falsy value unlocks, everything else (truthy or unrecognised) locks.
@pytest.mark.parametrize("value", ["", "  ", "0", "no", "off", "FALSE", " false "])
def test_falsey_values_do_not_lock(monkeypatch, value):
    _clear_read_only(monkeypatch)
    monkeypatch.setenv("MCP_READ_ONLY", value)
    assert GitLabConfig.from_env().read_only is False


@pytest.mark.parametrize("value", ["1", "yes", "on", "TRUE", " true "])
def test_truthy_values_lock(monkeypatch, value):
    _clear_read_only(monkeypatch)
    monkeypatch.setenv("MCP_READ_ONLY", value)
    assert GitLabConfig.from_env().read_only is True


@pytest.mark.parametrize("value", ["maybe", "2", "enabled"])
def test_unrecognised_value_fails_closed(monkeypatch, caplog, value):
    """A non-empty value that is neither truthy nor falsy locks (fails closed) and warns."""
    _clear_read_only(monkeypatch)
    monkeypatch.setenv("MCP_READ_ONLY", value)
    with caplog.at_level(logging.WARNING, logger="mcp_gitlab.config"):
        config = GitLabConfig.from_env()
    assert config.read_only is True
    assert any(value in r.message and "MCP_READ_ONLY" in r.message for r in caplog.records)


def test_no_read_only_flag_rejected():
    """`--no-read-only` does not exist (plain is_flag); click rejects it, exit 2."""
    result = CliRunner().invoke(main, ["--no-read-only"])
    assert result.exit_code == 2
    assert "no such option" in result.output.lower()


# ── lock: hide write tools and write-workflow prompts ─────────────────


async def test_locked_lists_no_write_tools(readonly_client):
    client, _router = readonly_client
    tools = await client.list_tools()
    assert all(t.annotations is None or t.annotations.read_only_hint is not False for t in tools)
    assert not ({t.name for t in tools} & _write_guarded_names())


async def test_hidden_set_equals_write_tag_set_equals_guard_set(readonly_client):
    # ``mcp._list_tools()`` is the full registry (visibility transforms apply only at
    # the client/protocol layer); the locked client gives what survives the hide.
    all_tools = await mcp._list_tools()
    tag_set = {t.name for t in all_tools if "write" in t.tags}
    assert tag_set == _write_guarded_names()

    client, _router = readonly_client
    visible = {t.name for t in await client.list_tools()}
    hidden = {t.name for t in all_tools} - visible
    assert hidden == tag_set


async def test_locked_hides_write_workflow_prompts(readonly_client):
    client, _router = readonly_client
    names = {p.name for p in await client.list_prompts()}
    assert "approve_mr" not in names
    assert "prepare_release" not in names
    assert "setup_branch_protection" not in names
    assert "review_mr" not in names
    assert "triage_issues" not in names
    assert "diagnose_pipeline" in names  # read-only diagnosis workflow stays


async def test_call_hidden_write_tool_is_unknown_tool(readonly_client):
    client, _router = readonly_client
    result = await client.call_tool("gitlab_create_project", {"name": "x"}, raise_on_error=False)
    assert result.is_error is True
    assert "unknown tool" in result.content[0].text.lower()


async def test_real_lifespan_boot_locks(monkeypatch):
    """Boot the real lifespan with ``MCP_READ_ONLY=true`` via a real Client: write tools
    are absent and the instructions carry the locked-read-only sentence. Snapshot/restore
    the shared ``mcp`` so this does not leak into other tests."""
    _clear_read_only(monkeypatch)
    monkeypatch.setenv("GITLAB_URL", "https://gl.test")
    monkeypatch.setenv("GITLAB_TOKEN", "t")
    monkeypatch.setenv("MCP_READ_ONLY", "true")
    tx = len(mcp._transforms)
    instructions = mcp.instructions
    try:
        async with Client(mcp) as client:
            tools = {t.name for t in await client.list_tools()}
            assert not (tools & _write_guarded_names())
        assert "locked read-only" in (mcp.instructions or "")
    finally:
        del mcp._transforms[tx:]
        mcp.instructions = instructions


async def test_locked_in_oauth_mode_lists_no_write_tools(monkeypatch):
    """The lock is unconditional on auth mode: booting the real lifespan with
    GITLAB_AUTH=oauth (its config stubbed so ``validate`` passes) and MCP_READ_ONLY=true
    still hides every write tool by tag."""
    _clear_read_only(monkeypatch)
    monkeypatch.setenv("GITLAB_URL", "https://gl.test")
    monkeypatch.setenv("GITLAB_AUTH", "oauth")
    monkeypatch.setenv("GITLAB_OAUTH_CLIENT_ID", "app")
    monkeypatch.setenv("GITLAB_OAUTH_CLIENT_SECRET", "s3cret-s3cret-s3cret")  # noqa: S105
    monkeypatch.setenv("GITLAB_OAUTH_BASE_URL", "https://mcp.test")
    monkeypatch.setenv("MCP_READ_ONLY", "true")
    tx = len(mcp._transforms)
    instructions = mcp.instructions
    try:
        async with Client(mcp) as client:
            tools = {t.name for t in await client.list_tools()}
            assert not (tools & _write_guarded_names())
    finally:
        del mcp._transforms[tx:]
        mcp.instructions = instructions


def test_guard_still_refuses_when_not_hidden():
    """Defence in depth: the guard raises for a write call even if a client reaches a
    write tool (cached list, a future untagged tool). The envelope carries the
    deploy-owned-read-only hint."""
    ctx = SimpleNamespace(
        lifespan_context={"config": GitLabConfig(url="u", token="t", read_only=True)}  # noqa: S106
    )
    with pytest.raises(GitLabWriteDisabledError):
        _check_write(ctx)
    assert "read-only" in _err(GitLabWriteDisabledError())["hint"].lower()


@pytest.mark.parametrize("source", ["MCP_READ_ONLY", "GITLAB_READ_ONLY"])
def test_locked_instructions_and_log(lock_mcp, caplog, source):
    """The lock appends the instructions sentence and logs LOCKED naming its sources.
    ``--read-only`` locks by setting GITLAB_READ_ONLY, so it is named through that alias."""
    with caplog.at_level(logging.INFO, logger="mcp_gitlab.servers.gitlab"):
        server = lock_mcp(sources=[source])
    assert "locked read-only" in (server.instructions or "")
    assert any("LOCKED" in r.message and source in r.message for r in caplog.records)


def test_src_never_re_enables_or_mutates_visibility():
    """``src/`` must not re-enable components, mutate the transform list, or clear the lock
    after config is final. The lock is one ``disable`` at boot and nothing undoes it."""
    banned = (
        r"\.enable\(",
        r"enable_components\(",
        r"disable_components\(",
        r"reset_visibility\(",
        r"add_transform\(",
        r"\._transforms",
        r"read_only\s*=\s*False",
    )
    for path in _SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in banned:
            assert not re.search(pattern, text), f"{pattern} found in {path}"
