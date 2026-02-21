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
            result = await client.list_branches(123)
            assert len(result) == 2
            assert result[0]["name"] == "main"

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
