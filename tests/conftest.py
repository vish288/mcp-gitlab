"""Shared test fixtures for mcp-gitlab."""

from __future__ import annotations

import pytest
import respx

from mcp_gitlab.client import GitLabClient
from mcp_gitlab.config import GitLabConfig

TEST_URL = "https://gitlab.example.com"
TEST_TOKEN = "test-token"


@pytest.fixture
def config() -> GitLabConfig:
    return GitLabConfig(url=TEST_URL, token=TEST_TOKEN)


@pytest.fixture
def client(config: GitLabConfig) -> GitLabClient:
    return GitLabClient(config)


@pytest.fixture
def mock_api() -> respx.MockRouter:
    with respx.mock(base_url="https://gitlab.example.com/api/v4") as router:
        yield router
