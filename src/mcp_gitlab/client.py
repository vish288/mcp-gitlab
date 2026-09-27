"""GitLab API client using httpx."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote, unquote

import httpx

from .config import GitLabConfig
from .exceptions import GitLabApiError, GitLabAuthError, GitLabNotFoundError

# Matches a GitLab project URL; captures the namespace/project path before any
# `/-/...` suffix (merge_requests, pipelines, issues, etc.).
_GITLAB_PROJECT_URL_RE = re.compile(r"https?://[^/]+/(.+?)(?:/-/.*)?/?$")


def parse_project_path(value: str) -> str:
    """Reduce a GitLab project URL to its ``namespace/project`` path.

    Values that are not URLs are returned unchanged, so this is safe to call on
    a raw project id or path.

    Single source of truth for this parse. It previously existed twice, and the
    copies disagreed: the server-side regex omitted the trailing ``/?``, so
    ``https://gitlab.com/g/p/`` yielded ``g/p/`` there and ``g/p`` here. The
    stray slash survived into the tool call, URL-encoded to ``g%2Fp%2F`` and
    404'd -- a trailing slash in a pasted URL was enough to make a project look
    missing.
    """
    if not value.startswith(("http://", "https://")):
        return value
    m = _GITLAB_PROJECT_URL_RE.match(value)
    return unquote(m.group(1)) if m else value


class GitLabClient:
    """Async HTTP client for the GitLab REST API v4.

    The public surface is the five HTTP verbs (``get``, ``post``, ``put``,
    ``delete``) plus ``get_paged`` for list endpoints; callers build the path
    inline. ``_encode_id`` turns a project/group id, path, or full URL into a
    path segment.
    """

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
        """Encode a project/group ID.

        Numeric IDs pass through, paths are URL-encoded, and full GitLab URLs
        (e.g. ``https://gitlab.com/group/project/-/merge_requests/42``) are
        reduced to the project path before encoding.
        """
        if isinstance(project_id, int):
            return str(project_id)
        project_id = parse_project_path(project_id)
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
    ) -> Any:
        """Make an API request and return parsed JSON (or raw text if raw=True)."""
        kwargs: dict[str, Any] = {"params": params}
        if json_data is not None:
            kwargs["json"] = json_data

        resp = await self._client.request(method, path, **kwargs)

        self._raise_for_status(resp)
        return self._parse_body(resp, raw=raw)

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code in (401, 403):
            raise GitLabAuthError(resp.status_code, resp.text)
        if resp.status_code == 404:
            raise GitLabNotFoundError(resp.text)
        if not resp.is_success:
            raise GitLabApiError(resp.status_code, resp.reason_phrase or "", resp.text)

    @staticmethod
    def _parse_body(resp: httpx.Response, *, raw: bool = False) -> Any:
        """Decode a successful response body. None for 204/empty.

        Shared by every request path so the HTML guard and the JSON error
        wording cannot drift between them.
        """
        if resp.status_code == 204 or not resp.content:
            return None

        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            msg = "Unexpected HTML response — check URL and authentication"
            raise GitLabApiError(resp.status_code, msg, resp.text[:500])

        if raw:
            return resp.text

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

    async def get_paged(
        self, path: str, params: dict[str, Any] | None = None
    ) -> tuple[list[Any], int | None]:
        """GET a list endpoint, returning (items, next_page).

        GitLab reports paging in response headers, which ``_request`` discards.
        Without them a capped list is indistinguishable from a complete one, so
        every list tool silently truncated with no way to ask for the rest.
        ``next_page`` is None on the last page.
        """
        resp = await self._client.request("GET", path, params=params)
        self._raise_for_status(resp)

        items = self._parse_body(resp)
        next_page = resp.headers.get("x-next-page") or None
        return (items or []), int(next_page) if next_page else None

    async def post(self, path: str, json_data: Any = None) -> Any:
        return await self._request("POST", path, json_data=json_data)

    async def put(
        self, path: str, json_data: Any = None, params: dict[str, Any] | None = None
    ) -> Any:
        return await self._request("PUT", path, json_data=json_data, params=params)

    async def delete(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("DELETE", path, params=params)

    # ── Merge requests ────────────────────────────────────────────
    # Kept because two callers each need them (the single-MR tool and the
    # merge-sequence tool); ``_mr_path`` is their shared path builder.

    def _mr_path(self, project_id: str | int, mr_iid: int) -> str:
        return f"/projects/{self._encode_id(project_id)}/merge_requests/{mr_iid}"

    async def get_merge_request(self, project_id: str | int, mr_iid: int) -> dict:
        return await self.get(self._mr_path(project_id, mr_iid))

    async def merge_merge_request(
        self, project_id: str | int, mr_iid: int, params: dict[str, Any] | None = None
    ) -> dict:
        return await self.put(f"{self._mr_path(project_id, mr_iid)}/merge", params or {})
