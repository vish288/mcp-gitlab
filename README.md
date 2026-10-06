# mcp-gitlab

[![PyPI version](https://img.shields.io/pypi/v/mcp-gitlab)](https://pypi.org/project/mcp-gitlab/)
[![PyPI downloads](https://img.shields.io/pypi/dm/mcp-gitlab)](https://pypi.org/project/mcp-gitlab/)
[![Python](https://img.shields.io/pypi/pyversions/mcp-gitlab)](https://pypi.org/project/mcp-gitlab/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/vish288/mcp-gitlab/actions/workflows/tests.yml/badge.svg)](https://github.com/vish288/mcp-gitlab/actions/workflows/tests.yml)
[![MCP Registry](https://img.shields.io/badge/MCP-Registry-blue)](https://registry.modelcontextprotocol.io)

<!-- mcp-name: io.github.vish288/mcp-gitlab -->

**mcp-gitlab** is a [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for the GitLab REST API. It gives AI assistants **83 tools**, **7 resources**, and **6 prompts** to manage projects, merge requests, pipelines, CI/CD variables, approvals, issues, and code reviews. Works with Claude Desktop, Claude Code, Cursor, Windsurf, VS Code Copilot, and any MCP-compatible client.

Supports GitLab.com and self-hosted GitLab instances (CE/EE). No GitLab Duo or Premium required.

Supports the MCP 2026-07-28 specification, often called MCP 2.0, and stays compatible with 2025-11-25 clients.

Built with [FastMCP](https://github.com/jlowin/fastmcp) 4.x, [httpx](https://www.python-httpx.org/), and [Pydantic](https://docs.pydantic.dev/).

**Install:** `uvx mcp-gitlab` | [PyPI](https://pypi.org/project/mcp-gitlab/) | [MCP Registry](https://registry.modelcontextprotocol.io) | [Changelog](https://github.com/vish288/mcp-gitlab/releases)

## 1-Click Installation

[![Install in Cursor](https://cursor.com/deeplink/mcp-install-dark.svg)](https://vish288.github.io/mcp-install?server=mcp-gitlab&install=cursor)

[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install_Server-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://vish288.github.io/mcp-install?server=mcp-gitlab&install=vscode) [![Install in VS Code Insiders](https://img.shields.io/badge/VS_Code_Insiders-Install_Server-24bfa5?style=flat-square&logo=visualstudiocode&logoColor=white)](https://vish288.github.io/mcp-install?server=mcp-gitlab&install=vscode-insiders)

> **💡 Tip:** For other AI assistants (Claude Code, Windsurf, IntelliJ, Gemini CLI), visit the **[GitLab MCP Installation Gateway](https://vish288.github.io/mcp-install?server=mcp-gitlab)**.

<details>
<summary><b>Manual Setup Guides (Click to expand)</b></summary>
<br/>

> Prerequisite: Install `uv` first (required for all `uvx` install flows). [Install uv](https://docs.astral.sh/uv/getting-started/installation/).

### Claude Code

```bash
claude mcp add gitlab -- uvx mcp-gitlab
```

### Windsurf & IntelliJ

**Windsurf:** Add to `~/.codeium/windsurf/mcp_config.json`
**IntelliJ:** Add to `Settings | Tools | MCP Servers`

> **Note:** The actual server config starts at `gitlab` inside the `mcpServers` object.

```json
{
  "mcpServers": {
    "gitlab": {
      "command": "uvx",
      "args": ["mcp-gitlab"],
      "env": {
        "GITLAB_URL": "https://gitlab.example.com",
        "GITLAB_TOKEN": "glpat-xxxxxxxxxxxxxxxxxxxx"
      }
    }
  }
}
```

### Gemini CLI

```bash
gemini mcp add -e GITLAB_URL=https://gitlab.example.com -e GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx gitlab uvx mcp-gitlab
```

### pip / uv

```bash
uv pip install mcp-gitlab
```

</details>

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITLAB_URL` | **Yes** | - | GitLab instance URL (e.g. `https://gitlab.example.com`) |
| `GITLAB_TOKEN` | **Yes** (token mode) | - | Authentication token (see below) |
| `GITLAB_READ_ONLY` | No | `false` | Set to `true` to disable write operations |
| `GITLAB_TIMEOUT` | No | `30` | Request timeout in seconds |
| `GITLAB_SSL_VERIFY` | No | `true` | Set to `false` to skip SSL verification |
| `GITLAB_AUTH` | No | `token` | `token` (PAT from env) or `oauth` (OAuth 2.1 proxy; see below) |

### Supported Token Types

The server checks these environment variables in order — first match wins:

1. `GITLAB_TOKEN`
2. `GITLAB_PAT`
3. `GITLAB_PERSONAL_ACCESS_TOKEN`
4. `GITLAB_API_TOKEN`

These accept any of the following token types:

| Token Type | Format | Use Case |
|------------|--------|----------|
| Personal access token | `glpat-xxx` | User-level access with `api` scope |
| OAuth2 token | `oauth-xxx` | OAuth app integrations |
| CI job token | `$CI_JOB_TOKEN` | GitLab CI pipeline access |

## OAuth 2.1 (remote deployments)

For a server shared by several people, `--auth oauth` turns mcp-gitlab into an
MCP 2026-07-28 resource server with GitLab as the upstream OAuth provider: each
user signs in with their own GitLab account, every request runs with that
user's token, and no personal access token is configured on the server. Use it
when you host the server once and multiple users connect to it; keep the
default `--auth token` for a single-user local setup.

OAuth mode requires `--transport streamable-http` (OAuth applies to HTTP only;
stdio keeps using the environment token).

**1. Register a GitLab OAuth application** (User Settings → Applications, or a
group/instance application). Set the redirect URI to `<base>/auth/callback`
(e.g. `https://mcp.example.com/auth/callback`), mark it confidential, and grant
the `api` scope (or `read_api` for a read-only deployment). Copy the
Application ID and Secret.

**2. Configure the server:**

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITLAB_URL` | **Yes** | - | GitLab instance; also the upstream authorization server |
| `GITLAB_OAUTH_CLIENT_ID` | **Yes** | - | Application ID of the GitLab OAuth app |
| `GITLAB_OAUTH_CLIENT_SECRET` | **Yes** | - | Its secret |
| `GITLAB_OAUTH_BASE_URL` | **Yes** | - | Public URL of this server, no trailing slash (e.g. `https://mcp.example.com`). Resource URL is `<base>/mcp` |
| `GITLAB_OAUTH_SCOPES` | No | `api` | Space-separated GitLab scopes required on every request. Use `read_api` for a read-only deployment |
| `GITLAB_OAUTH_JWT_KEY` | No | derived | FastMCP JWT signing key, ≥ 32 random chars. Set it in production so client registrations survive a client-secret rotation |
| `FASTMCP_HOME` | No | platform data dir | The encrypted token store lives at `$FASTMCP_HOME/oauth-proxy/<fingerprint>/` |

```bash
GITLAB_URL=https://gitlab.com GITLAB_AUTH=oauth \
  GITLAB_OAUTH_CLIENT_ID=... GITLAB_OAUTH_CLIENT_SECRET=... \
  GITLAB_OAUTH_BASE_URL=https://mcp.example.com \
  uvx mcp-gitlab --transport streamable-http
```

Point an MCP client (or the MCP Inspector, `pnpm dlx @modelcontextprotocol/inspector`)
at `<base>/mcp`; it discovers the authorization server, runs the OAuth flow, and
each tool call then uses that user's GitLab token. A `read_api`-only token can
read but is refused writes with an actionable hint.

## Compatibility

| Client | Supported | Install Method |
|--------|-----------|----------------|
| Claude Desktop | Yes | `claude_desktop_config.json` |
| Claude Code | Yes | `claude mcp add` |
| Cursor | Yes | One-click deeplink or `.cursor/mcp.json` |
| VS Code Copilot | Yes | One-click deeplink or `.vscode/mcp.json` |
| Windsurf | Yes | `~/.codeium/windsurf/mcp_config.json` |
| Any MCP client | Yes | stdio or HTTP transport |

## Protocol support

mcp-gitlab implements the Model Context Protocol. It supports the 2026-07-28 specification, often called MCP 2.0. It stays compatible with 2025-11-25 clients.

- **Specification**: MCP 2026-07-28 (MCP 2.0). Verified over `stdio` and `streamable-http`.
- **Legacy clients**: 2025-11-25 clients still work.
- **Built on**: FastMCP 4.x and the MCP Python SDK 2.x.
- **Transports**: `stdio` (default) and `streamable-http` (recommended for remote). The `sse` (HTTP+SSE) transport still works, but the 2026-07-28 specification deprecates it. The server prints a warning when you use it.
- **Capabilities**: tools, resources, and prompts. The server uses no roots, sampling, logging, elicitation, or resource subscriptions, so the 2026-07-28 deprecations do not affect it.

## Tools (83)

| Category | Count | Tools |
|----------|-------|-------|
| **Projects** | 4 | get, create, delete, update merge settings |
| **Project Approvals** | 10 | get/update config, CRUD approval rules (project + MR) |
| **Groups** | 6 | list, get, share/unshare project, share/unshare group |
| **Branches** | 3 | list, create, delete |
| **Commits** | 4 | list, get (with diff), create, compare |
| **Merge Requests** | 15 | list, get, create, update, merge, merge-sequence, rebase, changes, approve, unapprove, get approvals, list pipelines, list commits, subscribe, unsubscribe |
| **MR Notes** | 6 | list, add, delete, update, award emoji, remove emoji |
| **MR Discussions** | 4 | list, create (inline + multi-line), reply, resolve |
| **Pipelines** | 5 | list, get (with jobs), create, retry, cancel |
| **Jobs** | 4 | retry, play, cancel, get log |
| **Tags** | 4 | list, get, create, delete |
| **Releases** | 5 | list, get, create, update, delete |
| **CI/CD Variables** | 8 | CRUD for project variables, CRUD for group variables |
| **Issues** | 5 | list, get, create, update, add comment |

<details>
<summary>Full tool reference (click to expand)</summary>

### Projects
| Tool | Description |
|------|-------------|
| `gitlab_get_project` | Get project details |
| `gitlab_create_project` | Create a new project |
| `gitlab_delete_project` | Delete a project |
| `gitlab_update_project_merge_settings` | Update merge settings |

### Project Approvals
| Tool | Description |
|------|-------------|
| `gitlab_get_project_approvals` | Get approval config |
| `gitlab_update_project_approvals` | Update approval settings |
| `gitlab_list_project_approval_rules` | List approval rules |
| `gitlab_create_project_approval_rule` | Create approval rule |
| `gitlab_update_project_approval_rule` | Update approval rule |
| `gitlab_delete_project_approval_rule` | Delete approval rule |
| `gitlab_list_mr_approval_rules` | List MR approval rules |
| `gitlab_create_mr_approval_rule` | Create MR approval rule |
| `gitlab_update_mr_approval_rule` | Update MR approval rule |
| `gitlab_delete_mr_approval_rule` | Delete MR approval rule |

### Groups
| Tool | Description |
|------|-------------|
| `gitlab_list_groups` | List groups |
| `gitlab_get_group` | Get group details |
| `gitlab_share_project_with_group` | Share project with group |
| `gitlab_unshare_project_with_group` | Unshare project from group |
| `gitlab_share_group_with_group` | Share group with group |
| `gitlab_unshare_group_with_group` | Unshare group from group |

### Branches
| Tool | Description |
|------|-------------|
| `gitlab_list_branches` | List branches |
| `gitlab_create_branch` | Create a branch |
| `gitlab_delete_branch` | Delete a branch |

### Commits
| Tool | Description |
|------|-------------|
| `gitlab_list_commits` | List commits |
| `gitlab_get_commit` | Get commit (with optional diff) |
| `gitlab_create_commit` | Create commit with file actions |
| `gitlab_compare` | Compare branches/tags/commits |

### Merge Requests
| Tool | Description |
|------|-------------|
| `gitlab_list_mrs` | List merge requests |
| `gitlab_get_mr` | Get MR details |
| `gitlab_create_mr` | Create merge request |
| `gitlab_update_mr` | Update merge request |
| `gitlab_merge_mr` | Merge a merge request |
| `gitlab_merge_mr_sequence` | Merge multiple MRs in order |
| `gitlab_rebase_mr` | Rebase a merge request |
| `gitlab_mr_changes` | Get MR file changes |
| `gitlab_approve_mr` | Approve a merge request |
| `gitlab_unapprove_mr` | Remove approval from a merge request |
| `gitlab_get_mr_approvals` | Get MR approval state |
| `gitlab_list_mr_pipelines` | List MR pipelines |
| `gitlab_list_mr_commits` | List MR commits |
| `gitlab_subscribe_mr` | Subscribe to MR notifications |
| `gitlab_unsubscribe_mr` | Unsubscribe from MR notifications |

### MR Notes
| Tool | Description |
|------|-------------|
| `gitlab_list_mr_notes` | List MR comments |
| `gitlab_add_mr_note` | Add comment to MR |
| `gitlab_delete_mr_note` | Delete MR comment |
| `gitlab_update_mr_note` | Update MR comment |
| `gitlab_award_emoji` | Award emoji to note |
| `gitlab_remove_emoji` | Remove emoji from note |

### MR Discussions
| Tool | Description |
|------|-------------|
| `gitlab_list_mr_discussions` | List discussions |
| `gitlab_create_mr_discussion` | Create discussion (inline + multi-line) |
| `gitlab_reply_to_discussion` | Reply to discussion |
| `gitlab_resolve_discussion` | Resolve/unresolve discussion |

### Pipelines
| Tool | Description |
|------|-------------|
| `gitlab_list_pipelines` | List pipelines |
| `gitlab_get_pipeline` | Get pipeline (with optional jobs) |
| `gitlab_create_pipeline` | Trigger pipeline |
| `gitlab_retry_pipeline` | Retry failed jobs |
| `gitlab_cancel_pipeline` | Cancel pipeline |

### Jobs
| Tool | Description |
|------|-------------|
| `gitlab_retry_job` | Retry a job |
| `gitlab_play_job` | Trigger manual job |
| `gitlab_cancel_job` | Cancel a job |
| `gitlab_get_job_log` | Get job log output (last 200 lines by default; `tail_lines=0` for all) |

### Tags
| Tool | Description |
|------|-------------|
| `gitlab_list_tags` | List tags |
| `gitlab_get_tag` | Get tag details |
| `gitlab_create_tag` | Create a tag |
| `gitlab_delete_tag` | Delete a tag |

### Releases
| Tool | Description |
|------|-------------|
| `gitlab_list_releases` | List releases |
| `gitlab_get_release` | Get release details |
| `gitlab_create_release` | Create a release |
| `gitlab_update_release` | Update a release |
| `gitlab_delete_release` | Delete a release |

### CI/CD Variables
| Tool | Description |
|------|-------------|
| `gitlab_list_variables` | List project variables |
| `gitlab_create_variable` | Create project variable |
| `gitlab_update_variable` | Update project variable |
| `gitlab_delete_variable` | Delete project variable |
| `gitlab_list_group_variables` | List group variables |
| `gitlab_create_group_variable` | Create group variable |
| `gitlab_update_group_variable` | Update group variable |
| `gitlab_delete_group_variable` | Delete group variable |

### Issues
| Tool | Description |
|------|-------------|
| `gitlab_list_issues` | List issues |
| `gitlab_get_issue` | Get issue details |
| `gitlab_create_issue` | Create an issue |
| `gitlab_update_issue` | Update an issue |
| `gitlab_add_issue_comment` | Add comment to issue |

</details>

## Resources (7)

The server exposes curated workflow guides as [MCP resources](https://modelcontextprotocol.io/docs/concepts/resources) that clients can read on demand.

| URI | Name | Description |
|-----|------|-------------|
| `resource://rules/gitlab-ci` | GitLab CI/CD Pipeline Patterns | Stage design, job rules, caching, artifacts, `needs` DAG, multi-project pipelines |
| `resource://rules/git-workflow` | Git Workflow Standards | Branch naming, trunk-based flow, merge vs rebase, protected branches |
| `resource://rules/mr-hygiene` | Merge Request Best Practices | MR size, description templates, review checklists, thread resolution |
| `resource://rules/conventional-commits` | Conventional Commits Spec | Commit types, scopes, breaking changes, changelog generation |
| `resource://guides/code-review` | Code Review Standards | Review priorities, inline comments, approval workflows, nit vs blocker |
| `resource://guides/codeowners` | GitLab CODEOWNERS Reference | Syntax, section owners, approval rules, pattern matching |
| `resource://guides/approval-workflow` | Approval Workflow Guide | Approval types, project vs MR-level rules, SHA safety, merge readiness |

## Prompts (6)

The server provides [MCP prompts](https://modelcontextprotocol.io/docs/concepts/prompts) — reusable multi-tool workflow templates that clients can surface as slash commands.

| Prompt | Parameters | Workflow |
|--------|-----------|----------|
| `review_mr` | `project_id`, `mr_iid` | Fetch MR → check pipeline → review changes → write discussion notes |
| `approve_mr` | `project_id`, `mr_iid` | Check approvals → verify pipeline → review changes → approve or request changes |
| `diagnose_pipeline` | `project_id`, `pipeline_id` | Fetch pipeline → identify failed jobs → get logs → suggest fix |
| `prepare_release` | `project_id`, `tag_name`, `ref` | Compare commits since last tag → draft changelog → create tag + release |
| `setup_branch_protection` | `project_id` | Review settings → configure merge method → set approval rules |
| `triage_issues` | `project_id`, `label` | List open issues → categorize → prioritize → identify duplicates |

## Usage Examples

### Projects & Branches

```
"Get details for project my-org/api-gateway"
→ gitlab_get_project(project_id="my-org/api-gateway")

"Create a feature branch from main"
→ gitlab_create_branch(project_id="123", branch_name="feat/login", ref="main")

"Delete all branches merged into main"
→ gitlab_list_branches(project_id="123") → filter merged → gitlab_delete_branch for each
```

### Merge Requests & Code Review

```
"Open a merge request from feat/login to main"
→ gitlab_create_mr(project_id="123", source_branch="feat/login", target_branch="main", title="Add login")

"Review MR !42 — list changes and add inline comments"
→ gitlab_mr_changes(project_id="123", mr_iid=42)
→ gitlab_create_mr_discussion(project_id="123", mr_iid=42, body="nit: ...", new_path="src/auth.py", new_line=15)

"Merge MR !42 after resolving all threads"
→ gitlab_list_mr_discussions(project_id="123", mr_iid=42) → resolve unresolved
→ gitlab_merge_mr(project_id="123", mr_iid=42, squash=True)
```

### Pipelines & CI/CD

```
"Show failed pipelines on main this week"
→ gitlab_list_pipelines(project_id="123", ref="main", status="failed")

"Retry a failed pipeline"
→ gitlab_retry_pipeline(project_id="123", pipeline_id=456)

"Get the build log for job 789"
→ gitlab_get_job_log(project_id="123", job_id=789, tail_lines=100)
```

### Issues

```
"Create a bug report in project 123"
→ gitlab_create_issue(project_id="123", title="Login page 500 error", labels=["bug","P1"])

"Find open issues assigned to me"
→ gitlab_list_issues(project_id="123", state="opened", assignee_username="johndoe")
```

## Security Considerations

- **Token scope**: Use the minimum required scope. `api` scope grants full access; prefer `read_api` for read-only deployments.
- **Read-only mode**: Set `GITLAB_READ_ONLY=true` to disable all write operations (create, update, delete, merge). The server enforces read-only mode before any API call.
- **SSL verification**: `GITLAB_SSL_VERIFY=true` by default. Only disable for self-signed certificates in trusted networks.
- **CI/CD variable masking**: `gitlab_list_variables` and `gitlab_list_group_variables` automatically mask values of variables marked as masked in GitLab, returning `***MASKED***` instead of the actual value.
- **MCP tool annotations**: Each tool declares `readOnlyHint`, `destructiveHint`, and `idempotentHint` for client-side permission prompts.
- **No credential storage**: The server does not persist tokens. The server reads credentials from environment variables at startup.

## Rate Limits & Permissions

### Rate Limits

GitLab enforces per-user rate limits (default: 2000 requests/minute for authenticated users). When rate-limited, tools return a 429 error with a hint to wait before retrying. Paginated endpoints default to 20 results per page; use `per_page` (max 100) to reduce the number of API calls.

### Required Permissions

| Operation | Minimum GitLab Role |
|-----------|-------------------|
| Read projects, MRs, pipelines, issues | Reporter |
| Create branches, MRs, issues | Developer |
| Merge MRs, manage CI/CD variables | Maintainer |
| Delete projects, manage approval rules | Maintainer/Owner |
| Share projects/groups | Owner (or Admin) |

## CLI & Transport Options

```bash
# Default: stdio transport (for MCP clients)
uvx mcp-gitlab

# HTTP transport — streamable-http is recommended for remote use
uvx mcp-gitlab --transport streamable-http --port 9000

# SSE transport — deprecated by MCP 2026-07-28; still works, prints a warning
uvx mcp-gitlab --transport sse --host 127.0.0.1 --port 8000

# OAuth 2.1 mode (per-user GitLab sign-in; streamable-http only) — see "OAuth 2.1" above
uvx mcp-gitlab --auth oauth --transport streamable-http

# CLI overrides for config
uvx mcp-gitlab --gitlab-url https://gitlab.example.com --gitlab-token glpat-xxx --read-only
```

`--auth {token,oauth}` selects the authentication mode (`token` by default);
`oauth` requires `--transport streamable-http`.

The server loads `.env` files from the working directory automatically via `python-dotenv`.

## FAQ

### Does mcp-gitlab support MCP 2.0?

Yes. It supports the MCP 2026-07-28 specification, often called MCP 2.0. It also stays compatible with 2025-11-25 clients.

### Does it work with self-hosted GitLab?

Yes. It works with GitLab.com and self-hosted GitLab (CE and EE). It needs no GitLab Duo or Premium.

### Which transports does it support?

It supports `stdio` (the default) and `streamable-http`. The `sse` transport still works, but the 2026-07-28 specification deprecates it. OAuth 2.1 mode (`--auth oauth`) is available on `streamable-http` only.

### Is mcp-gitlab safe for read-only use?

Yes. Set `GITLAB_READ_ONLY=true` to disable every create, update, delete, and merge. The server enforces this before any API call.

### What token scopes does it need?

Use a token with the `api` scope for full access. Use the `read_api` scope for read-only deployments. The server reads the token from the environment and never stores it.

### Which AI assistants work with it?

It works with Claude Desktop, Claude Code, Cursor, Windsurf, VS Code Copilot, and any MCP-compatible client.

### How do I install mcp-gitlab?

Run `uvx mcp-gitlab`, or add it to your MCP client configuration. See the installation section above.

## Related MCP Servers

- [mcp-atlassian-extended](https://github.com/vish288/mcp-atlassian-extended) — Jira + Confluence integration (22 tools, 15 resources, 5 prompts)
- [mcp-coda](https://github.com/vish288/mcp-coda) — Coda integration (53 tools, 12 resources, 5 prompts)
- [mcp-argocd](https://github.com/vish288/mcp-argocd) — Argo CD integration (37 tools, 7 resources, 7 prompts)

## Development

```bash
git clone https://github.com/vish288/mcp-gitlab.git
cd mcp-gitlab
uv sync --all-extras

uv run pytest --cov
uv run ruff check .
uv run ruff format --check .
```

## License

MIT
