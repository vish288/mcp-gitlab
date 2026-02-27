# Triage issues in project $project_id

## Parameters
- **Label filter**: $label

## Steps

1. **List open issues** — use `gitlab_list_issues` with project_id="$project_id", state="opened", and labels="$label" (if provided). Retrieve up to 100 issues.
2. **Categorize** — group issues by:
   - **Bug reports**: issues with "bug" label or bug-related keywords
   - **Feature requests**: issues with "feature" or "enhancement" labels
   - **Questions/Support**: issues asking for help or clarification
   - **Stale**: issues with no activity in the last 30 days
3. **Assess priority** — for each issue, consider:
   - Number of upvotes/reactions
   - Whether it has a milestone assigned
   - Age (older unaddressed issues may need attention)
   - Whether it blocks other issues
4. **Identify duplicates** — look for issues with similar titles or descriptions. Suggest closing duplicates with a reference to the original.
5. **Suggest labels** — for unlabeled issues, recommend appropriate labels based on content analysis.
6. **Apply updates** — use `gitlab_update_issue` to:
   - Add missing labels
   - Set priority labels where appropriate
   - Close confirmed duplicates with a comment
7. **Summary** — provide a triage report:
   - Total open issues by category
   - Top priority items needing immediate attention
   - Stale issues recommended for closure
   - Duplicates identified
