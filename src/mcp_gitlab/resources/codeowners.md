# GitLab CODEOWNERS Reference

## File Location

GitLab searches in order:
1. `CODEOWNERS` (root)
2. `docs/CODEOWNERS`
3. `.gitlab/CODEOWNERS` (preferred)

## Syntax

```
# pattern   @owner(s)
*                       @team-lead
/src/auth/              @security-team
/src/payments/          @payments-team @security-team
/.gitlab-ci.yml         @devops-team
*.tf                    @sre-team
```

Last matching pattern wins. More specific patterns after general ones.

## Pattern Rules

| Pattern | Matches |
|---------|---------|
| `*` | Everything |
| `/src/` | Only top-level `src/` |
| `src/` | Any `src/` at any depth |
| `*.js` | All `.js` files anywhere |
| `/docs/**/*.md` | Markdown in `/docs/` and subdirectories |

## Sections (GitLab Premium+)

```
[Security] @security-team
/src/auth/
/src/crypto/

[Platform][2] @sre-team @devops-team
/infra/
/.gitlab-ci.yml

^[Documentation]
/docs/
*.md
```

- `[Name]` — 1 approval required (default)
- `[Name][2]` — 2 approvals required
- `^[Name]` — optional (approval requested but not required)

## Owner Types

```
/src/auth/     @john.doe          # individual
/src/auth/     @myorg/security    # group
/src/payments/ @team-a @team-b    # multiple (any can approve)
```

## Governance

- Review quarterly: remove departed members, update team names
- Use groups over individuals
- Keep patterns specific — broad `*` creates noise
- Protect the CODEOWNERS file itself:

```
/.gitlab/CODEOWNERS  @platform-lead
```

## Handling Departing Team Members

When someone leaves the team:

1. Replace their `@username` with a group `@team-name` (never leave stale usernames)
2. Check CODEOWNERS entries are covered — orphaned paths get zero required approvals
3. Audit quarterly: `grep -n '@' CODEOWNERS | sort -t@ -k2` and cross-reference with    active team roster
4. Use groups (`@org/team`) instead of individuals to avoid this problem

## Wildcard Pitfalls

- `*` at root level matches **every** file — creates review noise for everyone
- `*.js` matches `src/foo.js` AND `docs/config.js` — use path prefixes for precision
- Last matching pattern wins — a broad `*` at the end overrides all earlier patterns
- Test changes with: `git diff --name-only main | while read f; do echo "$f:";   git check-attr -a "$f"; done`

## Troubleshooting "No Approvers Matched"

Causes:
1. Pattern doesn't match the changed file paths — check with `git diff --name-only`
2. Owner is an individual who left — replace with group
3. Group doesn't have access to the project — share project with group first
4. Section requires N approvals but group has <N members with project access
5. CODEOWNERS file is in wrong location — check `.gitlab/CODEOWNERS` first
