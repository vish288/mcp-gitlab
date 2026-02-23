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

Always rebase immediately before merging. A 3-day-old green CI may be broken by intervening changes.

## Merge Checklist

- [ ] All review threads resolved
- [ ] CI green on rebased branch
- [ ] Required approvals obtained
- [ ] No WIP/Draft status
- [ ] Source branch deleted after merge
- [ ] Linked ticket status updated

## Handling Unresponsive Reviewers

| Elapsed | Action |
|---------|--------|
| 4h | Ping reviewer in MR comment |
| 24h | Ping on Slack/Teams, add a second reviewer |
| 48h | Resolve non-blocking threads yourself with explanation, escalate to team lead |

## Handling Failing CI in MR

1. Check if failure is related to your changes or a flaky test
2. If flaky: retry the job, add a comment noting the flake and link to tracking issue
3. If your change: fix before requesting re-review — never ask reviewers to review red CI
4. If infrastructure: comment with error, tag DevOps, set MR to Draft until resolved

## Draft → Ready Workflow

1. Open MR as Draft when: incomplete, needs early feedback, or CI experiments
2. Draft prefix `Draft:` prevents accidental merges (approval button disabled)
3. When ready: click **Mark as ready** (removes `Draft:` prefix)
4. Never self-approve immediately after undrafting — wait for fresh review
