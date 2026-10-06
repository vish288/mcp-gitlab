"""GitLab MCP server configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass
class GitLabConfig:
    """Configuration for the GitLab MCP server, loaded from environment variables."""

    url: str = ""
    token: str = ""
    read_only: bool = False
    timeout: int = 30
    ssl_verify: bool = True
    auth: str = "token"  # GITLAB_AUTH: "token" or "oauth"
    oauth_client_id: str = ""  # GITLAB_OAUTH_CLIENT_ID
    oauth_client_secret: str = ""  # GITLAB_OAUTH_CLIENT_SECRET
    oauth_base_url: str = ""  # GITLAB_OAUTH_BASE_URL, trailing slash stripped
    oauth_scopes: str = "api"  # GITLAB_OAUTH_SCOPES, space-separated
    oauth_jwt_key: str = ""  # GITLAB_OAUTH_JWT_KEY, else derived from the secret
    # LocalCredentials when the token came from `mcp-gitlab auth login`. Not read
    # by from_env() (that must not touch the filesystem); lifespan sets it.
    credentials: Any = None

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
            auth=os.getenv("GITLAB_AUTH", "token"),
            oauth_client_id=os.getenv("GITLAB_OAUTH_CLIENT_ID", ""),
            oauth_client_secret=os.getenv("GITLAB_OAUTH_CLIENT_SECRET", ""),
            oauth_base_url=os.getenv("GITLAB_OAUTH_BASE_URL", "").rstrip("/"),
            oauth_scopes=os.getenv("GITLAB_OAUTH_SCOPES", "api"),
            oauth_jwt_key=os.getenv("GITLAB_OAUTH_JWT_KEY", ""),
        )

    @property
    def api_url(self) -> str:
        return f"{self.url}/api/v4"

    @property
    def scopes(self) -> list[str]:
        return self.oauth_scopes.split()

    @property
    def token_scopes(self) -> list[str] | None:
        """Scopes of stored OAuth credentials, or None when not signed in
        locally. ``_check_write`` enforces ``api`` against these."""
        return self.credentials.scopes if self.credentials is not None else None

    def validate(self) -> None:
        if not self.url:
            msg = "GITLAB_URL environment variable is required"
            raise ValueError(msg)
        if self.auth not in ("token", "oauth"):
            msg = "GITLAB_AUTH must be 'token' or 'oauth'"
            raise ValueError(msg)
        if self.auth == "oauth":
            missing = [
                name
                for name, value in (
                    ("GITLAB_OAUTH_CLIENT_ID", self.oauth_client_id),
                    ("GITLAB_OAUTH_CLIENT_SECRET", self.oauth_client_secret),
                    ("GITLAB_OAUTH_BASE_URL", self.oauth_base_url),
                )
                if not value
            ]
            if missing:
                msg = f"OAuth mode requires: {', '.join(missing)}"
                raise ValueError(msg)
            return  # a GitLab PAT is not used in oauth mode
        if not self.token and self.credentials is None:
            msg = (
                "GitLab token is required. Set one of: GITLAB_TOKEN, GITLAB_PAT, "
                "GITLAB_PERSONAL_ACCESS_TOKEN, GITLAB_API_TOKEN, or run: mcp-gitlab auth login"
            )
            raise ValueError(msg)
