# mcp-gitlab

[![PyPI version](https://img.shields.io/pypi/v/mcp-gitlab)](https://pypi.org/project/mcp-gitlab/)
[![PyPI downloads](https://img.shields.io/pypi/dm/mcp-gitlab)](https://pypi.org/project/mcp-gitlab/)
[![Python](https://img.shields.io/pypi/pyversions/mcp-gitlab)](https://pypi.org/project/mcp-gitlab/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/vish288/mcp-gitlab/actions/workflows/tests.yml/badge.svg)](https://github.com/vish288/mcp-gitlab/actions/workflows/tests.yml)

**mcp-gitlab** is a [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for the GitLab REST API that provides **65+ tools** for AI assistants to manage projects, merge requests, pipelines, CI/CD variables, approvals, issues, code reviews, and more. Works with Claude Desktop, Claude Code, Cursor, Windsurf, VS Code Copilot, and any MCP-compatible client.

Built with [FastMCP](https://github.com/jlowin/fastmcp), [httpx](https://www.python-httpx.org/), and [Pydantic](https://docs.pydantic.dev/).

## Quick Install

### Cursor

[![Install MCP Server](https://cursor.com/deeplink/mcp-install-dark.svg)](cursor://anysphere.cursor-deeplink/mcp/install?name=mcp-gitlab&config=eyJtY3BTZXJ2ZXJzIjogeyJnaXRsYWIiOiB7ImNvbW1hbmQiOiAidXZ4IiwgImFyZ3MiOiBbIm1jcC1naXRsYWIiXSwgImVudiI6IHsiR0lUTEFCX1VSTCI6ICJodHRwczovL2dpdGxhYi5leGFtcGxlLmNvbSIsICJHSVRMQUJfVE9LRU4iOiAieW91ci10b2tlbiJ9fX19)

### Claude Code

```bash
claude mcp add gitlab -- uvx mcp-gitlab
```

### Windsurf / VS Code

Add to your MCP config file:

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

## Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `GITLAB_URL` | Yes | GitLab instance URL (e.g. `https://gitlab.example.com`) |
| `GITLAB_TOKEN` | Yes | Authentication token (see below) |
| `GITLAB_READ_ONLY` | No | Set to `true` to disable write operations |
| `GITLAB_TIMEOUT` | No | Request timeout in seconds (default: 30) |
| `GITLAB_SSL_VERIFY` | No | Set to `false` to skip SSL verification |

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
| Windsurf | Yes | `~/.codeium/windsurf/mcp_config.json` |
| VS Code Copilot | Yes | `.vscode/mcp.json` |
| Any MCP client | Yes | stdio or HTTP transport |

## Tools (65)

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
