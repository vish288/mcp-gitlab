# mcp-gitlab — Gemini CLI Extension Context

MCP server providing 76 tools, 6 resources, and 5 prompts for interacting with the GitLab API. Covers the full lifecycle of GitLab projects: code, reviews, CI/CD, releases, and issue tracking.

## Tool Categories

- **Projects** — get, create, delete, update merge settings, share/unshare with groups
- **Merge Requests** — list, get, create, update, merge, rebase, view changes and diffs
- **MR Reviews** — list/add/update/delete notes, list/create discussions, reply to and resolve discussions, award/remove emoji
- **MR Approvals** — project-level and MR-level approval rules (list, create, update, delete)
- **Pipelines & Jobs** — list/get/create/retry/cancel pipelines, retry/play/cancel jobs, get job logs
- **Branches** — list, create, delete
- **Commits** — list, get, create, compare refs
- **Tags & Releases** — list/get/create/delete tags, list/get/create/update/delete releases
- **CI/CD Variables** — project and group variables (list, create, update, delete)
- **Issues** — list, get, create, update, add comments
- **Groups** — list, get, share/unshare groups

## Common Workflows

- **Code review**: `list_mrs` -> `mr_changes` -> `list_mr_discussions` -> `add_mr_note` or `create_mr_discussion` -> `resolve_discussion`
- **Pipeline debugging**: `list_pipelines` -> `get_pipeline` -> `get_job_log` -> `retry_job`
- **Release process**: `list_commits` -> `compare` -> `create_tag` -> `create_release`
- **Branch protection**: `list_project_approval_rules` -> `create_project_approval_rule` -> `update_project_merge_settings`
- **Issue triage**: `list_issues` -> `get_issue` -> `update_issue` -> `add_issue_comment`

## Notes

- Set `GITLAB_READ_ONLY=true` to restrict all operations to read-only (no writes, no deletes).
- Token requires appropriate GitLab scopes: `api` for full access, `read_api` for read-only.
- Default request timeout is 30 seconds; override with `GITLAB_TIMEOUT`.
- SSL verification is on by default; disable with `GITLAB_SSL_VERIFY=false` for self-signed certs.
- Works with GitLab.com and self-hosted GitLab instances.
