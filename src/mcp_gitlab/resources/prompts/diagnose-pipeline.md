# Diagnose pipeline {pipeline_id} in project {project_id}

## Steps

1. **Fetch pipeline details** — use `gitlab_get_pipeline` with project_id="{project_id}" and pipeline_id="{pipeline_id}". Note the status, ref, and created timestamp.
2. **Identify failed jobs** — from the pipeline response, find jobs with status "failed". List each failed job with its name, stage, and runner.
3. **Get job logs** — for each failed job, use `gitlab_get_job_log` to retrieve the trace output. Focus on the last 100 lines where errors typically appear.
4. **Analyze errors** — for each failed job log, identify:
   - The root error message (compilation error, test failure, timeout, OOM, dependency issue)
   - Whether the failure is flaky (transient network issue, timing) or deterministic (code bug)
   - Any missing environment variables or secrets
5. **Suggest resolution** — for each failure:
   - If flaky: suggest retry via `gitlab_retry_job`
   - If deterministic: describe what code change or config fix is needed
   - If infra-related: flag for manual investigation
6. **Summary** — provide a table of failed jobs with diagnosis and recommended action.
