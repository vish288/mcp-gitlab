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
    """Raised when a write operation cannot proceed.

    ``reason="read_only"`` (default): ``GITLAB_READ_ONLY=true``.
    ``reason="scope"``: oauth mode, the user's token lacks the ``api`` scope.
    """

    def __init__(self, reason: str = "read_only") -> None:
        self.reason = reason
        if reason == "scope":
            msg = "Write operations need the GitLab 'api' scope; this OAuth token has read_api only"
        else:
            msg = "Write operations are disabled (GITLAB_READ_ONLY=true)"
        super().__init__(msg)
