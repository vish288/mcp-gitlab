# Conventional Commits Spec

## Format

```
type(scope): description

[optional body]

[optional footer(s)]
```

- **Subject line**: max 72 characters
- **Type**: lowercase, from allowed list
- **Scope**: optional, lowercase, kebab-case
- **Description**: imperative mood, lowercase first letter, no trailing period
- **Body**: wrapped at 72 chars, separated by blank line
- **Footer**: `token: value` format, separated by blank line

## Types

| Type | Changelog | Version bump |
|------|-----------|-------------|
| `feat` | Features | minor |
| `fix` | Bug Fixes | patch |
| `perf` | Performance | patch |
| `refactor` | — | none |
| `docs` | — | none |
| `style` | — | none |
| `test` | — | none |
| `build` | — | none |
| `ci` | — | none |
| `chore` | — | none |
| `revert` | Reverts | patch |
| Any + `!` or `BREAKING CHANGE:` | BREAKING CHANGES | major |

### Type Selection

- `fix` is for bugs only — use `chore` for deps, `refactor` for non-bug changes
- `feat` = new user-visible capability — internal plumbing is `refactor` or `chore`

## Scope Conventions

Use the module/component/service name:

```
feat(auth): add PKCE support
fix(cart): prevent negative quantities
ci(deploy): add smoke test
```

Lowercase, kebab-case. Omit when truly cross-cutting.

## Breaking Changes

```
# Option A: ! suffix
feat(auth)!: replace session tokens with JWTs

# Option B: footer
refactor(api): remove deprecated /v1 endpoints

BREAKING CHANGE: /v1/users and /v1/orders removed.
Migrate to /v2 equivalents.
```

Both trigger a MAJOR bump.

## Standard Footers

| Footer | Purpose |
|--------|---------|
| `Closes: TICKET-123` | Auto-closes linked issue |
| `Refs: TICKET-456` | References related issue |
| `BREAKING CHANGE:` | Documents breaking API change |

## Semantic-Release Mapping

```
feat → MINOR (1.x.0)
fix, perf, revert → PATCH (1.0.x)
BREAKING CHANGE or ! → MAJOR (x.0.0)
All other types → no release
```

## Commit Atomicity

Each commit = single logical change that compiles and passes tests. Enables:
- `git bisect` to find exact regression
- `git revert` to cleanly undo one change
- Cherry-picking to release branches

## Monorepo Scope Conventions

In a monorepo, scope identifies the package:

```
feat(api): add rate limiting
fix(web): correct hydration mismatch
chore(shared-types): bump version
```

Rules:
- Use the package/directory name as scope
- If change spans multiple packages: `feat(api,web): shared auth flow` or split into separate commits per package

## Squash Commit Type Selection

When squash-merging, the squash commit type should reflect the **primary** change:
- Mix of `feat` + `fix` → `feat` (the feature includes the fix)
- Mix of `fix` + `test` + `refactor` → `fix` (tests and refactoring support the fix)
- All `chore` → `chore`

The MR title determines the squash commit message — format it as a Conventional Commit.

## Revert Commit Format

```
revert: feat(auth): add PKCE support

This reverts commit abc1234.
Reason: PKCE flow breaks Safari 15 session handling.
Follow-up: PROJ-789
```

Revert commits trigger a PATCH bump. Always include: original commit reference, reason for revert, follow-up ticket.
