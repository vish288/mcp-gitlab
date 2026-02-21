"""GitLab API exceptions."""

from __future__ import annotations


class GitLabError(Exception):
    """Base exception for GitLab operations."""


class GitLabApiError(GitLabError):
    """Raised when the GitLab API returns a non-success response."""

    def __init__(self, status_code: int, status_text: str, body: str = "") -> None:
        self.status_code = status_code
        self.status_text = status_text
        self.body = body
        super().__init__(f"GitLab API Error {status_code} {status_text}: {body}")


class GitLabAuthError(GitLabApiError):
    """Raised on 401/403 authentication failures."""

    def __init__(self, status_code: int, body: str = "") -> None:
        status_text = "Unauthorized" if status_code == 401 else "Forbidden"
        super().__init__(status_code, status_text, body)


class GitLabNotFoundError(GitLabApiError):
    """Raised on 404 responses."""

    def __init__(self, body: str = "") -> None:
        super().__init__(404, "Not Found", body)


class GitLabWriteDisabledError(GitLabError):
    """Raised when a write operation is attempted in read-only mode."""

    def __init__(self) -> None:
        super().__init__("Write operations are disabled (GITLAB_READ_ONLY=true)")
