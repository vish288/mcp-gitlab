# mcp-gitlab — Agent Context

MCP server providing 76 tools for the GitLab REST API v4.

## Architecture

- **Entry point**: `src/mcp_gitlab/__init__.py` — click CLI, loads env, runs FastMCP server
- **Client**: `src/mcp_gitlab/client.py` — async httpx client with all GitLab API methods
- **Tools**: `src/mcp_gitlab/servers/gitlab.py` — all FastMCP tool registrations
- **Resources**: `src/mcp_gitlab/servers/resources.py` — 6 MCP resources (workflow guides)
- **Prompts**: `src/mcp_gitlab/servers/prompts.py` — 5 MCP prompts (multi-tool workflows)
- **Config**: `src/mcp_gitlab/config.py` — `GitLabConfig` dataclass from env vars
- **Exceptions**: `src/mcp_gitlab/exceptions.py` — `GitLabApiError`, `GitLabAuthError`, etc.
- **Tests**: `tests/unit/test_tools.py` — 120+ tool-level tests via FastMCP test client

## Patterns

- All tools are `async def` returning JSON strings
- Error handling: try/except wrapping every tool, returning `{"error": ...}` JSON
- Write access control: `_check_write(ctx)` raises `GitLabWriteDisabledError` when `GITLAB_READ_ONLY=true`
- Tags: every tool tagged with `{"gitlab", "<category>", "read"|"write"}`
- Parameters use `Annotated[type, Field(description=...)]`
- Client uses httpx with `PRIVATE-TOKEN` header auth
- Project/group IDs can be numeric or URL-encoded paths

## MCP Compliance Rules

### Tool Annotations (MANDATORY)
Every tool MUST have `annotations={}` with at minimum `readOnlyHint`.
- Read tools: `annotations={"readOnlyHint": True, "idempotentHint": True}`
- Non-destructive write tools: `annotations={"readOnlyHint": False}`
- Destructive write tools: `annotations={"destructiveHint": True, "readOnlyHint": False}`
- Idempotent writes (PUT/update): add `idempotentHint: True`

### Tool Descriptions
- 1-2 sentences. Front-load what it does AND what it returns.
- Bad: "This tool gets a merge request."
- Good: "Get merge request details. Returns title, state, branches, author, diff_refs."

### Error Handling
- Every tool MUST wrap in try/except and return `_err(e)` — never raise.
- Error text MUST be actionable: include what went wrong and suggest a fix.
- Never return concatenated JSON strings — always a single valid JSON object.
- Never expose stack traces, tokens, or internal paths.

### Parameter Design
- Use `Annotated[type, Field(description="...")]` on every parameter.
- Use `Literal[...]` for known value sets instead of plain `str`.
- Every optional parameter must have a default.
- Flatten — no nested dicts unless truly necessary.

### Read-Only Mode
- Every write tool MUST call `_check_write(ctx)` before any mutation.

### Naming Convention
- Pattern: `gitlab_{verb}_{resource}` (snake_case)
- Verbs: create, get, list, search, update, delete, merge, rebase, retry, play, cancel, award, remove, share, unshare, compare, add, reply, resolve

## Tool Categories

Projects (4), Approvals (10), Groups (6), Branches (3), Commits (4), Merge Requests (8), MR Notes (6), MR Discussions (4), Pipelines (5), Jobs (4), Tags (4), Releases (5), CI/CD Variables (8), Issues (5)

## Environment Variables

- `GITLAB_URL` (required) — GitLab instance base URL
- `GITLAB_TOKEN` or `GITLAB_PAT` (required) — Personal access token
- `GITLAB_READ_ONLY` — disable mutations
- `GITLAB_TIMEOUT` — request timeout seconds
- `GITLAB_SSL_VERIFY` — SSL verification toggle

## Release Workflow

Releases are handled via GitHub Actions — never bump versions manually.

### How to release

```bash
# From the repo directory:
gh workflow run release.yml -f bump=minor      # 0.4.0 → 0.5.0
gh workflow run release.yml -f bump=patch      # 0.5.0 → 0.5.1
gh workflow run release.yml -f bump=major      # 0.5.0 → 1.0.0

# Dry run (preview changelog, no push):
gh workflow run release.yml -f bump=minor -f dry_run=true
```

### What happens

1. `release.yml` (workflow_dispatch) — bumps `pyproject.toml` version, regenerates `uv.lock`, generates CHANGELOG.md, creates release commit + tag via GitHub API
2. `publish.yml` (triggered by `v*` tag push) — builds wheel, publishes to PyPI, creates GitHub Release with auto-generated notes

### Rules
- Never edit `pyproject.toml` version directly — the workflow owns it
- Never create tags manually — the workflow creates them
- Commit messages must follow conventional commits (`feat:`, `fix:`, `docs:`, etc.) for changelog generation
- The release commit is authored by `github-actions[bot]` with message `chore(release): X.Y.Z`

## Prompts

Prompts follow the resources pattern: prompt content lives as `.md` files in `src/mcp_gitlab/resources/prompts/`, loaded by `servers/prompts.py` via `_load_prompt()`, registered with `@mcp.prompt()`. Each prompt returns `list[Message]` with a user message (workflow template) and an assistant message (acknowledgment).

- `review_mr` — MR review workflow (tags: gitlab, review)
- `diagnose_pipeline` — CI debug workflow (tags: gitlab, ci)
- `prepare_release` — Release preparation (tags: gitlab, release)
- `setup_branch_protection` — Branch protection setup (tags: gitlab, settings)
- `triage_issues` — Issue triage workflow (tags: gitlab, issues)

## Known Limitations / Future Work

- 76 tools in one server file (exceeds 5-15 guideline). Consider splitting by category in a future refactor.
- Errors are returned as successful tool results with `{"error": ...}` (soft-error pattern). Callers must inspect JSON content.
