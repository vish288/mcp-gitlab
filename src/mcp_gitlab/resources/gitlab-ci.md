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
    - if: $CI_COMMIT_MESSAGE =~ /^chore\(release\):/
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
    - if: $CI_COMMIT_MESSAGE =~ /^chore\(release\):/
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

## Debugging Failed Pipelines

1. Check the failed job log — scroll to the **first** error, not the last
2. Enable `CI_DEBUG_TRACE`:
   ```yaml
   variables:
     CI_DEBUG_TRACE: "true"
   ```
   Disable after debugging — it prints secrets.
3. Download artifacts for local analysis:
   ```bash
   curl --header "PRIVATE-TOKEN: $TOKEN"      "https://gitlab.example.com/api/v4/projects/:id/jobs/:job_id/artifacts"      -o artifacts.zip
   ```
4. Common failure patterns:
   - `exit code 137` — OOM kill. Increase runner memory or reduce parallelism.
   - `exit code 1` on `npm ci` — stale lockfile. Run `npm install` locally and commit.
   - `fatal: reference is not a tree` — shallow clone. Set `GIT_DEPTH: 0`.
   - `Permission denied` — check runner executor (Docker vs shell) and file permissions.
5. Re-run with `CI_DEBUG_SERVICES: "true"` to diagnose service container failures.
