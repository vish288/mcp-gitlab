# mcp-gitlab — Agent Context

MCP server exposing 91 tools, 7 resources, and 6 prompts over the GitLab REST API v4. Covers the
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
- **Tools**: `src/mcp_gitlab/servers/gitlab.py` — all 91 FastMCP tool registrations
- **Resources**: `src/mcp_gitlab/servers/resources.py` — 7 MCP resources (4 `resource://rules/*`, 3 `resource://guides/*`), content in `src/mcp_gitlab/resources/*.md`
- **Prompts**: `src/mcp_gitlab/servers/prompts.py` — 6 MCP prompts (multi-tool workflows)
- **Helpers**: `src/mcp_gitlab/servers/_helpers.py` — cached file loader with path-traversal guard, plus GitLab URL parsers. Most tools accept a project ID, a path, *or* a full GitLab URL for `project_id`; MR and pipeline URLs also yield the iid/id
- **Config**: `src/mcp_gitlab/config.py` — `GitLabConfig` dataclass built from env vars
- **Local sign-in**: `src/mcp_gitlab/local_auth.py` — device and PKCE flows, credentials file, refresh under lock; used when no env token is set
- **OAuth**: `src/mcp_gitlab/oauth.py` — `GitLabProvider` (a fastmcp `OAuthProxy` in front of GitLab) and `GitLabTokenVerifier` (validates a GitLab OAuth token via `GET /oauth/token/info`). Only used when `--auth oauth`
- **Exceptions**: `src/mcp_gitlab/exceptions.py` — `GitLabError` base; `GitLabApiError`, `GitLabAuthError`, `GitLabNotFoundError`, `GitLabWriteDisabledError`
- **Tests**: `tests/` — `unit/test_tools.py` (143 tool-level tests via the FastMCP in-memory client), plus `test_client.py`, `test_config.py`, `test_local_auth.py`, `test_exceptions.py`, `test_prompts.py`, `test_resources.py`, and `tests/test_links.py`. Shared fixtures (`config`, `client`, `mock_api` via respx) live in `tests/conftest.py`

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

Docker (no CI job — smoke-check by hand): `docker build -t mcp-gitlab .` then
`docker run --rm mcp-gitlab --help` exits 0. The image builds from the repo with `uv sync
--frozen --no-dev`, runs as a non-root user, and defaults to `MCP_READ_ONLY=true`. Nothing is
pushed to a registry.

## Patterns

- All tools are `async def` returning a `ToolResult` (built by `_ok`/`_paginated`/`_error_result`, never a bare string)
- `_ok(data)` / `_paginated(items)` wrap success in a `ToolResult` via `_result`: pretty JSON text (byte-identical to the old `-> str` output) plus the same object as `structuredContent`. `_err(e)` builds the error dict that `_error_result` wraps into the text-only `isError` result. Tools advertise no `outputSchema` (upstream fields pass through untyped); a typed schema is opt-in per tool via `output_schema=`
- Errors: expected failures are `isError: true` results whose text content is the `{"error", "status_code"?, "body"?, "hint"?}` object and which set no `structuredContent` (a strict client — the TS MCP SDK — validates `structuredContent` against the tool's output schema even on an error, and the schema rejects the error body); bugs are `isError: true` with `TypeName: message` text and no `structuredContent`, logged with a traceback
- `_slim_pipeline` / `_slim_job` trim pipeline and job payloads; tools expose `slim=True` by default
- Write access control: a truthy `MCP_READ_ONLY` / `GITLAB_READ_ONLY` locks the server read-only — `_lock_read_only` hides the write tools from `tools/list`, and `_check_write(ctx)` (via `@tool_result(write=True)`, or inline in `gitlab_merge_mr_sequence`) raises `GitLabWriteDisabledError` as defence in depth (see Read-only mode)
- Tags: every tool tagged with `{"gitlab", "<category>", "read"|"write"}`
- Parameters use `Annotated[type, Field(description=...)]`
- Client auth is a per-request header: `PRIVATE-TOKEN` in token mode, `Bearer` from `get_access_token()` in oauth mode. `GitLabClient.with_bearer(token)` returns a shallow copy that shares the connection pool but swaps the auth header. The shared `httpx.AsyncClient` uses a cookie jar that rejects every cookie (empty-`allowed_domains` policy) so a `Set-Cookie` from GitLab is never stored on the shared client and replayed on another user's request
- `GitLabClient._send` is the one send path for every verb. With stored local-sign-in credentials it sets a `Bearer` header from `LocalCredentials.bearer()` (proactive refresh within a 300 s margin) and, on a 401, refreshes once and retries; refresh failure raises `GitLabAuthError` rather than looping
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
- Tools do not catch their own errors: the `tool_result` decorator wraps every tool, turns an expected `GitLabError` into an `isError: true` result via `_error_result(_err(e))`, and re-raises anything else as a `ToolError` (a bug) after logging it with a traceback. `gitlab_merge_mr_sequence` keeps its own `except GitLabError` so its `isError: true` envelope can carry `merged_so_far`/`scheduled` (which MRs landed before the failure); bugs still fall through to `tool_result`.
- Error text MUST be actionable: what went wrong plus a suggested fix.
- Never return concatenated JSON strings — always a single valid JSON object.
- Never expose stack traces, tokens, or internal paths.

### Parameter design
- `Annotated[type, Field(description="...")]` on every parameter.
- `Literal[...]` for known value sets instead of plain `str`.
- Every optional parameter has a default.
- Flatten — no nested dicts unless truly necessary.

### Read-only mode
A truthy `MCP_READ_ONLY` (shared across the mcp-* servers) or the `GITLAB_READ_ONLY` alias,
or `--read-only`, locks the server read-only for the process: `GitLabConfig.from_env` ORs the
sources (any locking one wins; a falsy value never unlocks and logs a WARNING; an unrecognised
value fails closed), and the lifespan calls `_lock_read_only(server)`, which
`server.disable(tags={"write"})` so write tools and write-workflow prompts drop out of
`tools/list`/`prompts/list` and `tools/call` on them returns "Unknown tool". The lock is
computed once and never cleared; `src/` never calls `enable`/`enable_components`. The lock is
unconditional on auth mode (oauth also hides by tag); the per-user `read_api` scope refusal in
`_check_write` stays call-time. Every write tool MUST still call `_check_write(ctx)` (via
`@tool_result(write=True)`, or inline as `gitlab_merge_mr_sequence` does) as defence in depth.

### Naming convention
- Pattern: `gitlab_{verb}_{resource}` (snake_case)
- Verbs: create, get, list, search, update, delete, merge, rebase, retry, play, cancel, award,
  remove, share, unshare, compare, add, reply, resolve, approve, unapprove, subscribe, unsubscribe

## Tool Categories (91)

| Category | Count | Operations |
|---|---|---|
| Projects | 4 | get, create, delete, update merge settings |
| Approvals | 10 | project-level approval settings; project and MR approval rules (list, create, update, delete) |
| Groups | 6 | list, get groups; share/unshare project with group; share/unshare group with group |
| Branches | 3 | list, create, delete |
| Commits | 4 | list, get, create, compare refs |
| Repository Files | 4 | get file (at ref, line range; refuses binary), list tree, search code (blobs), blame |
| Merge Requests | 15 | list, get, create, update, merge, merge sequence, rebase, changes/diffs, approve, unapprove, get approvals, list pipelines, list commits, subscribe, unsubscribe |
| MR Notes | 6 | list, add, update, delete notes; award/remove emoji |
| MR Discussions | 4 | list, create, reply, resolve |
| Draft Notes | 4 | create (inline, SHAs auto-filled from the MR version), list, publish all, delete |
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
- **Review with drafts**: `gitlab_mr_changes` → `gitlab_get_file` (read full context at the MR head) → `gitlab_create_draft_note` per finding → `gitlab_publish_draft_notes` once at the end ("Submit review")
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
| `review_mr` | MR review workflow | gitlab, review, write |
| `approve_mr` | MR approval workflow | gitlab, review, approvals, write |
| `diagnose_pipeline` | CI debug workflow | gitlab, ci |
| `prepare_release` | Release preparation | gitlab, release, write |
| `setup_branch_protection` | Branch protection setup | gitlab, settings, write |
| `triage_issues` | Issue triage workflow | gitlab, issues, write |

## Environment Variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `GITLAB_URL` | yes | — | Instance base URL; trailing slash stripped, `/api/v4` appended |
| token (see below) | yes, unless signed in via `mcp-gitlab auth login` | — | Personal access token, OAuth2 token, or `$CI_JOB_TOKEN` |
| `GITLAB_READ_ONLY` | no | `false` | Truthy (or unrecognised) locks the server read-only: the write tools are not listed and are refused before any API call |
| `MCP_READ_ONLY` | no | `false` | Same as `GITLAB_READ_ONLY`; shared name across the mcp-* servers. Either being truthy locks read-only, and nothing turns it off at runtime |
| `GITLAB_TIMEOUT` | no | `30` | Request timeout in seconds |
| `GITLAB_SSL_VERIFY` | no | `true` | `false`/`0`/`no` skips verification — self-signed certs only |
| `GITLAB_AUTH` | no | `token` | `token` (PAT from env) or `oauth` (OAuth 2.1 proxy to GitLab; `streamable-http` only) |
| `GITLAB_OAUTH_CLIENT_ID` | oauth | — | Application ID of the GitLab OAuth app; also the local sign-in app |
| `GITLAB_OAUTH_CLIENT_SECRET` | oauth | — | Its secret |
| `GITLAB_OAUTH_BASE_URL` | oauth | — | Public URL of this server, no trailing slash; redirect URI `<base>/auth/callback`, resource `<base>/mcp` |
| `GITLAB_OAUTH_SCOPES` | no | `api` | Space-separated GitLab scopes required on every request (`read_api` for read-only) |
| `GITLAB_OAUTH_JWT_KEY` | no | derived | FastMCP JWT signing key, ≥ 32 random chars; set in production to survive a secret rotation |

In oauth mode, `GITLAB_TOKEN` is ignored and the encrypted upstream-token store lives at `$FASTMCP_HOME/oauth-proxy/<fingerprint>/`. `GITLAB_READ_ONLY` still applies in both modes.

The server reads the token from the first of `GITLAB_TOKEN`, `GITLAB_PAT`,
`GITLAB_PERSONAL_ACCESS_TOKEN`, `GITLAB_API_TOKEN` that is set. Scope `api` for full access,
`read_api` for read-only deployments. The server never persists an env token. Stored OAuth
credentials live in `~/.config/mcp-gitlab/credentials.json`.

CLI flags override env: `--gitlab-url`, `--read-only`, plus
`--transport {stdio,sse,streamable-http}` with `--host` (default `127.0.0.1`) and `--port`
(default `8000`); host/port apply only to non-stdio transports (`--gitlab-token` is deprecated
and hidden from `--help`; it still works and warns on stderr — set `GITLAB_TOKEN` instead). The
`mcp-gitlab auth login|status|logout` subcommands manage local OAuth sign-in for stdio and never
start the server.

`--read-only` can only raise the lock (it sets `GITLAB_READ_ONLY=true`); there is no
`--no-read-only`, so argv can never unlock a server whose env already locked it.

Token-mode HTTP on a non-loopback `--host` requires `GITLAB_HTTP_BEARER_TOKEN` (>= 16 chars) or `--auth oauth`; else exit 2.

## Release Workflow

Releases run through GitHub Actions — never bump versions manually.

```bash
gh workflow run release.yml -f bump=minor                  # 0.9.0 → 0.10.0
gh workflow run release.yml -f bump=patch                  # 0.9.0 → 0.9.1
gh workflow run release.yml -f bump=major                  # 0.9.0 → 1.0.0
gh workflow run release.yml -f bump=minor -f dry_run=true  # preview changelog, no push
```

1. `release.yml` (workflow_dispatch) — runs the `tests.yml` and `lint.yml` workflows first
   (`needs: [test, lint]`), then bumps the version in `pyproject.toml`, `llms.txt`,
   `llms-full.txt`, `server.json`, `gemini-extension.json`; regenerates `uv.lock`; prepends a
   CHANGELOG.md entry. The release commit is created with `GITHUB_TOKEN` and no author/committer,
   so GitHub signs it as `github-actions[bot]` (Verified); the job hard-fails if it is not. The
   `main` and tag refs are then moved with `RELEASE_PAT` (the Admin ruleset bypass, and the tag
   push triggers `publish.yml`).
2. `publish.yml` (triggered by a `v*` tag push) — builds the wheel, publishes to PyPI, creates the
   GitHub Release with auto-generated notes, then publishes to the MCP Registry.

Rules:
- Never edit the `pyproject.toml` version directly — the workflow owns it.
- Never create tags manually — the workflow creates them.
- Commit messages must follow Conventional Commits (`feat:`, `fix:`, `docs:`, …) for changelog generation.
- `github-actions[bot]` authors the release commit with the message `chore(release): X.Y.Z`.
- Release commits are GitHub-verified; PR commits merged via rebase show as unsigned on `main`
  by GitHub design (rebase rewrites each commit with a new committer and no signature) — PR review
  plus required checks are the integrity control there.

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

- 91 tools in one server file, well past the 5-15 guideline. If you refactor it, split the tools by category.
- OAuth mode makes one `GET /oauth/token/info` call to GitLab per MCP request (no token-info cache).
  Add `fastmcp.utilities.token_cache.TokenCache` if GitLab rate-limits bite; revocation lag then
  equals the cache TTL.
