# Approval Workflow Guide

## Approval Types

GitLab supports two levels of approval configuration:

### Project-Level Approval Rules
- Set default required approvals for all MRs in a project
- Define groups or users who must approve
- Configure via `gitlab_get_project_approvals` / `gitlab_update_project_approvals`

### MR-Level Approval Rules
- Override or extend project-level rules for a specific MR
- Add per-MR required approvers (e.g., domain experts for specific changes)
- Configure via `gitlab_list_mr_approval_rules` / `gitlab_create_mr_approval_rule`

## Approval Workflow

### Before Approving
1. All CI pipelines must pass — check via `gitlab_list_mr_pipelines`
2. All discussions must be resolved — check via `gitlab_list_mr_discussions`
3. The MR must not be in draft state — check `draft` field in `gitlab_get_mr`
4. Review the latest changes — use `gitlab_mr_changes` and `gitlab_list_mr_commits`
5. Verify no new commits since your last review

### Approving
- Use `gitlab_approve_mr` with the `sha` parameter set to the current HEAD
- SHA mismatch returns 409 Conflict — this prevents approving stale code
- Re-approval after force-push: previous approvals may be reset (depends on project settings)

### Revoking Approval
- Use `gitlab_unapprove_mr` to withdraw your approval
- Common reasons: new commits pushed after approval, discovered issue post-approval

## Best Practices

### Required Approvals
- Minimum 1 approval for all MRs (prevents self-merge)
- 2 approvals for changes to CI/CD, infrastructure, or security-sensitive code
- Use CODEOWNERS to enforce domain-specific approvers

### Approval Reset
- Configure "Remove all approvals when commits are added to the source branch"
- This prevents stale approvals after force-pushes or amendments

### Merge Readiness Checklist
1. Required approvals met → `gitlab_get_mr_approvals` shows `approved: true`
2. Pipeline passing → latest pipeline in `gitlab_list_mr_pipelines` has `status: success`
3. No unresolved threads → all discussions in `gitlab_list_mr_discussions` are resolved
4. No merge conflicts → `merge_status` is not `cannot_be_merged`
5. Target branch up to date → rebase if needed via `gitlab_rebase_mr`
