# mcp-gitlab — spec for the test-confidence → error-contract initiative

## Objective

Make the suite prove tool behaviour through the real MCP server, gate it in CI
(done, 0.10.3), then collapse the 83 identical `try/except` tool bodies into one
decorator that returns expected API failures as JSON and raises everything else
as a real MCP `isError` (done, 0.11.0). No public tool, resource or prompt
changes shape. gitlab has no `dedup` branch — its drift items were fixed in #77
or left as `[ticket-only]`.

## Commands

```
uv run pytest -q                                   # network marker excluded
uv run pytest -q --cov --cov-report=term-missing   # src/ only, gate 98
uv run ruff check . && uv run ruff format --check .
uv build
```

## Structure

```
src/mcp_gitlab/
  client.py            GitLabClient: 5 verbs (get, get_paged, post, put, delete)
                       over _request; _raise_for_status; _parse_body; + 82 thin
                       path-building methods, one caller each (INT-GL-010, deferred)
  config.py            GitLabConfig dataclass, from_env(), validate()
  exceptions.py        GitLabError > GitLabApiError > {Auth, NotFound}; GitLabWriteDisabledError
  servers/gitlab.py    FastMCP `mcp`, lifespan, the helpers below, and all 83 @mcp.tool
                       tool_result, _ok, _paginated, _err, _params, _check_write, _get_client
  servers/_helpers.py  _load_file + the three URL parsers
  servers/resources.py 7 resources     servers/prompts.py  6 prompts
  servers/__init__.py  imports the three modules so registration happens on load
tests/
  conftest.py          client, mock_api, tool_client, readonly_client fixtures
  unit/test_tools.py   per-tool unit layer (real Client + respx, mocked routes)
  unit/test_tool_contract.py   83 rows, one per tool: request shape + forced failure
  unit/test_server_assembly.py real lifespan; list_tools() == decorators scanned from src/
  unit/test_exceptions.py      _err envelope table, one row per exception type
```

## Code style

```python
@mcp.tool(tags={"gitlab", "projects", "read"}, annotations={"readOnlyHint": True, ...})
@tool_result
async def gitlab_get_project(ctx: Context, project_id: Annotated[str, Field(...)]) -> str:
    """One-line summary. Then when to use it and what it does NOT return."""
    return _ok(await _get_client(ctx).get_project(project_id))
```

Ruff: E F B W I N UP S C4 EM ISC, line length 100, py310. No `# noqa`, no
`# type: ignore`.

## Testing strategy

1. Unit layer (`test_tools.py`): call through a real `fastmcp.Client(mcp)` whose
   lifespan is swapped for a `GitLabClient` pointed at respx; mock each route.
2. Contract table (`test_tool_contract.py`): one `(name, args, method, path,
   query, json_body)` row per tool. `test_request_shape` pins the wire request;
   `test_forced_failure` drives the same route to 404 so every `except` arm runs
   and its `_err` envelope is checked. `test_every_tool_has_a_row` keeps it honest.
3. Assembly: real lifespan via env; live `list_tools()` count equals the
   `@mcp.tool` decorators scanned from `src/`; resources and prompts non-empty.

Rows are derived by reading each tool's `GitLabClient` call, not guessed — that
is what makes the deferred one-caller-client-method deletion (INT-GL-010) safe.

## Boundaries

- `contract` branch touches `servers/gitlab.py` only; `exceptions.py` untouched.
- Never edit `.github/workflows/release.yml` or `publish.yml`.
- No live-API tests (`-m network` excluded by default). No new runtime deps.
- Coverage omits `__init__`/`__main__` (`pyproject.toml`); mirror if that moves.

## Success criteria

- harness: every tool asserts its wire request; `except` arms execute; CI red on
  a `--cov-fail-under` breach.
- contract: unexpected exceptions surface as MCP `isError: true` (logged with
  traceback); expected API errors (401/403/404, 409/422/429, read-only) keep the
  JSON envelope. `_params` forwards explicit `False`/`0`/`""` that the old
  truthiness guards dropped. `access_level` is case-sensitive via the `Literal`
  enum, validated once at the boundary instead of two hand-rolled blocks.
- Every `[fix]` ticket at `fixed` with a `gh:` number; `[ticket-only]` filed.

State (2026-09-26, v0.11.0): 83 tools, 408 tests, `servers/gitlab.py` 510
statements at 100%, src/ coverage 99%.

## Outcome

- Released versions: 0.10.3 (harness), 0.11.0 (contract). No dedup branch.
- Closed issues: #75, #76, #77, #78, #79, and #80's tests/-side items
  (its src/ items remain open).
