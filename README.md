# mcp-gitlab

[![PyPI version](https://img.shields.io/pypi/v/mcp-gitlab)](https://pypi.org/project/mcp-gitlab/)
[![PyPI downloads](https://img.shields.io/pypi/dm/mcp-gitlab)](https://pypi.org/project/mcp-gitlab/)
[![Python](https://img.shields.io/pypi/pyversions/mcp-gitlab)](https://pypi.org/project/mcp-gitlab/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/vish288/mcp-gitlab/actions/workflows/tests.yml/badge.svg)](https://github.com/vish288/mcp-gitlab/actions/workflows/tests.yml)

**mcp-gitlab** is a [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for the GitLab REST API that provides **76 tools** for AI assistants to manage projects, merge requests, pipelines, CI/CD variables, approvals, issues, code reviews, and more. Works with Claude Desktop, Claude Code, Cursor, Windsurf, VS Code Copilot, and any MCP-compatible client.

Built with [FastMCP](https://github.com/jlowin/fastmcp), [httpx](https://www.python-httpx.org/), and [Pydantic](https://docs.pydantic.dev/).

## 1-Click Installation

[![Install in Cursor](https://cursor.com/deeplink/mcp-install-dark.svg)](https://vish288.github.io/mcp-gitlab-cursor-redirect.html?install=cursor)

[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install_Server-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://vish288.github.io/mcp-gitlab-cursor-redirect.html?install=vscode) [![Install in VS Code Insiders](https://img.shields.io/badge/VS_Code_Insiders-Install_Server-24bfa5?style=flat-square&logo=visualstudiocode&logoColor=white)](https://vish288.github.io/mcp-gitlab-cursor-redirect.html?install=vscode-insiders)

> **💡 Tip:** For other AI assistants (Claude Code, Windsurf, IntelliJ), visit the **[GitLab MCP Installation Gateway](https://vish288.github.io/mcp-gitlab-cursor-redirect.html)**.

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

### pip / uv

```bash
uv pip install mcp-gitlab
```

</details>

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITLAB_URL` | **Yes** | - | GitLab instance URL (e.g. `https://gitlab.example.com`) |
| `GITLAB_TOKEN` | **Yes** | - | Authentication token (see below) |
| `GITLAB_READ_ONLY` | No | `false` | Set to `true` to disable write operations |
| `GITLAB_TIMEOUT` | No | `30` | Request timeout in seconds |
| `GITLAB_SSL_VERIFY` | No | `true` | Set to `false` to skip SSL verification |

### Supported Token Types

`GITLAB_TOKEN` (or `GITLAB_PAT`) accepts any of these:

| Token Type | Format | Use Case |
|------------|--------|----------|
| Personal access token | `glpat-xxx` | User-level access with `api` scope |
| OAuth2 token | `oauth-xxx` | OAuth app integrations |
| CI job token | `$CI_JOB_TOKEN` | GitLab CI pipeline access |

## Compatibility

| Client | Supported | Install Method |
|--------|-----------|----------------|
| Claude Desktop | Yes | `claude_desktop_config.json` |
| Claude Code | Yes | `claude mcp add` |
| Cursor | Yes | One-click deeplink or `.cursor/mcp.json` |
| VS Code Copilot | Yes | One-click deeplink or `.vscode/mcp.json` |
| Windsurf | Yes | `~/.codeium/windsurf/mcp_config.json` |
| Any MCP client | Yes | stdio or HTTP transport |

## Tools (76)

| Category | Count | Tools |
|----------|-------|-------|
| **Projects** | 4 | get, create, delete, update merge settings |
| **Project Approvals** | 10 | get/update config, CRUD approval rules (project + MR) |
| **Groups** | 6 | list, get, share/unshare project, share/unshare group |
| **Branches** | 3 | list, create, delete |
| **Commits** | 4 | list, get (with diff), create, compare |
| **Merge Requests** | 8 | list, get, create, update, merge, merge-sequence, rebase, changes |
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
| `gitlab_get_job_log` | Get job log output |

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

## Resources (6)

The server exposes curated workflow guides as [MCP resources](https://modelcontextprotocol.io/docs/concepts/resources) that clients can read on demand.

| URI | Name |
|-----|------|
| `resource://rules/gitlab-ci` | GitLab CI/CD Pipeline Patterns |
| `resource://rules/git-workflow` | Git Workflow Standards |
| `resource://rules/mr-hygiene` | Merge Request Best Practices |
| `resource://rules/conventional-commits` | Conventional Commits Spec |
| `resource://guides/code-review` | Code Review Standards |
| `resource://guides/codeowners` | GitLab CODEOWNERS Reference |

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
- **Read-only mode**: Set `GITLAB_READ_ONLY=true` to disable all write operations (create, update, delete, merge). Read-only mode is enforced server-side before any API call.
- **SSL verification**: `GITLAB_SSL_VERIFY=true` by default. Only disable for self-signed certificates in trusted networks.
- **CI/CD variable masking**: `gitlab_list_variables` and `gitlab_list_group_variables` automatically mask values of variables marked as masked in GitLab, returning `***MASKED***` instead of the actual value.
- **No credential storage**: The server does not persist tokens. Credentials are read from environment variables at startup.

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

# HTTP transport (SSE or streamable-http)
uvx mcp-gitlab --transport sse --host 127.0.0.1 --port 8000
uvx mcp-gitlab --transport streamable-http --port 9000

# CLI overrides for config
uvx mcp-gitlab --gitlab-url https://gitlab.example.com --gitlab-token glpat-xxx --read-only
```

The server loads `.env` files from the working directory automatically via `python-dotenv`.

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
