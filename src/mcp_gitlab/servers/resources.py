"""MCP resources for GitLab — curated rules and guides for Git/GitLab workflows."""

from __future__ import annotations

from .gitlab import mcp

# ════════════════════════════════════════════════════════════════════
# Rules
# ════════════════════════════════════════════════════════════════════


@mcp.resource(
    "resource://rules/gitlab-ci",
    name="GitLab CI/CD Pipeline Patterns",
    description=(
        "Workflow rules, DAG with needs, caching, artifact expiry, "
        "secrets, environment tracking, and anti-patterns for .gitlab-ci.yml"
    ),
    mime_type="text/markdown",
    tags={"rule", "gitlab", "ci"},
)
def gitlab_ci_rules() -> str:
    """GitLab CI/CD pipeline authoring patterns and anti-patterns."""
    return _GITLAB_CI_CONTENT


@mcp.resource(
    "resource://rules/git-workflow",
    name="Git Workflow Standards",
    description=(
        "Trunk-based development, branch naming, rebase discipline, "
        "safe force-push, feature flags, and merge strategy"
    ),
    mime_type="text/markdown",
    tags={"rule", "gitlab", "git"},
)
def git_workflow_rules() -> str:
    """Git workflow standards for trunk-based development."""
    return _GIT_WORKFLOW_CONTENT


@mcp.resource(
    "resource://rules/mr-hygiene",
    name="Merge Request Best Practices",
    description=(
        "MR size limits, description template, author/reviewer responsibilities, "
        "thread resolution, approval rules, and merge readiness"
    ),
    mime_type="text/markdown",
    tags={"rule", "gitlab", "merge-request"},
)
def mr_hygiene_rules() -> str:
    """Merge request best practices and review etiquette."""
    return _MR_HYGIENE_CONTENT


@mcp.resource(
    "resource://rules/conventional-commits",
    name="Conventional Commits Spec",
    description=(
        "Commit types, breaking changes, footers, scope conventions, "
        "and semantic-release integration"
    ),
    mime_type="text/markdown",
    tags={"rule", "gitlab", "git", "commits"},
)
def conventional_commits_rules() -> str:
    """Conventional Commits specification and semantic-release mapping."""
    return _CONVENTIONAL_COMMITS_CONTENT


# ════════════════════════════════════════════════════════════════════
# Guides
# ════════════════════════════════════════════════════════════════════


@mcp.resource(
    "resource://guides/code-review",
    name="Code Review Standards",
    description=(
        "Review priority order (Google Engineering Practices), "
        "Conventional Comments labels, turnaround expectations, and anti-patterns"
    ),
    mime_type="text/markdown",
    tags={"guide", "gitlab", "review"},
)
def code_review_guide() -> str:
    """Code review standards with Conventional Comments and priority order."""
    return _CODE_REVIEW_CONTENT


@mcp.resource(
    "resource://guides/codeowners",
    name="GitLab CODEOWNERS Reference",
    description=(
        "CODEOWNERS syntax, sections with required approvals, "
        "optional sections, owner types, and governance patterns"
    ),
    mime_type="text/markdown",
    tags={"guide", "gitlab", "codeowners"},
)
def codeowners_guide() -> str:
    """GitLab CODEOWNERS file reference and governance."""
    return _CODEOWNERS_CONTENT


# ════════════════════════════════════════════════════════════════════
# Content constants
# ════════════════════════════════════════════════════════════════════

_GITLAB_CI_CONTENT = """\
# GitLab CI/CD Pipeline Patterns

## Workflow Rules

Always define `workflow: rules` at the top level to prevent duplicate pipelines.

```yaml
workflow:
  rules:
    - if: $CI_COMMIT_TAG
      when: always
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      when: always
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: always
    - if: $CI_COMMIT_MESSAGE =~ /^chore\\(release\\):/
      when: never
    - when: never
```

## `rules:` Over `only:`/`except:`

`only`/`except` are deprecated since GitLab 12.3. Use `rules:` for all conditional job execution.

Rules evaluate top-to-bottom; the first match wins. Place exclusions first:

```yaml
build:
  rules:
    - if: $NOTIFY_ONLY == "true"
      when: never               # exclusion first
    - if: $CI_COMMIT_BRANCH
      when: on_success
```

## `when: manual` Behaviour

| Context | `allow_failure` default | Pipeline behaviour |
|---------|------------------------|-------------------|
| `when: manual` inside `rules:` | `false` | **Blocks** downstream stages until clicked |
| `when: manual` at top-level job | `true` | Does NOT block — pipeline continues |

Always set `allow_failure` explicitly when using `when: manual` inside `rules:`
to make intent clear.

## DAG with `needs:`

Use `needs:` to express actual job dependencies, not stage order.

```yaml
build:
  stage: build
  script: [make build]

test:unit:
  stage: test
  needs: [build]
  script: [make test-unit]

test:integration:
  stage: test
  needs: [build]            # runs in parallel with test:unit
  script: [make test-integration]

deploy:staging:
  stage: deploy
  needs: [test:unit, test:integration]
  script: [make deploy-staging]
```

Best practices:
- Use `needs: []` for jobs with zero dependencies (start immediately)
- Keep the DAG shallow — deep chains negate the parallelism benefit
- Limit to 50 `needs:` entries per job (GitLab hard limit)

## Notify-Slack Job Ordering

Pattern for downstream trigger for release notes + Slack posting:

```yaml
notify-slack:
  stage: notify
  needs: [prod:apply]           # MUST run after successful prod deploy
  rules:
    - if: $ENABLE_SLACK_NOTIFICATION == "true" && $CI_COMMIT_TAG
      when: on_success
    - when: never

notify-slack-manual:
  stage: notify
  needs: []                     # MUST have empty needs — independent trigger
  when: manual
  rules:
    - if: $ENABLE_SLACK_NOTIFICATION == "true"
      when: manual
    - when: never
```

## `NOTIFY_ONLY` Guard

All non-notify jobs must skip when `NOTIFY_ONLY == "true"`:

```yaml
build:
  rules:
    - if: $NOTIFY_ONLY == "true"
      when: never               # MUST be first rule
    - if: $CI_COMMIT_BRANCH
      when: on_success
```

## Caching

Scope cache by branch. Use `policy: pull` for consumers.

```yaml
cache:
  key: "$CI_COMMIT_REF_SLUG-node"
  fallback_keys:
    - "$CI_DEFAULT_BRANCH-node"
  paths: [node_modules/]
  policy: pull-push
```

## Artifacts

Always set `expire_in`. Default retention is forever.

```yaml
build:
  artifacts:
    paths: [dist/]
    expire_in: 1 week
```

## DRY Templates

Use `extends:` for shared config. Use `!reference []` for selective reuse.

```yaml
.deploy-base:
  image: alpine:3.19
  before_script:
    - apk add --no-cache curl

deploy:staging:
  extends: .deploy-base
  script: [./deploy.sh]
```

## Secrets

Store as masked + protected CI/CD variables in project settings. Never in YAML.

## Pipeline Cancellation

```yaml
default:
  interruptible: true      # all jobs unless overridden

deploy:prod:
  interruptible: false     # production deploys must not be cancelled
```

## `[skip ci]` — Never Use

`[skip ci]` blocks ALL pipelines including tag pipelines. Use workflow rules instead:

```yaml
workflow:
  rules:
    - if: $CI_COMMIT_MESSAGE =~ /^chore\\(release\\):/
      when: never
    - if: $CI_COMMIT_TAG
      when: always
```

## Security Scanning

```yaml
include:
  - template: Security/SAST.gitlab-ci.yml
  - template: Security/Dependency-Scanning.gitlab-ci.yml
  - template: Security/Secret-Detection.gitlab-ci.yml
```

## Efficiency Checklist

- [ ] `workflow: rules` defined — no duplicate pipelines
- [ ] `needs:` used for parallelism
- [ ] Cache scoped by branch with `fallback_keys`
- [ ] `expire_in` set on all artifacts
- [ ] `interruptible: true` on non-deploy jobs
- [ ] Hidden jobs (`.template`) used for DRY config
- [ ] Secrets in CI/CD settings, not in YAML
- [ ] `rules:` everywhere, no `only:`/`except:`
"""

_GIT_WORKFLOW_CONTENT = """\
# Git Workflow Standards

## Trunk-Based Development

`main` is always releasable. Feature branches are short-lived (2-3 days max), \
merged via rebase, and deleted after merge. Direct commits to `main` are prohibited \
except for automated release tooling.

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

Never force-push `main` or release branches. Never escalate to `--force` \
if `--force-with-lease` fails — fetch first and investigate.

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

Disable the merge commit button in repository settings. Default to squash-merge \
for most work.

## Stale Branch Cleanup

```bash
git branch -r --merged origin/main | grep -v 'main\\|release'
```

Enable automatic branch deletion on merge in repository settings.
"""

_MR_HYGIENE_CONTENT = """\
# Merge Request Best Practices

## Before Opening

- Self-review the diff in the platform UI
- Size: keep under **400 lines changed**, single concern
- CI green before requesting review
- Rebase on target branch

## Title

- Imperative mood, sentence case, max 72 characters
- Include ticket reference: `[PROJ-123] Add email login to auth service`

## Description Template

```markdown
## Summary
- What changed and why (2-5 bullets)
- Trade-offs or decisions for reviewers

## Test plan
- [ ] Unit tests added/updated
- [ ] Manually verified: [scenario]
- [ ] Edge case covered: [describe]

## References
- Ticket: [PROJ-123](link)
```

## Size

Under 400 lines. If larger:
1. Extract refactors into a prerequisite MR
2. Split by layer (data → logic → UI)
3. If unavoidable, document rationale in description

## Stacked MRs

For features exceeding 400 lines:
1. Base MR: shared types / data layer
2. Second MR: business logic
3. Third MR: UI layer

## Review Comments — Conventional Comments

```
blocking: SQL injection via string concatenation.
nit: Prefer const over let here.
suggestion: Consider Map instead of object for the cache.
question: Is the 5-second timeout intentional?
praise: Clean separation of validation from handler.
```

## Thread Resolution

All threads must be resolved before merge — no exceptions.

- Blocking comments: resolve only after code change pushed
- Non-blocking: resolve after responding
- If reviewer is unresponsive >24h: resolve with explanation and merge

## Pre-Merge Rebase

Always rebase immediately before merging. A 3-day-old green CI may be broken \
by intervening changes.

## Merge Checklist

- [ ] All review threads resolved
- [ ] CI green on rebased branch
- [ ] Required approvals obtained
- [ ] No WIP/Draft status
- [ ] Source branch deleted after merge
- [ ] Linked ticket status updated
"""

_CONVENTIONAL_COMMITS_CONTENT = """\
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
"""

_CODE_REVIEW_CONTENT = """\
# Code Review Standards

## Review Priority Order

From Google Engineering Practices — review in this order:

1. **Correctness**: Logic bugs, off-by-one, race conditions, null checks
2. **Security**: OWASP Top 10, input validation, secret handling
3. **Design**: Abstraction level, architecture fit, over/under-engineering
4. **Completeness**: Edge cases, error paths, missing scenarios
5. **Tests**: Meaningful assertions, behavior coverage, failure modes
6. **Readability**: Future maintainer comprehension, naming, flow
7. **Style**: Formatting, conventions — automate with linters (lowest priority)

## Conventional Comments

| Label | Author action |
|-------|---------------|
| `blocking:` | Must fix before merge |
| `nit:` | Author decides |
| `suggestion:` | No obligation, worth considering |
| `question:` | Answer the question |
| `thought:` | Read and acknowledge |
| `praise:` | No action — reinforces good patterns |
| `issue:` | Investigate and respond |
| `todo:` | Create follow-up ticket |

### Examples

```
blocking: SQL injection via string concatenation on line 42.
  Use parameterized queries or a whitelist of allowed columns.

nit: Prefer `const` over `let` — `config` is never reassigned.

suggestion: Consider `Map` instead of plain object for the cache.
  (non-blocking — current approach works fine)

praise: Clean separation of validation from handler.
```

## Reviewer Responsibilities

- Read the MR description and linked ticket first
- Check CI is green before starting review
- First response within **4 working hours**
- Limit to 2 rounds of feedback — schedule sync if major issues remain
- Do not approve without reading the diff
- Do not block on style issues linters should catch

## Author Responsibilities

- Respond to every comment
- Push response commits separately (not amended) for easy re-review
- Squash before merge, not before re-review
- If you disagree with a blocking comment, explain — never silently ignore

## Anti-Patterns

- **Rubber-stamping**: Approve without reading. Decline if you can't review properly.
- **Gatekeeping**: Blocking on trivial preferences. Reserve blocking for actual issues.
- **Review bombing**: 50+ comments at once. Prioritize by severity, suggest rework.
- **Scope creep**: "While you're here, also..." — create a separate ticket.
"""

_CODEOWNERS_CONTENT = """\
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
"""
