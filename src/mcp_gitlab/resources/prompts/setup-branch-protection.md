# Set up branch protection for project $project_id

## Steps

1. **Review current settings** — use `gitlab_get_project` with project_id="$project_id" to check the current merge method, approval settings, and default branch.
2. **Check existing approvals** — use `gitlab_get_project_approvals` to see current approval rules and required approval count.
3. **Configure merge method** — use `gitlab_update_project_merge_settings` to set:
   - Merge method (merge commit, rebase, fast-forward)
   - Whether to delete source branch after merge
   - Whether to squash commits
   - Pipeline success requirement
4. **Set approval requirements** — use `gitlab_update_project_approvals` to configure:
   - Required number of approvals
   - Whether authors can approve their own MRs
   - Whether to reset approvals on new pushes
5. **Create approval rules** — use `gitlab_create_project_approval_rule` to define who must approve:
   - Code owners rule
   - Team-specific rules (e.g., security team for sensitive paths)
6. **Verify** — re-fetch project settings and approval rules to confirm everything is applied correctly.
7. **Summary** — report what was configured and any settings that require manual adjustment in the GitLab UI.
