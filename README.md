# mcp-gitlab

MCP server for the GitLab REST API. Provides 65+ tools for projects, merge requests, pipelines, CI/CD variables, approvals, issues, and more.

Built with [FastMCP](https://github.com/jlowin/fastmcp), [httpx](https://www.python-httpx.org/), and [Pydantic](https://docs.pydantic.dev/).

## Installation

```bash
# From PyPI
uv pip install mcp-gitlab

# From source
uv pip install git+https://github.com/vish288/mcp-gitlab.git
```

## Configuration

Set these environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `GITLAB_URL` | Yes | GitLab instance URL (e.g. `https://gitlab.example.com`) |
| `GITLAB_TOKEN` | Yes | Personal access token with `api` scope |
| `GITLAB_READ_ONLY` | No | Set to `true` to disable write operations |
| `GITLAB_TIMEOUT` | No | Request timeout in seconds (default: 30) |
| `GITLAB_SSL_VERIFY` | No | Set to `false` to skip SSL verification |

## Usage

### Claude Code / Cursor

Add to your MCP config (`~/.claude/settings.json` or `.cursor/mcp.json`):

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

### Standalone

```bash
# stdio transport (default)
mcp-gitlab

# HTTP transport
mcp-gitlab --transport sse --port 8000
```

### Python

```python
from mcp_gitlab.servers.gitlab import mcp

# Run with stdio
mcp.run()
```

## Tools (65)

### Projects (4)
| Tool | Description |
|------|-------------|
| `gitlab_get_project` | Get project details |
| `gitlab_create_project` | Create a new project |
| `gitlab_delete_project` | Delete a project |
| `gitlab_update_project_merge_settings` | Update merge settings |

### Project Approvals (8)
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

### Groups (6)
| Tool | Description |
|------|-------------|
| `gitlab_list_groups` | List groups |
| `gitlab_get_group` | Get group details |
| `gitlab_share_project_with_group` | Share project with group |
| `gitlab_unshare_project_with_group` | Unshare project from group |
| `gitlab_share_group_with_group` | Share group with group |
| `gitlab_unshare_group_with_group` | Unshare group from group |

### Branches (3)
| Tool | Description |
|------|-------------|
| `gitlab_list_branches` | List branches |
| `gitlab_create_branch` | Create a branch |
| `gitlab_delete_branch` | Delete a branch |

### Commits (4)
| Tool | Description |
|------|-------------|
| `gitlab_list_commits` | List commits |
| `gitlab_get_commit` | Get commit (with optional diff) |
| `gitlab_create_commit` | Create commit with file actions |
| `gitlab_compare` | Compare branches/tags/commits |

### Merge Requests (9)
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

### MR Notes (6)
| Tool | Description |
|------|-------------|
| `gitlab_list_mr_notes` | List MR comments |
| `gitlab_add_mr_note` | Add comment to MR |
| `gitlab_delete_mr_note` | Delete MR comment |
| `gitlab_update_mr_note` | Update MR comment |
| `gitlab_award_emoji` | Award emoji to note |
| `gitlab_remove_emoji` | Remove emoji from note |

### MR Discussions (4)
| Tool | Description |
|------|-------------|
| `gitlab_list_mr_discussions` | List discussions |
| `gitlab_create_mr_discussion` | Create discussion (inline + multi-line) |
| `gitlab_reply_to_discussion` | Reply to discussion |
| `gitlab_resolve_discussion` | Resolve/unresolve discussion |

### Pipelines (5)
| Tool | Description |
|------|-------------|
| `gitlab_list_pipelines` | List pipelines |
| `gitlab_get_pipeline` | Get pipeline (with optional jobs) |
| `gitlab_create_pipeline` | Trigger pipeline |
| `gitlab_retry_pipeline` | Retry failed jobs |
| `gitlab_cancel_pipeline` | Cancel pipeline |

### Jobs (4)
| Tool | Description |
|------|-------------|
| `gitlab_retry_job` | Retry a job |
| `gitlab_play_job` | Trigger manual job |
| `gitlab_cancel_job` | Cancel a job |
| `gitlab_get_job_log` | Get job log output |

### Tags (4)
| Tool | Description |
|------|-------------|
| `gitlab_list_tags` | List tags |
| `gitlab_get_tag` | Get tag details |
| `gitlab_create_tag` | Create a tag |
| `gitlab_delete_tag` | Delete a tag |

### Releases (5)
| Tool | Description |
|------|-------------|
| `gitlab_list_releases` | List releases |
| `gitlab_get_release` | Get release details |
| `gitlab_create_release` | Create a release |
| `gitlab_update_release` | Update a release |
| `gitlab_delete_release` | Delete a release |

### CI/CD Variables (8)
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

### Issues (5)
| Tool | Description |
|------|-------------|
| `gitlab_list_issues` | List issues |
| `gitlab_get_issue` | Get issue details |
| `gitlab_create_issue` | Create an issue |
| `gitlab_update_issue` | Update an issue |
| `gitlab_add_issue_comment` | Add comment to issue |

## Development

```bash
# Clone and install
git clone https://github.com/vish288/mcp-gitlab.git
cd mcp-gitlab
uv sync --all-extras

# Run tests
uv run pytest --cov

# Lint
uv run ruff check .
uv run ruff format --check .
```

## License

MIT
