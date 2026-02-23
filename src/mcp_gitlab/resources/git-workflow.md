# Git Workflow Standards

## Trunk-Based Development

`main` is always releasable. Feature branches are short-lived (2-3 days max), merged via rebase, and deleted after merge. Direct commits to `main` are prohibited except for automated release tooling.

## Branch Naming

Pattern: `type/TICKET-description`

- `type`: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `ci`
- `TICKET`: issue key in uppercase (e.g., `PROJ-123`)
- `description`: lowercase, hyphen-separated, max 5 words

```bash
feat/PROJ-123-user-login
fix/PROJ-456-cart-null-crash
chore/PROJ-789-upgrade-eslint
```

## Branch Lifetime

Branches must merge or be deleted within **2-3 days**.

If work takes longer:
1. Use a feature flag to ship an incomplete but non-breaking slice
2. Break into smaller independently mergeable pieces
3. Last resort: rebase daily — never let it drift

## Rebase Discipline

Always rebase on `main` before merging. Never use `git merge main` on a feature branch.

```bash
git fetch origin
git rebase origin/main
git push --force-with-lease origin feat/PROJ-123-user-login
```

### Interactive Rebase

Clean up WIP history before opening a PR:

```bash
git rebase -i origin/main
# pick, reword, squash, fixup, drop
```

Each remaining commit should pass CI independently.

## Safe Force Push

```bash
# Correct — verifies nobody else pushed
git push --force-with-lease origin feat/PROJ-123-user-login

# Wrong — blindly overwrites
git push --force origin feat/PROJ-123-user-login
```

Never force-push `main` or release branches. Never escalate to `--force` if `--force-with-lease` fails — fetch first and investigate.

## Feature Flags

Gate incomplete work behind feature flags and merge to `main`:

```typescript
if (featureFlags.isEnabled('new-checkout-flow')) {
  return <NewCheckout />;
}
return <LegacyCheckout />;
```

Remove the flag after full rollout. Track removal with a follow-up ticket.

## Merge Strategy

| Strategy | When |
|----------|------|
| Rebase-merge | Each commit is meaningful and passes CI independently |
| Squash-merge | Noisy WIP commits; squash into one clean Conventional Commit |

Disable the merge commit button in repository settings. Default to squash-merge for most work.

## Stale Branch Cleanup

```bash
git branch -r --merged origin/main | grep -v 'main\\|release'
```

Enable automatic branch deletion on merge in repository settings.

## Rebase Conflict Recovery

```bash
# During a rebase that hits conflicts:
git status                    # see conflicting files
# Edit files to resolve
git add <resolved-files>
git rebase --continue         # repeat until done
git rebase --abort            # abandon and restore pre-rebase state
```

If you resolved wrong: `git reflog` shows every HEAD position. `git reset --hard HEAD@{N}` restores to before the rebase.

## Accidental Force-Push Recovery

```bash
# Find the pre-push commit:
git reflog show origin/feat/my-branch
# Or from another clone that still has the old ref:
git push origin <old-sha>:refs/heads/feat/my-branch --force-with-lease
```

If reflog is unavailable (CI runner, ephemeral clone), check the GitLab UI — merge request activity shows previous head SHAs.

## Stale Branch Automation

Set up a scheduled pipeline or local cron to prune:

```bash
# Delete remote branches merged into main and older than 14 days
git fetch --prune
for branch in $(git branch -r --merged origin/main | grep -v 'main\|release'); do
  last_commit=$(git log -1 --format="%ci" "$branch")
  if [[ "$last_commit" < "$(date -d '14 days ago' +%Y-%m-%d)" ]]; then
    git push origin --delete "${branch#origin/}"
  fi
done
```

Enable **Delete source branch** by default in project settings → Merge Requests.
