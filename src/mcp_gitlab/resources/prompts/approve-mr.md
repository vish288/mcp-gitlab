# Approve MR !$mr_iid in project $project_id

## Steps

1. **Fetch MR details** — use `gitlab_get_mr` with project_id="$project_id" and mr_iid="$mr_iid". Note the author, source/target branches, description, labels, and current merge status.
2. **Check approval state** — use `gitlab_get_mr_approvals` to see how many approvals are required, who has already approved, and which approval rules apply.
3. **Check pipeline status** — use `gitlab_list_mr_pipelines` to find the latest pipeline. If it has not passed, flag this and do not approve.
4. **Review commits** — use `gitlab_list_mr_commits` to understand the scope of changes. Flag force-pushed or squashed commits that may invalidate earlier reviews.
5. **Review the diff** — use `gitlab_mr_changes` to inspect all changed files. Look for:
   - Correctness and logic errors
   - Security implications (injection, auth, secrets)
   - Test coverage for new/changed code paths
   - Breaking changes not mentioned in description
6. **Check open discussions** — use `gitlab_list_mr_discussions` and verify all threads are resolved. Unresolved blocking threads must be addressed before approval.
7. **Decision**:
   - If all checks pass → use `gitlab_approve_mr` (pass the HEAD sha for safety)
   - If issues found → post findings via `gitlab_create_mr_discussion` and do NOT approve
   - If pipeline is failing → do NOT approve, explain why

## Safety Notes

- Always pass `sha` to `gitlab_approve_mr` — this prevents approving stale code if new commits were pushed after review.
- Never approve your own MR unless the project explicitly allows self-approval.
- Check that the MR is not in draft state before approving.
