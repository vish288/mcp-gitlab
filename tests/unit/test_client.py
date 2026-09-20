"""Tests for GitLab API client."""

from __future__ import annotations

import httpx
import pytest
import respx

from mcp_gitlab.client import GitLabClient
from mcp_gitlab.config import GitLabConfig
from mcp_gitlab.exceptions import GitLabApiError, GitLabAuthError, GitLabNotFoundError

BASE = "https://gitlab.example.com/api/v4"


def _make_client() -> GitLabClient:
    return GitLabClient(GitLabConfig(url="https://gitlab.example.com", token="test-token"))


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
        """The client and the prompt helper must resolve a URL identically.

        They were separate regexes and disagreed on a trailing slash: the helper
        returned 'my-group/my-project/', which encoded to '...%2F' and 404'd, so
        a pasted URL ending in '/' made the project look missing.
        """
        from mcp_gitlab.client import parse_project_path
        from mcp_gitlab.servers._helpers import _parse_gitlab_project_url

        assert _parse_gitlab_project_url(url) == parse_project_path(url)
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
    @pytest.mark.asyncio
    async def test_get_project(self):
        async with respx.mock(base_url=BASE) as router:
            router.get("/projects/123").mock(
                return_value=httpx.Response(200, json={"id": 123, "name": "test"})
            )
            client = _make_client()
            result = await client.get_project(123)
            assert result["id"] == 123
            assert result["name"] == "test"

    @pytest.mark.asyncio
    async def test_auth_error_401(self):
        async with respx.mock(base_url=BASE) as router:
            router.get("/projects/123").mock(return_value=httpx.Response(401, text="Unauthorized"))
            client = _make_client()
            with pytest.raises(GitLabAuthError) as exc_info:
                await client.get_project(123)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_not_found_error(self):
        async with respx.mock(base_url=BASE) as router:
            router.get("/projects/999").mock(return_value=httpx.Response(404, text="Not Found"))
            client = _make_client()
            with pytest.raises(GitLabNotFoundError):
                await client.get_project(999)

    @pytest.mark.asyncio
    async def test_server_error(self):
        async with respx.mock(base_url=BASE) as router:
            router.get("/projects/123").mock(
                return_value=httpx.Response(500, text="Internal Server Error")
            )
            client = _make_client()
            with pytest.raises(GitLabApiError) as exc_info:
                await client.get_project(123)
            assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_html_response_error(self):
        async with respx.mock(base_url=BASE) as router:
            router.get("/projects/123").mock(
                return_value=httpx.Response(
                    200,
                    text="<html><body>Login</body></html>",
                    headers={"content-type": "text/html"},
                )
            )
            client = _make_client()
            with pytest.raises(GitLabApiError, match="HTML"):
                await client.get_project(123)

    @pytest.mark.asyncio
    async def test_html_response_error_on_raw_path(self):
        """A raw read must not hand back a login page as content.

        The raw return used to sit above the HTML guard, so an auth redirect
        made get_job_log return `<html>…Login…` as though it were a job trace.
        get_job_log is the only raw=True caller, and a trace is text/plain, so
        HTML here is always a failure rather than a payload.
        """
        async with respx.mock(base_url=BASE) as router:
            router.get("/projects/123/jobs/7/trace").mock(
                return_value=httpx.Response(
                    200,
                    text="<html><body>Login</body></html>",
                    headers={"content-type": "text/html"},
                )
            )
            client = _make_client()
            with pytest.raises(GitLabApiError, match="HTML"):
                await client.get_job_log(123, 7)

    @pytest.mark.asyncio
    async def test_raw_path_still_returns_plain_text(self):
        """The guard must not swallow legitimate raw traces."""
        async with respx.mock(base_url=BASE) as router:
            router.get("/projects/123/jobs/7/trace").mock(
                return_value=httpx.Response(
                    200,
                    text="$ echo build\nbuild ok\n",
                    headers={"content-type": "text/plain"},
                )
            )
            client = _make_client()
            assert "build ok" in await client.get_job_log(123, 7)

    @pytest.mark.asyncio
    async def test_empty_response(self):
        async with respx.mock(base_url=BASE) as router:
            router.delete("/projects/123").mock(return_value=httpx.Response(204))
            client = _make_client()
            result = await client.delete_project(123)
            assert result is None

    @pytest.mark.asyncio
    async def test_list_branches(self):
        async with respx.mock(base_url=BASE) as router:
            router.get("/projects/123/repository/branches").mock(
                return_value=httpx.Response(200, json=[{"name": "main"}, {"name": "develop"}])
            )
            client = _make_client()
            branches, next_page = await client.list_branches(123)
            assert len(branches) == 2
            assert branches[0]["name"] == "main"
            assert next_page is None  # no X-Next-Page header -> last page

    @pytest.mark.asyncio
    async def test_list_reports_next_page(self):
        """X-Next-Page is the only signal that a list was cut short."""
        async with respx.mock(base_url=BASE) as router:
            router.get("/projects/123/repository/branches").mock(
                return_value=httpx.Response(
                    200,
                    json=[{"name": "main"}],
                    headers={"X-Next-Page": "2", "X-Total-Pages": "7"},
                )
            )
            client = _make_client()
            branches, next_page = await client.list_branches(123)
            assert len(branches) == 1
            assert next_page == 2

    @pytest.mark.asyncio
    async def test_blank_next_page_header_means_last_page(self):
        """GitLab sends X-Next-Page as an empty string on the final page."""
        async with respx.mock(base_url=BASE) as router:
            router.get("/projects/123/repository/branches").mock(
                return_value=httpx.Response(
                    200, json=[{"name": "main"}], headers={"X-Next-Page": ""}
                )
            )
            client = _make_client()
            _branches, next_page = await client.list_branches(123)
            assert next_page is None

    @pytest.mark.asyncio
    async def test_create_merge_request(self):
        async with respx.mock(base_url=BASE) as router:
            router.post("/projects/123/merge_requests").mock(
                return_value=httpx.Response(201, json={"iid": 1, "title": "Test MR"})
            )
            client = _make_client()
            result = await client.create_merge_request(
                123,
                {
                    "source_branch": "feature",
                    "target_branch": "main",
                    "title": "Test MR",
                },
            )
            assert result["iid"] == 1

    @pytest.mark.asyncio
    async def test_get_job_log(self):
        async with respx.mock(base_url=BASE) as router:
            router.get("/projects/123/jobs/456/trace").mock(
                return_value=httpx.Response(200, text="line1\nline2\nline3")
            )
            client = _make_client()
            result = await client.get_job_log(123, 456)
            assert "line1" in result
            assert "line3" in result

    @pytest.mark.asyncio
    async def test_path_encoding(self):
        async with respx.mock(base_url=BASE) as router:
            route = router.get("/projects/my-group%2Fmy-project").mock(
                return_value=httpx.Response(200, json={"id": 1})
            )
            client = _make_client()
            await client.get_project("my-group/my-project")
            assert route.called
