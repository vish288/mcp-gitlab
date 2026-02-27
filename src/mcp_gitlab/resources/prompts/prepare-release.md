# Prepare release $tag_name from $ref in project $project_id

## Steps

1. **List existing tags** — use `gitlab_list_tags` with project_id="$project_id" to find the most recent tag. This is the baseline for the changelog.
2. **Compare commits** — use `gitlab_compare` with project_id="$project_id", from the previous tag to "$ref". This gives all commits that will be in this release.
3. **Build changelog** — from the commit list, group by conventional commit type:
   - **Features** (`feat:`): new functionality
   - **Fixes** (`fix:`): bug corrections
   - **Breaking Changes** (`BREAKING CHANGE:` or `!:`): API/behavior changes
   - **Other**: refactor, docs, chore, ci, test, perf
4. **Draft release notes** — format as markdown with sections for each group. Include commit hash references and author attribution.
5. **Create tag** — use `gitlab_create_tag` with project_id="$project_id", tag_name="$tag_name", ref="$ref", and the release notes as the message.
6. **Create release** — use `gitlab_create_release` with project_id="$project_id", tag_name="$tag_name", and the formatted changelog as the description.
7. **Verify** — confirm the tag and release were created. Report any issues.
