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

## Security-Sensitive Review Checklist

When the MR touches auth, data handling, or external integrations:

- [ ] No secrets in code (use CI/CD variables)
- [ ] Input validation on all external inputs
- [ ] SQL/NoSQL injection prevention (parameterized queries)
- [ ] XSS prevention (output encoding, CSP headers)
- [ ] SSRF prevention (URL allowlists for outbound requests)
- [ ] Rate limiting on new endpoints
- [ ] Audit logging for sensitive operations
- [ ] Dependency versions checked against known CVEs

## Async Review Timing Expectations

| Situation | Target response |
|-----------|----------------|
| Same timezone, normal hours | 4h |
| Cross-timezone | Next business morning |
| Urgent/hotfix (labeled) | 2h |
| Large MR (>800 lines) | 8h (schedule dedicated block) |

## Large MR Review Strategy

For MRs >400 lines (when splitting isn't possible):

1. Read the MR description and linked ticket first
2. Review tests first — they explain intent
3. Review core logic changes before peripheral files
4. Use `changes` tab grouped by directory, not flat file list
5. Leave a summary comment after first pass before line-by-line
6. If overwhelmed: comment "suggestion: split this into X and Y for easier review"
