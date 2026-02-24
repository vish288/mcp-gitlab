"""GitLab MCP server configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class GitLabConfig:
    """Configuration for the GitLab MCP server, loaded from environment variables."""

    url: str = ""
    token: str = ""
    read_only: bool = False
    timeout: int = 30
    ssl_verify: bool = True

    @classmethod
    def from_env(cls) -> GitLabConfig:
        url = os.getenv("GITLAB_URL", "").rstrip("/")
        token = (
            os.getenv("GITLAB_TOKEN")
            or os.getenv("GITLAB_PAT")
            or os.getenv("GITLAB_PERSONAL_ACCESS_TOKEN")
            or os.getenv("GITLAB_API_TOKEN", "")
        )
        read_only = os.getenv("GITLAB_READ_ONLY", "false").lower() in (
            "true",
            "1",
            "yes",
        )
        timeout = int(os.getenv("GITLAB_TIMEOUT", "30"))
        ssl_verify = os.getenv("GITLAB_SSL_VERIFY", "true").lower() not in (
            "false",
            "0",
            "no",
        )

        return cls(
            url=url,
            token=token,
            read_only=read_only,
            timeout=timeout,
            ssl_verify=ssl_verify,
        )

    @property
    def api_url(self) -> str:
        return f"{self.url}/api/v4"

    def validate(self) -> None:
        if not self.url:
            msg = "GITLAB_URL environment variable is required"
            raise ValueError(msg)
        if not self.token:
            msg = (
                "GitLab token is required. Set one of: GITLAB_TOKEN, GITLAB_PAT, "
                "GITLAB_PERSONAL_ACCESS_TOKEN, or GITLAB_API_TOKEN"
            )
            raise ValueError(msg)
