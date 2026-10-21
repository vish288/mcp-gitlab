"""GitLab API client using httpx."""

from __future__ import annotations

import asyncio
import copy
import http.cookiejar
import json
import math
import random
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, unquote

import httpx

from .config import GitLabConfig
from .exceptions import (
    GitLabApiError,
    GitLabAuthError,
    GitLabConnectionError,
    GitLabError,
    GitLabNotFoundError,
    GitLabRateLimitError,
    GitLabTimeoutError,
)

# Transport retry policy (R2). Idempotent GETs are retried on a transient
# upstream status; writes are never retried. httpx's AsyncHTTPTransport(retries=)
# already covers connection-level failures, so this layer only adds status
# retries. "Max 2 attempts" = the initial request plus at most one retry.
_RETRY_STATUSES = frozenset({502, 503, 504})
_MAX_ATTEMPTS = 2
_MAX_RETRY_AFTER = 5.0  # only honour a 429 Retry-After at most this long (seconds)
_jitter = random.SystemRandom()  # jitter source; SystemRandom sidesteps the S311 lint


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """Parse a ``Retry-After`` header to seconds-from-now, or None when absent.

    Both forms are handled: delta-seconds, and an HTTP-date (RFC 7231), which is
    converted to the delay from now. The result is clamped to >= 0 (a past date
    means "retry now") and non-finite values are rejected."""
    raw = resp.headers.get("Retry-After")
    if raw is None:
        return None
    raw = raw.strip()
    try:
        seconds = float(raw)
    except ValueError:
        try:
            when = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - datetime.now(timezone.utc)).total_seconds()
    if not math.isfinite(seconds):
        return None
    return max(0.0, seconds)


def _retry_delay(resp: httpx.Response) -> float | None:
    """Seconds to wait before retrying this response, or None to not retry.

    502/503/504 get a jittered backoff; a 429 is retried only when it names a
    ``Retry-After`` of at most ``_MAX_RETRY_AFTER`` seconds."""
    if resp.status_code in _RETRY_STATUSES:
        return _jitter.uniform(0.5, 1.5)
    if resp.status_code == 429:
        after = _retry_after_seconds(resp)
        if after is not None and after <= _MAX_RETRY_AFTER:
            return after
    return None


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

    def __init__(
        self,
        config: GitLabConfig | None = None,
        *,
        auth_headers: dict[str, str] | None = None,
    ) -> None:
        self.config = config or GitLabConfig.from_env()
        self.config.validate()
        if auth_headers is None:
            if self.config.credentials is not None:
                auth_headers = {}  # filled per request from the stored credentials
            elif self.config.token:
                auth_headers = {"PRIVATE-TOKEN": self.config.token}
            else:
                auth_headers = {}
        self._auth_headers = auth_headers
        # Stored OAuth credentials (local sign-in) that refresh themselves; None
        # for PAT and hosted-oauth modes, where with_bearer/_auth_headers apply.
        self._credentials = self.config.credentials
        self._client = httpx.AsyncClient(
            base_url=self.config.api_url,
            headers={"Content-Type": "application/json"},
            timeout=httpx.Timeout(self.config.timeout, connect=min(10, self.config.timeout)),
            verify=self.config.ssl_verify,
            # Reject every cookie. The GitLab REST API needs none, and in oauth
            # mode ``with_bearer`` shares this one client across users; without
            # this, a ``Set-Cookie`` (e.g. ``_gitlab_session``) would be stored
            # on the shared jar and replayed on another user's request — GitLab
            # honours session cookies on GET, so that is a cross-user identity
            # leak. An empty allowed_domains policy stores nothing.
            cookies=http.cookiejar.CookieJar(
                policy=http.cookiejar.DefaultCookiePolicy(allowed_domains=[])
            ),
            # verify= on the transport too: httpx 0.28 ignores the client-level
            # verify once a transport is supplied, but the client-level one is
            # still used for proxy mounts, so both carry the same value.
            transport=httpx.AsyncHTTPTransport(retries=2, verify=self.config.ssl_verify),
        )

    def with_bearer(self, token: str) -> GitLabClient:
        """Same connection pool, this request's OAuth token.

        Returns a shallow copy that shares ``_client`` (and so the pool); the
        caller must not close it. Used in oauth mode, where each MCP request
        carries a different user's GitLab token.
        """
        other = copy.copy(self)
        other._auth_headers = {"Authorization": f"Bearer {token}"}
        return other

    async def close(self) -> None:
        await self._client.aclose()
        if self._credentials is not None:
            await self._credentials.aclose()

    # ── HTTP helpers ──────────────────────────────────────────────

    async def _headers(self) -> dict[str, str]:
        """The auth headers for one request. Stored OAuth credentials refresh
        proactively (within the margin) and yield a fresh Bearer; everything
        else uses the static headers set at construction (or by with_bearer)."""
        if self._credentials is None:
            return self._auth_headers
        return {"Authorization": f"Bearer {await self._credentials.bearer()}"}

    @staticmethod
    def _reject_dot_segments(path: str) -> None:
        """Reject ``.``/``..`` path segments before they reach httpx.

        httpx resolves dot segments against the base URL, so an unencoded
        ``..`` in a caller-supplied value (a variable key, a discussion id)
        would walk the request up to a different endpoint — e.g.
        ``DELETE /projects/:id`` instead of ``.../variables/...``. The call
        sites URL-encode their inputs, but ``quote`` leaves ``.``/``..`` as-is,
        so this is the catch-all that also covers any missed or future site.
        """
        for segment in path.split("/"):
            if segment in (".", ".."):
                msg = f"Invalid path segment {segment!r}: '.' and '..' are not allowed"
                raise GitLabError(msg)

    def _unreachable(self, e: httpx.TransportError) -> GitLabConnectionError:
        # Strip any userinfo so a credential embedded in the URL never lands in an error.
        safe = httpx.URL(self.config.url).copy_with(username=None, password=None)
        msg = f"Cannot reach GitLab at {safe}: {e}"
        return GitLabConnectionError(msg)

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """One send path for every verb, so refresh-on-401 cannot drift between
        ``_request`` and ``get_paged``. On a 401 with stored credentials it
        refreshes once (covering revocation or clock skew) and retries; the
        refresh raises ``GitLabAuthError`` on failure rather than looping.

        R2: idempotent GETs are also retried on a transient upstream status
        (502/503/504, or a 429 naming a short ``Retry-After``) with jitter; writes
        are never retried. A timeout and an unreachable host become distinct
        expected errors (the split is ported from mcp-argocd), and a
        ``ConnectTimeout`` counts as unreachable. Connection-level failures are
        retried beneath this by ``AsyncHTTPTransport(retries=2)``.

        The refresh-on-401 retry sits inside the status-retry loop, so on the
        second attempt it can fire again: worst case is 4 sends (2 attempts, each
        a request plus one post-refresh request)."""
        self._reject_dot_segments(path)
        resp: httpx.Response
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                resp = await self._client.request(
                    method, path, headers=await self._headers(), **kwargs
                )
                if resp.status_code == 401 and self._credentials is not None:
                    await self._credentials.refresh()
                    resp = await self._client.request(
                        method, path, headers=await self._headers(), **kwargs
                    )
            except httpx.ConnectTimeout as e:
                # A connect timeout means the host was never reached — treat it as
                # unreachable, not slow (it is a TimeoutException subclass, so it
                # must be caught before the timeout branch).
                raise self._unreachable(e) from e
            except httpx.TimeoutException as e:
                msg = f"Request to GitLab timed out: {e}"
                raise GitLabTimeoutError(msg) from e
            except httpx.TransportError as e:
                raise self._unreachable(e) from e
            if method == "GET" and attempt < _MAX_ATTEMPTS:
                delay = _retry_delay(resp)
                if delay is not None:
                    await asyncio.sleep(delay)
                    continue
            return resp
        return resp  # pragma: no cover — the loop always returns

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

        resp = await self._send(method, path, **kwargs)

        self._raise_for_status(resp)
        return self._parse_body(resp, raw=raw)

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code in (401, 403):
            raise GitLabAuthError(resp.status_code, resp.text)
        if resp.status_code == 404:
            raise GitLabNotFoundError(resp.text)
        if resp.status_code == 429:
            raise GitLabRateLimitError(
                resp.status_code,
                resp.reason_phrase or "",
                resp.text,
                retry_after=_retry_after_seconds(resp),
            )
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
        resp = await self._send("GET", path, params=params)
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
