# mcp-gitlab — Agent Context

MCP server providing 65+ tools for the GitLab REST API v4.

## Architecture

- **Entry point**: `src/mcp_gitlab/__init__.py` — click CLI, loads env, runs FastMCP server
- **Client**: `src/mcp_gitlab/client.py` — async httpx client with all GitLab API methods
- **Tools**: `src/mcp_gitlab/servers/gitlab.py` — all FastMCP tool registrations
- **Models**: `src/mcp_gitlab/models/` — Pydantic models for typed API responses
- **Config**: `src/mcp_gitlab/config.py` — `GitLabConfig` dataclass from env vars
- **Exceptions**: `src/mcp_gitlab/exceptions.py` — `GitLabApiError`, `GitLabAuthError`, etc.

## Patterns

- All tools are `async def` returning JSON strings
- Error handling: try/except wrapping every tool, returning `{"error": ...}` JSON
- Write access control: `_check_write(ctx)` raises `GitLabWriteDisabledError` when `GITLAB_READ_ONLY=true`
- Tags: every tool tagged with `{"gitlab", "<category>", "read"|"write"}`
- Parameters use `Annotated[type, Field(description=...)]`
- Client uses httpx with `PRIVATE-TOKEN` header auth
- Project/group IDs can be numeric or URL-encoded paths

## Tool Categories

Projects (4), Approvals (10), Groups (6), Branches (3), Commits (4), Merge Requests (9), MR Notes (6), MR Discussions (4), Pipelines (5), Jobs (4), Tags (4), Releases (5), CI/CD Variables (8), Issues (5)

## Environment Variables

- `GITLAB_URL` (required) — GitLab instance base URL
- `GITLAB_TOKEN` or `GITLAB_PAT` (required) — Personal access token
- `GITLAB_READ_ONLY` — disable mutations
- `GITLAB_TIMEOUT` — request timeout seconds
- `GITLAB_SSL_VERIFY` — SSL verification toggle
