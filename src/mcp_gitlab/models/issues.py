"""Issue models."""

from __future__ import annotations

from .base import GitLabModel
from .common import Milestone, User


class Issue(GitLabModel):
    id: int
    iid: int
    title: str = ""
    description: str | None = None
    state: str = ""
    created_at: str = ""
    updated_at: str = ""
    closed_at: str | None = None
    author: User | None = None
    assignee: User | None = None
    assignees: list[User] = []
    labels: list[str] = []
    milestone: Milestone | None = None
    web_url: str = ""
    confidential: bool = False
    weight: int | None = None
