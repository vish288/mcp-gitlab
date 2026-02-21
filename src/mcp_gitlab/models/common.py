"""Common GitLab models shared across domains."""

from __future__ import annotations

from .base import GitLabModel


class User(GitLabModel):
    id: int
    username: str = ""
    name: str = ""
    state: str = ""
    avatar_url: str | None = None
    web_url: str = ""


class Namespace(GitLabModel):
    id: int
    name: str = ""
    path: str = ""
    kind: str = ""
    full_path: str = ""


class Milestone(GitLabModel):
    id: int
    title: str = ""


class DiffRefs(GitLabModel):
    base_sha: str = ""
    head_sha: str = ""
    start_sha: str = ""


class PipelineRef(GitLabModel):
    id: int
    status: str = ""
    web_url: str = ""


class Diff(GitLabModel):
    old_path: str = ""
    new_path: str = ""
    a_mode: str = ""
    b_mode: str = ""
    diff: str = ""
    new_file: bool = False
    renamed_file: bool = False
    deleted_file: bool = False
