"""Tests for GitLab API client."""

from __future__ import annotations

import time

import httpx
import pytest
import respx

from mcp_gitlab.client import GitLabClient
from mcp_gitlab.config import GitLabConfig
from mcp_gitlab.exceptions import (
    GitLabApiError,
    GitLabAuthError,
    GitLabError,
    GitLabNotFoundError,
)
from mcp_gitlab.local_auth import CredentialStore

TEST_URL = "https://gitlab.example.com"


def _rotated_token(access="at-2", refresh="rt-2"):
    return httpx.Response(
        200,
        json={
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": 7200,
            "scope": "api",
            "created_at": int(time.time()),
        },
    )


class TestEncodeId:
    def test_numeric_string(self):
        assert GitLabClient._encode_id("123") == "123"

    def test_integer(self):
        assert GitLabClient._encode_id(123) == "123"

    def test_path(self):
        assert GitLabClient._encode_id("my-group/my-project") == "my-group%2Fmy-project"

    def test_project_url(self):
        assert (
            GitLabClient._encode_id("https://gitlab.com/my-group/my-project")
            == "my-group%2Fmy-project"
        )

    def test_project_url_trailing_slash(self):
        assert (
            GitLabClient._encode_id("https://gitlab.com/my-group/my-project/")
            == "my-group%2Fmy-project"
        )

    def test_mr_url(self):
        assert (
            GitLabClient._encode_id("https://gitlab.com/my-group/my-project/-/merge_requests/42")
            == "my-group%2Fmy-project"
        )

    @pytest.mark.parametrize(
        "url",
        [
            "https://gitlab.com/my-group/my-project",
            "https://gitlab.com/my-group/my-project/",
            "https://gitlab.com/my-group/my-project/-/merge_requests/42",
            "https://gitlab.com/my-group/my-project/-/pipelines/7",
            "my-group/my-project",
        ],
    )
    def test_both_parsers_agree(self, url):
        """parse_project_path never returns a trailing slash.

        A trailing slash in a pasted URL encodes to '...%2F' and 404s,
        so the parser must always strip it.
        """
        from mcp_gitlab.client import parse_project_path

        assert not parse_project_path(url).endswith("/")

    def test_pipeline_url(self):
        assert (
            GitLabClient._encode_id("https://gitlab.example.com/g/sub/proj/-/pipelines/999")
            == "g%2Fsub%2Fproj"
        )

    def test_issue_url_nested_group(self):
        assert (
            GitLabClient._encode_id("https://gitlab.example.com/top/mid/proj/-/issues/7")
            == "top%2Fmid%2Fproj"
        )

    def test_self_hosted_with_port(self):
        assert GitLabClient._encode_id("http://gitlab.local:8080/g/p") == "g%2Fp"


class TestRequest:
    async def test_get_project(self, client, mock_api):
        mock_api.get("/projects/123").mock(
            return_value=httpx.Response(200, json={"id": 123, "name": "test"})
        )
        result = await client.get("/projects/123")
        assert result["id"] == 123
        assert result["name"] == "test"

    async def test_auth_error_401(self, client, mock_api):
        mock_api.get("/projects/123").mock(return_value=httpx.Response(401, text="Unauthorized"))
        with pytest.raises(GitLabAuthError) as exc_info:
            await client.get("/projects/123")
        assert exc_info.value.status_code == 401

    async def test_not_found_error(self, client, mock_api):
        mock_api.get("/projects/999").mock(return_value=httpx.Response(404, text="Not Found"))
        with pytest.raises(GitLabNotFoundError):
            await client.get("/projects/999")

    async def test_server_error(self, client, mock_api):
        mock_api.get("/projects/123").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        with pytest.raises(GitLabApiError) as exc_info:
            await client.get("/projects/123")
        assert exc_info.value.status_code == 500

    async def test_html_response_error(self, client, mock_api):
        mock_api.get("/projects/123").mock(
            return_value=httpx.Response(
                200,
                text="<html><body>Login</body></html>",
                headers={"content-type": "text/html"},
            )
        )
        with pytest.raises(GitLabApiError, match="HTML"):
            await client.get("/projects/123")

    async def test_html_response_error_on_raw_path(self, client, mock_api):
        """A raw read must not hand back a login page as content.

        The raw return used to sit above the HTML guard, so an auth redirect
        made get_job_log return `<html>…Login…` as though it were a job trace.
        get_job_log is the only raw=True caller, and a trace is text/plain, so
        HTML here is always a failure rather than a payload.
        """
        mock_api.get("/projects/123/jobs/7/trace").mock(
            return_value=httpx.Response(
                200,
                text="<html><body>Login</body></html>",
                headers={"content-type": "text/html"},
            )
        )
        with pytest.raises(GitLabApiError, match="HTML"):
            await client.get("/projects/123/jobs/7/trace", raw=True)

    async def test_raw_path_still_returns_plain_text(self, client, mock_api):
        """The guard must not swallow legitimate raw traces."""
        mock_api.get("/projects/123/jobs/7/trace").mock(
            return_value=httpx.Response(
                200,
                text="$ echo build\nbuild ok\n",
                headers={"content-type": "text/plain"},
            )
        )
        assert "build ok" in await client.get("/projects/123/jobs/7/trace", raw=True)

    async def test_empty_response(self, client, mock_api):
        mock_api.delete("/projects/123").mock(return_value=httpx.Response(204))
        result = await client.delete("/projects/123")
        assert result is None

    async def test_list_branches(self, client, mock_api):
        mock_api.get("/projects/123/repository/branches").mock(
            return_value=httpx.Response(200, json=[{"name": "main"}, {"name": "develop"}])
        )
        branches, next_page = await client.get_paged("/projects/123/repository/branches")
        assert len(branches) == 2
        assert branches[0]["name"] == "main"
        assert next_page is None  # no X-Next-Page header -> last page

    async def test_list_reports_next_page(self, client, mock_api):
        """X-Next-Page is the only signal that a list was cut short."""
        mock_api.get("/projects/123/repository/branches").mock(
            return_value=httpx.Response(
                200,
                json=[{"name": "main"}],
                headers={"X-Next-Page": "2", "X-Total-Pages": "7"},
            )
        )
        branches, next_page = await client.get_paged("/projects/123/repository/branches")
        assert len(branches) == 1
        assert next_page == 2

    async def test_blank_next_page_header_means_last_page(self, client, mock_api):
        """GitLab sends X-Next-Page as an empty string on the final page."""
        mock_api.get("/projects/123/repository/branches").mock(
            return_value=httpx.Response(200, json=[{"name": "main"}], headers={"X-Next-Page": ""})
        )
        _branches, next_page = await client.get_paged("/projects/123/repository/branches")
        assert next_page is None

    async def test_create_merge_request(self, client, mock_api):
        mock_api.post("/projects/123/merge_requests").mock(
            return_value=httpx.Response(201, json={"iid": 1, "title": "Test MR"})
        )
        result = await client.post(
            "/projects/123/merge_requests",
            {
                "source_branch": "feature",
                "target_branch": "main",
                "title": "Test MR",
            },
        )
        assert result["iid"] == 1

    async def test_get_job_log(self, client, mock_api):
        mock_api.get("/projects/123/jobs/456/trace").mock(
            return_value=httpx.Response(200, text="line1\nline2\nline3")
        )
        result = await client.get("/projects/123/jobs/456/trace", raw=True)
        assert "line1" in result
        assert "line3" in result

    async def test_path_encoding(self, client, mock_api):
        route = mock_api.get("/projects/my-group%2Fmy-project").mock(
            return_value=httpx.Response(200, json={"id": 1})
        )
        await client.get(f"/projects/{GitLabClient._encode_id('my-group/my-project')}")
        assert route.called

    @pytest.mark.parametrize("bad", ["/projects/1/variables/..", "/projects/1/../2", "/.."])
    async def test_send_rejects_dot_segments(self, client, mock_api, bad):
        """R01: a '.'/'..' path segment is rejected before httpx can collapse it
        and walk the request onto a different endpoint."""
        mock_api._assert_all_called = False
        trap = mock_api.route().mock(return_value=httpx.Response(200, json={}))
        with pytest.raises(GitLabError):
            await client.get(bad)
        assert not trap.called


class TestAuthHeaders:
    async def test_private_token_header_unchanged(self, client, mock_api):
        """R16: token mode still sends PRIVATE-TOKEN on a plain GET and on get_paged."""
        get = mock_api.get("/projects/1").mock(return_value=httpx.Response(200, json={"id": 1}))
        await client.get("/projects/1")
        assert get.calls.last.request.headers["PRIVATE-TOKEN"] == "test-token"

        paged = mock_api.get("/projects/1/issues").mock(return_value=httpx.Response(200, json=[]))
        await client.get_paged("/projects/1/issues")
        assert paged.calls.last.request.headers["PRIVATE-TOKEN"] == "test-token"

    async def test_with_bearer_shares_pool_and_sets_header(self, client, mock_api):
        other = client.with_bearer("glo-token")
        assert other._client is client._client  # same connection pool

        route = mock_api.get("/projects/1").mock(return_value=httpx.Response(200, json={"id": 1}))
        await other.get("/projects/1")
        req = route.calls.last.request
        assert req.headers["Authorization"] == "Bearer glo-token"
        assert "PRIVATE-TOKEN" not in req.headers

        await client.get("/projects/1")  # original still sends PRIVATE-TOKEN
        req2 = route.calls.last.request
        assert req2.headers["PRIVATE-TOKEN"] == "test-token"
        assert "Authorization" not in req2.headers

    async def test_no_token_no_auth_header(self, mock_api):
        """OAuth-mode config (no PAT) builds a client with no PRIVATE-TOKEN header."""
        from mcp_gitlab.config import GitLabConfig

        gl = GitLabClient(
            GitLabConfig(
                url="https://gitlab.example.com",
                auth="oauth",
                oauth_client_id="app",
                oauth_client_secret="s3cret",
                oauth_base_url="https://mcp.example.com",
            )
        )
        route = mock_api.get("/projects/1").mock(return_value=httpx.Response(200, json={"id": 1}))
        await gl.get("/projects/1")
        assert "PRIVATE-TOKEN" not in route.calls.last.request.headers
        await gl.close()

    async def test_set_cookie_is_not_stored_or_replayed(self, client, mock_api):
        """Security: a Set-Cookie from GitLab must not persist on the shared
        client (``with_bearer`` shares it across users) nor be sent on the next
        request. Otherwise a ``_gitlab_session`` cookie would leak between users
        in oauth mode."""
        mock_api.get("/projects/1").mock(
            return_value=httpx.Response(
                200, json={"id": 1}, headers={"Set-Cookie": "_gitlab_session=abc; Path=/"}
            )
        )
        await client.get("/projects/1")
        assert len(client._client.cookies.jar) == 0  # nothing stored

        nxt = mock_api.get("/projects/2").mock(return_value=httpx.Response(200, json={"id": 2}))
        await client.get("/projects/2")
        assert "cookie" not in nxt.calls.last.request.headers  # nothing replayed


class TestLocalCredentials:
    """R5/R6: stored OAuth credentials send Bearer and refresh on 401."""

    def _creds(self, tmp_path, *, expires_at):
        store = CredentialStore(tmp_path / "credentials.json")
        store.save(
            TEST_URL,
            {
                "client_id": "cid",
                "access_token": "at",
                "refresh_token": "rt",
                "expires_at": expires_at,
                "scopes": ["api"],
            },
        )
        return store.load(TEST_URL)

    async def test_credentials_use_bearer_header(self, tmp_path):
        creds = self._creds(tmp_path, expires_at=9999999999)
        gl = GitLabClient(GitLabConfig(url=TEST_URL, token="", credentials=creds))
        with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
            route = router.get("/api/v4/projects/1").mock(
                return_value=httpx.Response(200, json={"id": 1})
            )
            await gl.get("/projects/1")
        req = route.calls.last.request
        assert req.headers["Authorization"] == "Bearer at"
        assert "PRIVATE-TOKEN" not in req.headers
        await gl.close()

    async def test_401_triggers_refresh_and_retry(self, tmp_path):
        creds = self._creds(tmp_path, expires_at=9999999999)  # fresh: no proactive refresh
        gl = GitLabClient(GitLabConfig(url=TEST_URL, token="", credentials=creds))
        with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
            get = router.get("/api/v4/projects/1").mock(
                side_effect=[httpx.Response(401), httpx.Response(200, json={"id": 1})]
            )
            router.post("/oauth/token").mock(return_value=_rotated_token())
            result = await gl.get("/projects/1")
        assert result["id"] == 1
        assert get.call_count == 2
        assert get.calls.last.request.headers["Authorization"] == "Bearer at-2"
        await gl.close()

    async def test_401_refresh_failure_raises_auth_error_once(self, tmp_path):
        creds = self._creds(tmp_path, expires_at=9999999999)
        gl = GitLabClient(GitLabConfig(url=TEST_URL, token="", credentials=creds))
        with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
            get = router.get("/api/v4/projects/1").mock(return_value=httpx.Response(401))
            router.post("/oauth/token").mock(
                return_value=httpx.Response(400, json={"error": "invalid_grant"})
            )
            with pytest.raises(GitLabAuthError):
                await gl.get("/projects/1")
        assert get.call_count == 1  # no infinite retry: refresh failure stops it
        await gl.close()

    async def test_get_paged_also_refreshes(self, tmp_path):
        creds = self._creds(tmp_path, expires_at=9999999999)
        gl = GitLabClient(GitLabConfig(url=TEST_URL, token="", credentials=creds))
        with respx.mock(base_url=TEST_URL, assert_all_called=False) as router:
            get = router.get("/api/v4/projects/1/issues").mock(
                side_effect=[httpx.Response(401), httpx.Response(200, json=[{"id": 9}])]
            )
            router.post("/oauth/token").mock(return_value=_rotated_token())
            items, _ = await gl.get_paged("/projects/1/issues")
        assert items == [{"id": 9}]
        assert get.call_count == 2
        await gl.close()
