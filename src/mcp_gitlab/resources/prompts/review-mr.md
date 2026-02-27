# Review MR !$mr_iid in project $project_id

## Steps

1. **Fetch MR details** — use `gitlab_get_mr` with project_id="$project_id" and mr_iid="$mr_iid". Note the author, source/target branches, description, and labels.
2. **Check pipeline status** — use `gitlab_get_pipeline` with the pipeline ID from step 1. If CI has not passed, flag it before proceeding.
3. **Get the diff** — use `gitlab_mr_changes` to retrieve all changed files.
4. **Review each changed file** — evaluate:
   - Correctness and logic errors
   - Test coverage for new/changed code paths
   - Security implications (injection, auth, secrets)
   - Performance (N+1 queries, unnecessary allocations)
   - Naming clarity and code style consistency
5. **Write inline comments** — use `gitlab_create_mr_discussion` for each finding, anchored to the relevant file and line. Use Conventional Comments labels (suggestion, issue, nitpick, praise).
6. **Summarize** — post an overall MR note via `gitlab_add_mr_note` with:
   - What the MR does well
   - Blocking issues (if any)
   - Non-blocking suggestions
7. **Verdict** — approve if no blocking issues, otherwise request changes.

## Review Priority Order

1. Design — is the overall approach sound?
2. Functionality — does it do what the description says?
3. Complexity — could a future reader understand it quickly?
4. Tests — are they correct, meaningful, and covering edge cases?
5. Naming — are variables, functions, and files clearly named?
6. Comments — do they explain "why", not "what"?
7. Style — consistent with the rest of the codebase?
