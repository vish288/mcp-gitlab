"""GitLab API client using httpx."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import httpx

from .config import GitLabConfig
from .exceptions import GitLabApiError, GitLabAuthError, GitLabNotFoundError


class GitLabClient:
    """Async HTTP client for the GitLab REST API v4."""

    def __init__(self, config: GitLabConfig | None = None) -> None:
        self.config = config or GitLabConfig.from_env()
        self.config.validate()
        self._client = httpx.AsyncClient(
            base_url=self.config.api_url,
            headers={
                "PRIVATE-TOKEN": self.config.token,
                "Content-Type": "application/json",
            },
            timeout=self.config.timeout,
            verify=self.config.ssl_verify,
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ── HTTP helpers ──────────────────────────────────────────────

    @staticmethod
    def _encode_id(project_id: str | int) -> str:
        """Encode a project/group ID. Numeric IDs pass through; paths are URL-encoded."""
        if isinstance(project_id, int):
            return str(project_id)
        try:
            return str(int(project_id))
        except ValueError:
            return quote(project_id, safe="")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: Any = None,
        params: dict[str, Any] | None = None,
        raw: bool = False,
        content: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        """Make an API request and return parsed JSON (or raw text if raw=True)."""
        headers = {}
        if extra_headers:
            headers.update(extra_headers)

        kwargs: dict[str, Any] = {"params": params, "headers": headers}
        if json_data is not None:
            kwargs["json"] = json_data
        if content is not None:
            kwargs["content"] = content

        resp = await self._client.request(method, path, **kwargs)

        if resp.status_code in (401, 403):
            raise GitLabAuthError(resp.status_code, resp.text)
        if resp.status_code == 404:
            raise GitLabNotFoundError(resp.text)
        if not resp.is_success:
            raise GitLabApiError(resp.status_code, resp.reason_phrase or "", resp.text)

        if resp.status_code == 204 or not resp.content:
            return None

        if raw:
            return resp.text

        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            msg = "Unexpected HTML response — check URL and authentication"
            raise GitLabApiError(resp.status_code, msg, resp.text[:500])

        try:
            return resp.json()
        except json.JSONDecodeError as e:
            raise GitLabApiError(
                resp.status_code,
                f"JSON parse error: {e}",
                resp.text[:500],
            ) from e

    async def get(
        self, path: str, params: dict[str, Any] | None = None, *, raw: bool = False
    ) -> Any:
        return await self._request("GET", path, params=params, raw=raw)

    async def post(self, path: str, json_data: Any = None, **kwargs: Any) -> Any:
        return await self._request("POST", path, json_data=json_data, **kwargs)

    async def put(self, path: str, json_data: Any = None, **kwargs: Any) -> Any:
        return await self._request("PUT", path, json_data=json_data, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Any:
        return await self._request("DELETE", path, **kwargs)

    # ── Projects ──────────────────────────────────────────────────

    async def get_project(self, project_id: str | int) -> dict:
        enc = self._encode_id(project_id)
        return await self.get(f"/projects/{enc}")

    async def create_project(self, params: dict[str, Any]) -> dict:
        return await self.post("/projects", params)

    async def update_project(self, project_id: str | int, params: dict[str, Any]) -> dict:
        enc = self._encode_id(project_id)
        return await self.put(f"/projects/{enc}", params)

    async def delete_project(self, project_id: str | int) -> None:
        enc = self._encode_id(project_id)
        await self.delete(f"/projects/{enc}")

    # ── Project approvals ─────────────────────────────────────────

    async def get_project_approvals(self, project_id: str | int) -> dict:
        enc = self._encode_id(project_id)
        return await self.get(f"/projects/{enc}/approvals")

    async def update_project_approvals(self, project_id: str | int, params: dict[str, Any]) -> dict:
        enc = self._encode_id(project_id)
        return await self.post(f"/projects/{enc}/approvals", params)

    async def list_project_approval_rules(self, project_id: str | int) -> list[dict]:
        enc = self._encode_id(project_id)
        return await self.get(f"/projects/{enc}/approval_rules")

    async def create_project_approval_rule(
        self, project_id: str | int, params: dict[str, Any]
    ) -> dict:
        enc = self._encode_id(project_id)
        return await self.post(f"/projects/{enc}/approval_rules", params)

    async def update_project_approval_rule(
        self, project_id: str | int, rule_id: int, params: dict[str, Any]
    ) -> dict:
        enc = self._encode_id(project_id)
        return await self.put(f"/projects/{enc}/approval_rules/{rule_id}", params)

    async def delete_project_approval_rule(self, project_id: str | int, rule_id: int) -> None:
        enc = self._encode_id(project_id)
        await self.delete(f"/projects/{enc}/approval_rules/{rule_id}")

    # ── MR approval rules ─────────────────────────────────────────

    async def list_mr_approval_rules(self, project_id: str | int, mr_iid: int) -> list[dict]:
        enc = self._encode_id(project_id)
        return await self.get(f"/projects/{enc}/merge_requests/{mr_iid}/approval_rules")

    async def create_mr_approval_rule(
        self, project_id: str | int, mr_iid: int, params: dict[str, Any]
    ) -> dict:
        enc = self._encode_id(project_id)
        return await self.post(f"/projects/{enc}/merge_requests/{mr_iid}/approval_rules", params)

    async def update_mr_approval_rule(
        self, project_id: str | int, mr_iid: int, rule_id: int, params: dict[str, Any]
    ) -> dict:
        enc = self._encode_id(project_id)
        return await self.put(
            f"/projects/{enc}/merge_requests/{mr_iid}/approval_rules/{rule_id}", params
        )

    async def delete_mr_approval_rule(
        self, project_id: str | int, mr_iid: int, rule_id: int
    ) -> None:
        enc = self._encode_id(project_id)
        await self.delete(f"/projects/{enc}/merge_requests/{mr_iid}/approval_rules/{rule_id}")

    # ── Groups ────────────────────────────────────────────────────

    async def list_groups(self, params: dict[str, Any] | None = None) -> list[dict]:
        p = {"per_page": 50, **(params or {})}
        return await self.get("/groups", params=p)

    async def get_group(self, group_id: str | int) -> dict:
        enc = self._encode_id(group_id)
        return await self.get(f"/groups/{enc}")

    async def share_project_with_group(
        self, project_id: str | int, group_id: int, group_access: int
    ) -> None:
        enc = self._encode_id(project_id)
        await self.post(
            f"/projects/{enc}/share",
            {"group_id": group_id, "group_access": group_access},
        )

    async def unshare_project_with_group(self, project_id: str | int, group_id: int) -> None:
        enc = self._encode_id(project_id)
        await self.delete(f"/projects/{enc}/share/{group_id}")

    async def share_group_with_group(
        self, target_group_id: str | int, source_group_id: int, group_access: int
    ) -> None:
        enc = self._encode_id(target_group_id)
        await self.post(
            f"/groups/{enc}/share",
            {"group_id": source_group_id, "group_access": group_access},
        )

    async def unshare_group_with_group(
        self, target_group_id: str | int, source_group_id: int
    ) -> None:
        enc = self._encode_id(target_group_id)
        await self.delete(f"/groups/{enc}/share/{source_group_id}")

    # ── Branches ──────────────────────────────────────────────────

    async def list_branches(
        self, project_id: str | int, params: dict[str, Any] | None = None
    ) -> list[dict]:
        enc = self._encode_id(project_id)
        p = {"per_page": 100, **(params or {})}
        return await self.get(f"/projects/{enc}/repository/branches", params=p)

    async def create_branch(self, project_id: str | int, branch: str, ref: str) -> dict:
        enc = self._encode_id(project_id)
        return await self.post(
            f"/projects/{enc}/repository/branches",
            {"branch": branch, "ref": ref},
        )

    async def delete_branch(self, project_id: str | int, branch: str) -> None:
        enc = self._encode_id(project_id)
        await self.delete(f"/projects/{enc}/repository/branches/{quote(branch, safe='')}")

    # ── Commits ───────────────────────────────────────────────────

    async def list_commits(
        self, project_id: str | int, params: dict[str, Any] | None = None
    ) -> list[dict]:
        enc = self._encode_id(project_id)
        p = {"per_page": 40, **(params or {})}
        return await self.get(f"/projects/{enc}/repository/commits", params=p)

    async def get_commit(self, project_id: str | int, sha: str) -> dict:
        enc = self._encode_id(project_id)
        return await self.get(f"/projects/{enc}/repository/commits/{quote(sha, safe='')}")

    async def get_commit_diff(self, project_id: str | int, sha: str) -> list[dict]:
        enc = self._encode_id(project_id)
        return await self.get(f"/projects/{enc}/repository/commits/{quote(sha, safe='')}/diff")

    async def create_commit(self, project_id: str | int, params: dict[str, Any]) -> dict:
        enc = self._encode_id(project_id)
        return await self.post(f"/projects/{enc}/repository/commits", params)

    async def compare(self, project_id: str | int, from_ref: str, to_ref: str) -> dict:
        enc = self._encode_id(project_id)
        return await self.get(
            f"/projects/{enc}/repository/compare",
            params={"from": from_ref, "to": to_ref},
        )

    async def list_repository_tree(
        self, project_id: str | int, params: dict[str, Any] | None = None
    ) -> list[dict]:
        enc = self._encode_id(project_id)
        p = {"per_page": 100, "recursive": True, **(params or {})}
        return await self.get(f"/projects/{enc}/repository/tree", params=p)

    # ── Merge Requests ────────────────────────────────────────────

    async def list_merge_requests(
        self, project_id: str | int, params: dict[str, Any] | None = None
    ) -> list[dict]:
        enc = self._encode_id(project_id)
        p = {"per_page": 20, **(params or {})}
        return await self.get(f"/projects/{enc}/merge_requests", params=p)

    async def get_merge_request(self, project_id: str | int, mr_iid: int) -> dict:
        enc = self._encode_id(project_id)
        return await self.get(f"/projects/{enc}/merge_requests/{mr_iid}")

    async def create_merge_request(self, project_id: str | int, params: dict[str, Any]) -> dict:
        enc = self._encode_id(project_id)
        return await self.post(f"/projects/{enc}/merge_requests", params)

    async def update_merge_request(
        self, project_id: str | int, mr_iid: int, params: dict[str, Any]
    ) -> dict:
        enc = self._encode_id(project_id)
        return await self.put(f"/projects/{enc}/merge_requests/{mr_iid}", params)

    async def merge_merge_request(
        self, project_id: str | int, mr_iid: int, params: dict[str, Any] | None = None
    ) -> dict:
        enc = self._encode_id(project_id)
        return await self.put(f"/projects/{enc}/merge_requests/{mr_iid}/merge", params or {})

    async def rebase_merge_request(
        self, project_id: str | int, mr_iid: int, skip_ci: bool = False
    ) -> dict:
        enc = self._encode_id(project_id)
        return await self.put(
            f"/projects/{enc}/merge_requests/{mr_iid}/rebase",
            {"skip_ci": skip_ci},
        )

    async def get_merge_request_changes(self, project_id: str | int, mr_iid: int) -> dict:
        enc = self._encode_id(project_id)
        return await self.get(f"/projects/{enc}/merge_requests/{mr_iid}/changes")

    # ── MR Notes ──────────────────────────────────────────────────

    async def list_mr_notes(self, project_id: str | int, mr_iid: int) -> list[dict]:
        enc = self._encode_id(project_id)
        return await self.get(
            f"/projects/{enc}/merge_requests/{mr_iid}/notes",
            params={"per_page": 100},
        )

    async def add_mr_note(
        self,
        project_id: str | int,
        mr_iid: int,
        body: str,
        internal: bool = False,
    ) -> dict:
        enc = self._encode_id(project_id)
        data: dict[str, Any] = {"body": body}
        if internal:
            data["internal"] = True
        return await self.post(f"/projects/{enc}/merge_requests/{mr_iid}/notes", data)

    async def delete_mr_note(self, project_id: str | int, mr_iid: int, note_id: int) -> None:
        enc = self._encode_id(project_id)
        await self.delete(f"/projects/{enc}/merge_requests/{mr_iid}/notes/{note_id}")

    async def update_mr_note(
        self, project_id: str | int, mr_iid: int, note_id: int, body: str
    ) -> dict:
        enc = self._encode_id(project_id)
        return await self.put(
            f"/projects/{enc}/merge_requests/{mr_iid}/notes/{note_id}",
            {"body": body},
        )

    async def award_emoji(
        self, project_id: str | int, mr_iid: int, note_id: int, name: str
    ) -> dict:
        enc = self._encode_id(project_id)
        return await self.post(
            f"/projects/{enc}/merge_requests/{mr_iid}/notes/{note_id}/award_emoji",
            {"name": name},
        )

    async def delete_award_emoji(
        self, project_id: str | int, mr_iid: int, note_id: int, award_id: int
    ) -> None:
        enc = self._encode_id(project_id)
        await self.delete(
            f"/projects/{enc}/merge_requests/{mr_iid}/notes/{note_id}/award_emoji/{award_id}"
        )

    # ── MR Discussions ────────────────────────────────────────────

    async def list_mr_discussions(self, project_id: str | int, mr_iid: int) -> list[dict]:
        enc = self._encode_id(project_id)
        return await self.get(
            f"/projects/{enc}/merge_requests/{mr_iid}/discussions",
            params={"per_page": 100},
        )

    async def create_mr_discussion(
        self, project_id: str | int, mr_iid: int, params: dict[str, Any]
    ) -> dict:
        enc = self._encode_id(project_id)
        return await self.post(f"/projects/{enc}/merge_requests/{mr_iid}/discussions", params)

    async def reply_to_discussion(
        self, project_id: str | int, mr_iid: int, discussion_id: str, body: str
    ) -> dict:
        enc = self._encode_id(project_id)
        return await self.post(
            f"/projects/{enc}/merge_requests/{mr_iid}/discussions/{discussion_id}/notes",
            {"body": body},
        )

    async def resolve_discussion(
        self, project_id: str | int, mr_iid: int, discussion_id: str, resolved: bool
    ) -> dict:
        enc = self._encode_id(project_id)
        return await self.put(
            f"/projects/{enc}/merge_requests/{mr_iid}/discussions/{discussion_id}",
            {"resolved": resolved},
        )

    # ── Pipelines ─────────────────────────────────────────────────

    async def list_pipelines(
        self, project_id: str | int, params: dict[str, Any] | None = None
    ) -> list[dict]:
        enc = self._encode_id(project_id)
        p = {"per_page": 20, **(params or {})}
        return await self.get(f"/projects/{enc}/pipelines", params=p)

    async def get_pipeline(self, project_id: str | int, pipeline_id: int) -> dict:
        enc = self._encode_id(project_id)
        return await self.get(f"/projects/{enc}/pipelines/{pipeline_id}")

    async def list_pipeline_jobs(self, project_id: str | int, pipeline_id: int) -> list[dict]:
        enc = self._encode_id(project_id)
        return await self.get(
            f"/projects/{enc}/pipelines/{pipeline_id}/jobs",
            params={"per_page": 100},
        )

    async def create_pipeline(
        self,
        project_id: str | int,
        ref: str,
        variables: list[dict[str, str]] | None = None,
    ) -> dict:
        enc = self._encode_id(project_id)
        data: dict[str, Any] = {"ref": ref}
        if variables:
            data["variables"] = variables
        return await self.post(f"/projects/{enc}/pipeline", data)

    async def retry_pipeline(self, project_id: str | int, pipeline_id: int) -> dict:
        enc = self._encode_id(project_id)
        return await self.post(f"/projects/{enc}/pipelines/{pipeline_id}/retry")

    async def cancel_pipeline(self, project_id: str | int, pipeline_id: int) -> dict:
        enc = self._encode_id(project_id)
        return await self.post(f"/projects/{enc}/pipelines/{pipeline_id}/cancel")

    # ── Jobs ──────────────────────────────────────────────────────

    async def retry_job(self, project_id: str | int, job_id: int) -> dict:
        enc = self._encode_id(project_id)
        return await self.post(f"/projects/{enc}/jobs/{job_id}/retry")

    async def play_job(
        self,
        project_id: str | int,
        job_id: int,
        variables: list[dict[str, str]] | None = None,
    ) -> dict:
        enc = self._encode_id(project_id)
        data: dict[str, Any] = {}
        if variables:
            data["job_variables_attributes"] = variables
        return await self.post(f"/projects/{enc}/jobs/{job_id}/play", data or None)

    async def cancel_job(self, project_id: str | int, job_id: int) -> dict:
        enc = self._encode_id(project_id)
        return await self.post(f"/projects/{enc}/jobs/{job_id}/cancel")

    async def get_job_log(self, project_id: str | int, job_id: int) -> str:
        enc = self._encode_id(project_id)
        return await self.get(
            f"/projects/{enc}/jobs/{job_id}/trace",
            raw=True,
        )

    # ── Tags ──────────────────────────────────────────────────────

    async def list_tags(
        self, project_id: str | int, params: dict[str, Any] | None = None
    ) -> list[dict]:
        enc = self._encode_id(project_id)
        p = {"per_page": 20, **(params or {})}
        return await self.get(f"/projects/{enc}/repository/tags", params=p)

    async def get_tag(self, project_id: str | int, tag_name: str) -> dict:
        enc = self._encode_id(project_id)
        return await self.get(f"/projects/{enc}/repository/tags/{quote(tag_name, safe='')}")

    async def create_tag(self, project_id: str | int, params: dict[str, Any]) -> dict:
        enc = self._encode_id(project_id)
        return await self.post(f"/projects/{enc}/repository/tags", params)

    async def delete_tag(self, project_id: str | int, tag_name: str) -> None:
        enc = self._encode_id(project_id)
        await self.delete(f"/projects/{enc}/repository/tags/{quote(tag_name, safe='')}")

    # ── Releases ──────────────────────────────────────────────────

    async def list_releases(
        self, project_id: str | int, params: dict[str, Any] | None = None
    ) -> list[dict]:
        enc = self._encode_id(project_id)
        p = {"per_page": 20, **(params or {})}
        return await self.get(f"/projects/{enc}/releases", params=p)

    async def get_release(self, project_id: str | int, tag_name: str) -> dict:
        enc = self._encode_id(project_id)
        return await self.get(f"/projects/{enc}/releases/{quote(tag_name, safe='')}")

    async def create_release(self, project_id: str | int, params: dict[str, Any]) -> dict:
        enc = self._encode_id(project_id)
        return await self.post(f"/projects/{enc}/releases", params)

    async def update_release(
        self, project_id: str | int, tag_name: str, params: dict[str, Any]
    ) -> dict:
        enc = self._encode_id(project_id)
        return await self.put(f"/projects/{enc}/releases/{quote(tag_name, safe='')}", params)

    async def delete_release(self, project_id: str | int, tag_name: str) -> None:
        enc = self._encode_id(project_id)
        await self.delete(f"/projects/{enc}/releases/{quote(tag_name, safe='')}")

    # ── CI/CD Variables (Project) ─────────────────────────────────

    async def list_variables(self, project_id: str | int) -> list[dict]:
        enc = self._encode_id(project_id)
        return await self.get(f"/projects/{enc}/variables", params={"per_page": 100})

    async def create_variable(self, project_id: str | int, params: dict[str, Any]) -> dict:
        enc = self._encode_id(project_id)
        return await self.post(f"/projects/{enc}/variables", params)

    async def update_variable(
        self,
        project_id: str | int,
        key: str,
        params: dict[str, Any],
        environment_scope: str | None = None,
    ) -> dict:
        enc = self._encode_id(project_id)
        query: dict[str, Any] = {}
        if environment_scope:
            query["filter[environment_scope]"] = environment_scope
        return await self.put(f"/projects/{enc}/variables/{key}", params, params=query)

    async def delete_variable(
        self,
        project_id: str | int,
        key: str,
        environment_scope: str | None = None,
    ) -> None:
        enc = self._encode_id(project_id)
        query: dict[str, Any] = {}
        if environment_scope:
            query["filter[environment_scope]"] = environment_scope
        await self.delete(f"/projects/{enc}/variables/{key}", params=query)

    # ── CI/CD Variables (Group) ───────────────────────────────────

    async def list_group_variables(self, group_id: str | int) -> list[dict]:
        enc = self._encode_id(group_id)
        return await self.get(f"/groups/{enc}/variables", params={"per_page": 100})

    async def create_group_variable(self, group_id: str | int, params: dict[str, Any]) -> dict:
        enc = self._encode_id(group_id)
        return await self.post(f"/groups/{enc}/variables", params)

    async def update_group_variable(
        self, group_id: str | int, key: str, params: dict[str, Any]
    ) -> dict:
        enc = self._encode_id(group_id)
        return await self.put(f"/groups/{enc}/variables/{key}", params)

    async def delete_group_variable(self, group_id: str | int, key: str) -> None:
        enc = self._encode_id(group_id)
        await self.delete(f"/groups/{enc}/variables/{key}")

    # ── Issues ────────────────────────────────────────────────────

    async def list_issues(
        self, project_id: str | int, params: dict[str, Any] | None = None
    ) -> list[dict]:
        enc = self._encode_id(project_id)
        p = {"per_page": 20, **(params or {})}
        return await self.get(f"/projects/{enc}/issues", params=p)

    async def get_issue(self, project_id: str | int, issue_iid: int) -> dict:
        enc = self._encode_id(project_id)
        return await self.get(f"/projects/{enc}/issues/{issue_iid}")

    async def create_issue(self, project_id: str | int, params: dict[str, Any]) -> dict:
        enc = self._encode_id(project_id)
        return await self.post(f"/projects/{enc}/issues", params)

    async def update_issue(
        self, project_id: str | int, issue_iid: int, params: dict[str, Any]
    ) -> dict:
        enc = self._encode_id(project_id)
        return await self.put(f"/projects/{enc}/issues/{issue_iid}", params)

    async def add_issue_comment(self, project_id: str | int, issue_iid: int, body: str) -> dict:
        enc = self._encode_id(project_id)
        return await self.post(f"/projects/{enc}/issues/{issue_iid}/notes", {"body": body})
