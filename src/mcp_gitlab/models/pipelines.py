"""Pipeline and job models."""

from __future__ import annotations

from .base import GitLabModel
from .common import User


class Pipeline(GitLabModel):
    id: int
    iid: int = 0
    status: str = ""
    ref: str = ""
    sha: str = ""
    web_url: str = ""
    created_at: str = ""
    updated_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    duration: float | None = None
    queued_duration: float | None = None
    source: str = ""
    user: User | None = None


class Job(GitLabModel):
    id: int
    name: str = ""
    stage: str = ""
    status: str = ""
    ref: str = ""
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    duration: float | None = None
    web_url: str = ""
    allow_failure: bool = False
    failure_reason: str | None = None
