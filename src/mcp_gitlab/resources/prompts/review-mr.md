# Review MR !$mr_iid in project $project_id

## Steps

1. **Fetch MR details** — use `gitlab_get_mr` with project_id="$project_id" and mr_iid="$mr_iid". Note the author, source/target branches, description, and labels.
2. **Check pipeline status** — use `gitlab_list_mr_pipelines` to find the latest pipeline for the MR. If its status is not `success`, flag it before proceeding.
3. **Get the diff** — use `gitlab_mr_changes` to retrieve all changed files.
4. **Review each changed file** — use `gitlab_get_file` (at the MR's head ref) to read the full surrounding context a diff hunk omits, then evaluate:
   - Correctness and logic errors
   - Test coverage for new/changed code paths
   - Security implications (injection, auth, secrets)
   - Performance (N+1 queries, unnecessary allocations)
   - Naming clarity and code style consistency
5. **Draft inline comments** — use `gitlab_create_draft_note` for each finding, anchored to the relevant file and line (pass `new_path` plus `new_line`/`old_line`; the diff SHAs are auto-filled). Drafts stay invisible to the author until you publish, so you can revise them freely. Use Conventional Comments labels (suggestion, issue, nitpick, praise).
6. **Summarize** — add a draft note (no position) via `gitlab_create_draft_note` covering:
   - What the MR does well
   - Blocking issues (if any)
   - Non-blocking suggestions
7. **Confirm, then publish** — list the pending drafts with `gitlab_list_draft_notes` and show the author which comments you are about to post. Only after explicit confirmation, call `gitlab_publish_draft_notes` once to submit them all at once ("Submit review").
8. **Verdict** — approve if no blocking issues, otherwise request changes.

## Review Priority Order

1. Design — is the overall approach sound?
2. Functionality — does it do what the description says?
3. Complexity — could a future reader understand it quickly?
4. Tests — are they correct, meaningful, and covering edge cases?
5. Naming — are variables, functions, and files clearly named?
6. Comments — do they explain "why", not "what"?
7. Style — consistent with the rest of the codebase?
