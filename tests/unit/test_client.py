"""Tests for GitLab API client."""

from __future__ import annotations

import httpx
import pytest

from mcp_gitlab.client import GitLabClient
from mcp_gitlab.exceptions import GitLabApiError, GitLabAuthError, GitLabNotFoundError


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
    async def test_get_project(self, client, mock_api):
        mock_api.get("/projects/123").mock(
            return_value=httpx.Response(200, json={"id": 123, "name": "test"})
        )
        result = await client.get_project(123)
        assert result["id"] == 123
        assert result["name"] == "test"

    async def test_auth_error_401(self, client, mock_api):
        mock_api.get("/projects/123").mock(return_value=httpx.Response(401, text="Unauthorized"))
        with pytest.raises(GitLabAuthError) as exc_info:
            await client.get_project(123)
        assert exc_info.value.status_code == 401

    async def test_not_found_error(self, client, mock_api):
        mock_api.get("/projects/999").mock(return_value=httpx.Response(404, text="Not Found"))
        with pytest.raises(GitLabNotFoundError):
            await client.get_project(999)

    async def test_server_error(self, client, mock_api):
        mock_api.get("/projects/123").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        with pytest.raises(GitLabApiError) as exc_info:
            await client.get_project(123)
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
            await client.get_project(123)

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
            await client.get_job_log(123, 7)

    async def test_raw_path_still_returns_plain_text(self, client, mock_api):
        """The guard must not swallow legitimate raw traces."""
        mock_api.get("/projects/123/jobs/7/trace").mock(
            return_value=httpx.Response(
                200,
                text="$ echo build\nbuild ok\n",
                headers={"content-type": "text/plain"},
            )
        )
        assert "build ok" in await client.get_job_log(123, 7)

    async def test_empty_response(self, client, mock_api):
        mock_api.delete("/projects/123").mock(return_value=httpx.Response(204))
        result = await client.delete_project(123)
        assert result is None

    async def test_list_branches(self, client, mock_api):
        mock_api.get("/projects/123/repository/branches").mock(
            return_value=httpx.Response(200, json=[{"name": "main"}, {"name": "develop"}])
        )
        branches, next_page = await client.list_branches(123)
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
        branches, next_page = await client.list_branches(123)
        assert len(branches) == 1
        assert next_page == 2

    async def test_blank_next_page_header_means_last_page(self, client, mock_api):
        """GitLab sends X-Next-Page as an empty string on the final page."""
        mock_api.get("/projects/123/repository/branches").mock(
            return_value=httpx.Response(200, json=[{"name": "main"}], headers={"X-Next-Page": ""})
        )
        _branches, next_page = await client.list_branches(123)
        assert next_page is None

    async def test_create_merge_request(self, client, mock_api):
        mock_api.post("/projects/123/merge_requests").mock(
            return_value=httpx.Response(201, json={"iid": 1, "title": "Test MR"})
        )
        result = await client.create_merge_request(
            123,
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
        result = await client.get_job_log(123, 456)
        assert "line1" in result
        assert "line3" in result

    async def test_path_encoding(self, client, mock_api):
        route = mock_api.get("/projects/my-group%2Fmy-project").mock(
            return_value=httpx.Response(200, json={"id": 1})
        )
        await client.get_project("my-group/my-project")
        assert route.called
