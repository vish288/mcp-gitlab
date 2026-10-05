# mcp-gitlab — Agent Context

MCP server exposing 83 tools, 7 resources, and 6 prompts over the GitLab REST API v4. Covers the
full project lifecycle: code, reviews, CI/CD, releases, and issue tracking. Works against
GitLab.com and self-hosted instances.

## Protocol Support

Supports the MCP 2026-07-28 specification (MCP 2.0) and stays compatible with 2025-11-25
clients. Built on FastMCP 4.x and the MCP Python SDK 2.x. Verified over `stdio` and
`streamable-http`.

Transports: `stdio` (default), `streamable-http` (recommended for remote), and `sse`. The
2026-07-28 specification deprecates `sse`, so the server prints a warning when you use it. The
server uses no roots, sampling, logging, elicitation, or resource subscriptions, so the
2026-07-28 deprecations do not affect it.

Authorization: with `--auth oauth` (streamable-http only) the server is an MCP 2026-07-28 resource
server and OAuth proxy in front of GitLab (RFC 9728 PRM, RFC 8414 AS metadata, PKCE S256, per-user
GitLab tokens). The auth MUSTs are covered by in-process HTTP tests in `tests/unit/test_oauth_http.py`,
not by a CI conformance job: the MCP conformance suite has no server-side auth scenarios (`auth/*`
are client scenarios), so a conformance job cannot prove them.

## Architecture

- **Entry point**: `src/mcp_gitlab/__init__.py` — click CLI, loads `.env` via python-dotenv, runs the FastMCP server
- **Client**: `src/mcp_gitlab/client.py` — async httpx client with all GitLab API methods
- **Tools**: `src/mcp_gitlab/servers/gitlab.py` — all 83 FastMCP tool registrations
- **Resources**: `src/mcp_gitlab/servers/resources.py` — 7 MCP resources (4 `resource://rules/*`, 3 `resource://guides/*`), content in `src/mcp_gitlab/resources/*.md`
- **Prompts**: `src/mcp_gitlab/servers/prompts.py` — 6 MCP prompts (multi-tool workflows)
- **Helpers**: `src/mcp_gitlab/servers/_helpers.py` — cached file loader with path-traversal guard, plus GitLab URL parsers. Most tools accept a project ID, a path, *or* a full GitLab URL for `project_id`; MR and pipeline URLs also yield the iid/id
- **Config**: `src/mcp_gitlab/config.py` — `GitLabConfig` dataclass built from env vars
- **OAuth**: `src/mcp_gitlab/oauth.py` — `GitLabProvider` (a fastmcp `OAuthProxy` in front of GitLab) and `GitLabTokenVerifier` (validates a GitLab OAuth token via `GET /oauth/token/info`). Only used when `--auth oauth`
- **Exceptions**: `src/mcp_gitlab/exceptions.py` — `GitLabError` base; `GitLabApiError`, `GitLabAuthError`, `GitLabNotFoundError`, `GitLabWriteDisabledError`
- **Tests**: `tests/` — `unit/test_tools.py` (143 tool-level tests via the FastMCP in-memory client), plus `test_client.py`, `test_config.py`, `test_exceptions.py`, `test_prompts.py`, `test_resources.py`, and `tests/test_links.py`. Shared fixtures (`config`, `client`, `mock_api` via respx) live in `tests/conftest.py`

## Development

```bash
uv sync --all-extras
uv run pytest --cov
uv run ruff check .
uv run ruff format --check .   # CI runs --check; formatting drift fails the build
```

`pytest` uses `asyncio_mode = "auto"` — async tests need no marker. Ruff line length is 100,
target py310; lint rules include `S` (bandit), `EM`, `N`, `UP`. `tests/**` waives `S101`,
`S105`, `S106`.

## Patterns

- All tools are `async def` returning JSON strings
- `_ok(data)` for success, `_err(e)` for failure; `_paginated(items)` for list responses
- `_slim_pipeline` / `_slim_job` trim pipeline and job payloads; tools expose `slim=True` by default
- Write access control: `_check_write(ctx)` raises `GitLabWriteDisabledError` when `GITLAB_READ_ONLY=true`
- Tags: every tool tagged with `{"gitlab", "<category>", "read"|"write"}`
- Parameters use `Annotated[type, Field(description=...)]`
- Client auth is a per-request header: `PRIVATE-TOKEN` in token mode, `Bearer` from `get_access_token()` in oauth mode. `GitLabClient.with_bearer(token)` returns a shallow copy that shares the connection pool but swaps the auth header. The shared `httpx.AsyncClient` uses a cookie jar that rejects every cookie (empty-`allowed_domains` policy) so a `Set-Cookie` from GitLab is never stored on the shared client and replayed on another user's request
- Project/group IDs can be numeric or URL-encoded paths
- `gitlab_list_variables` / `gitlab_list_group_variables` return `***MASKED***` for variables GitLab marks as masked

## MCP Compliance Rules

### Tool annotations (mandatory)
Every tool MUST have `annotations={}` with at minimum `readOnlyHint`.
- Read tools: `annotations={"readOnlyHint": True, "idempotentHint": True}`
- Non-destructive writes: `annotations={"readOnlyHint": False}`
- Destructive writes: `annotations={"destructiveHint": True, "readOnlyHint": False}`
- Idempotent writes (PUT/update): add `idempotentHint: True`

### Tool descriptions
1-2 sentences. Front-load what it does AND what it returns.
- Bad: "This tool gets a merge request."
- Good: "Get merge request details. Returns title, state, branches, author, diff_refs."

### Error handling
- Every tool MUST wrap in try/except and return `_err(e)` — never raise.
- Error text MUST be actionable: what went wrong plus a suggested fix.
- Never return concatenated JSON strings — always a single valid JSON object.
- Never expose stack traces, tokens, or internal paths.

### Parameter design
- `Annotated[type, Field(description="...")]` on every parameter.
- `Literal[...]` for known value sets instead of plain `str`.
- Every optional parameter has a default.
- Flatten — no nested dicts unless truly necessary.

### Read-only mode
Every write tool MUST call `_check_write(ctx)` before any mutation.

### Naming convention
- Pattern: `gitlab_{verb}_{resource}` (snake_case)
- Verbs: create, get, list, search, update, delete, merge, rebase, retry, play, cancel, award,
  remove, share, unshare, compare, add, reply, resolve, approve, unapprove, subscribe, unsubscribe

## Tool Categories (83)

| Category | Count | Operations |
|---|---|---|
| Projects | 4 | get, create, delete, update merge settings |
| Approvals | 10 | project-level approval settings; project and MR approval rules (list, create, update, delete) |
| Groups | 6 | list, get groups; share/unshare project with group; share/unshare group with group |
| Branches | 3 | list, create, delete |
| Commits | 4 | list, get, create, compare refs |
| Merge Requests | 15 | list, get, create, update, merge, merge sequence, rebase, changes/diffs, approve, unapprove, get approvals, list pipelines, list commits, subscribe, unsubscribe |
| MR Notes | 6 | list, add, update, delete notes; award/remove emoji |
| MR Discussions | 4 | list, create, reply, resolve |
| Pipelines | 5 | list, get, create, retry, cancel |
| Jobs | 4 | retry, play, cancel, get job log |
| Tags | 4 | list, get, create, delete |
| Releases | 5 | list, get, create, update, delete |
| CI/CD Variables | 8 | project and group variables (list, create, update, delete) |
| Issues | 5 | list, get, create, update, add comment |

The table counts the share/unshare tools under Groups, not Projects. There is no `gitlab_list_jobs` —
get job IDs from `gitlab_get_pipeline(..., include_jobs=True)`.

## Common Workflows

- **Code review**: `gitlab_list_mrs` → `gitlab_mr_changes` → `gitlab_list_mr_discussions` → `gitlab_add_mr_note` or `gitlab_create_mr_discussion` → `gitlab_resolve_discussion`
- **Pipeline debugging**: `gitlab_list_pipelines` → `gitlab_get_pipeline` (`include_jobs=True`) → `gitlab_get_job_log` → `gitlab_retry_job`
- **Release**: `gitlab_list_commits` → `gitlab_compare` → `gitlab_create_tag` → `gitlab_create_release`
- **Branch protection**: `gitlab_list_project_approval_rules` → `gitlab_create_project_approval_rule` → `gitlab_update_project_merge_settings`
- **Issue triage**: `gitlab_list_issues` → `gitlab_get_issue` → `gitlab_update_issue` → `gitlab_add_issue_comment`

## Prompts

Prompt content lives as `.md` files in `src/mcp_gitlab/resources/prompts/`. `servers/prompts.py`
loads each file via `_load_prompt()` (`string.Template.safe_substitute` for parameters) and
registers it with `@mcp.prompt()`. Each returns `list[Message]`: a user message (workflow template)
plus an assistant acknowledgment.

| Prompt | Purpose | Tags |
|---|---|---|
| `review_mr` | MR review workflow | gitlab, review |
| `approve_mr` | MR approval workflow | gitlab, review, approvals |
| `diagnose_pipeline` | CI debug workflow | gitlab, ci |
| `prepare_release` | Release preparation | gitlab, release |
| `setup_branch_protection` | Branch protection setup | gitlab, settings |
| `triage_issues` | Issue triage workflow | gitlab, issues |

## Environment Variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `GITLAB_URL` | yes | — | Instance base URL; trailing slash stripped, `/api/v4` appended |
| token (see below) | yes | — | Personal access token, OAuth2 token, or `$CI_JOB_TOKEN` |
| `GITLAB_READ_ONLY` | no | `false` | `true`/`1`/`yes` disables all writes and deletes, enforced before any API call |
| `GITLAB_TIMEOUT` | no | `30` | Request timeout in seconds |
| `GITLAB_SSL_VERIFY` | no | `true` | `false`/`0`/`no` skips verification — self-signed certs only |
| `GITLAB_AUTH` | no | `token` | `token` (PAT from env) or `oauth` (OAuth 2.1 proxy to GitLab; `streamable-http` only) |
| `GITLAB_OAUTH_CLIENT_ID` | oauth | — | Application ID of the GitLab OAuth app |
| `GITLAB_OAUTH_CLIENT_SECRET` | oauth | — | Its secret |
| `GITLAB_OAUTH_BASE_URL` | oauth | — | Public URL of this server, no trailing slash; redirect URI `<base>/auth/callback`, resource `<base>/mcp` |
| `GITLAB_OAUTH_SCOPES` | no | `api` | Space-separated GitLab scopes required on every request (`read_api` for read-only) |
| `GITLAB_OAUTH_JWT_KEY` | no | derived | FastMCP JWT signing key, ≥ 32 random chars; set in production to survive a secret rotation |

In oauth mode, `GITLAB_TOKEN` is ignored and the encrypted upstream-token store lives at `$FASTMCP_HOME/oauth-proxy/<fingerprint>/`. `GITLAB_READ_ONLY` still applies in both modes.

The server reads the token from the first of `GITLAB_TOKEN`, `GITLAB_PAT`,
`GITLAB_PERSONAL_ACCESS_TOKEN`, `GITLAB_API_TOKEN` that is set. Scope `api` for full access,
`read_api` for read-only deployments. The server never persists tokens; it reads them from the
environment at startup.

CLI flags override env: `--gitlab-url`, `--gitlab-token`, `--read-only`, plus
`--transport {stdio,sse,streamable-http}` with `--host` (default `127.0.0.1`) and `--port`
(default `8000`); host/port apply only to non-stdio transports.

## Release Workflow

Releases run through GitHub Actions — never bump versions manually.

```bash
gh workflow run release.yml -f bump=minor                  # 0.9.0 → 0.10.0
gh workflow run release.yml -f bump=patch                  # 0.9.0 → 0.9.1
gh workflow run release.yml -f bump=major                  # 0.9.0 → 1.0.0
gh workflow run release.yml -f bump=minor -f dry_run=true  # preview changelog, no push
```

1. `release.yml` (workflow_dispatch) — bumps the version in `pyproject.toml`, `llms.txt`,
   `llms-full.txt`, `server.json`, `gemini-extension.json`; regenerates `uv.lock`; prepends a
   CHANGELOG.md entry; creates the release commit and tag via the GitHub API.
2. `publish.yml` (triggered by a `v*` tag push) — builds the wheel, publishes to PyPI, creates the
   GitHub Release with auto-generated notes, then publishes to the MCP Registry.

Rules:
- Never edit the `pyproject.toml` version directly — the workflow owns it.
- Never create tags manually — the workflow creates them.
- Commit messages must follow Conventional Commits (`feat:`, `fix:`, `docs:`, …) for changelog generation.
- `github-actions[bot]` authors the release commit with the message `chore(release): X.Y.Z`.

## Documentation Freshness (mandatory)

When a changeset adds, removes, or modifies tools, resources, or prompts, update ALL of these in
the same commit:

- `README.md` — counts in heading and intro, tool table, full tool reference, usage examples, permissions table
- `llms.txt` — count in tagline and documentation link
- `llms-full.txt` — count in tagline, documentation link, full tool reference section
- `AGENTS.md` — counts in intro, tool category table
- `GEMINI.md` — count in intro, tool categories, common workflows
- `server.json` — description field (≤100 chars)

Checklist: counts match the actual registered tools/resources/prompts; the category list is
complete; new entries appear in the right sections with parameters and annotations.

## Known Limitations

- 83 tools in one server file, well past the 5-15 guideline. If you refactor it, split the tools by category.
- Errors come back as successful tool results carrying `{"error": ...}` (soft-error pattern);
  callers must inspect the JSON content rather than relying on protocol-level errors.
- OAuth mode makes one `GET /oauth/token/info` call to GitLab per MCP request (no token-info cache).
  Add `fastmcp.utilities.token_cache.TokenCache` if GitLab rate-limits bite; revocation lag then
  equals the cache TTL.
