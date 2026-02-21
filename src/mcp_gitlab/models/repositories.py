"""Repository models: branches, commits, compare."""

from __future__ import annotations

from .base import GitLabModel
from .common import Diff


class Commit(GitLabModel):
    id: str = ""
    short_id: str = ""
    title: str = ""
    message: str = ""
    author_name: str = ""
    author_email: str = ""
    authored_date: str = ""
    committer_name: str = ""
    committer_email: str = ""
    committed_date: str = ""
    created_at: str = ""
    parent_ids: list[str] = []
    web_url: str = ""


class Branch(GitLabModel):
    name: str = ""
    merged: bool = False
    protected: bool = False
    default: bool = False
    developers_can_push: bool = False
    developers_can_merge: bool = False
    can_push: bool = False
    web_url: str = ""
    commit: Commit | None = None


class CompareResult(GitLabModel):
    commit: Commit | None = None
    commits: list[Commit] = []
    diffs: list[Diff] = []
    compare_timeout: bool = False
    compare_same_ref: bool = False
    web_url: str = ""
