"""Merge request models."""

from __future__ import annotations

from .base import GitLabModel
from .common import Diff, DiffRefs, Milestone, PipelineRef, User


class MergeRequest(GitLabModel):
    id: int
    iid: int
    title: str = ""
    description: str | None = None
    state: str = ""
    merged_by: User | None = None
    merged_at: str | None = None
    created_at: str = ""
    updated_at: str = ""
    source_branch: str = ""
    target_branch: str = ""
    author: User | None = None
    assignee: User | None = None
    assignees: list[User] = []
    reviewers: list[User] = []
    labels: list[str] = []
    milestone: Milestone | None = None
    draft: bool = False
    merge_status: str = ""
    detailed_merge_status: str = ""
    sha: str = ""
    web_url: str = ""
    squash: bool = False
    changes_count: str = ""
    user_notes_count: int = 0
    has_conflicts: bool = False
    diff_refs: DiffRefs | None = None
    pipeline: PipelineRef | None = None


class MergeRequestChanges(MergeRequest):
    changes: list[Diff] = []
    overflow: bool = False


class Note(GitLabModel):
    id: int
    body: str = ""
    author: User | None = None
    created_at: str = ""
    updated_at: str = ""
    system: bool = False
    noteable_id: int = 0
    noteable_type: str = ""
    resolvable: bool = False
    resolved: bool = False
    resolved_by: User | None = None


class DiscussionPosition(GitLabModel):
    base_sha: str = ""
    start_sha: str = ""
    head_sha: str = ""
    position_type: str = "text"
    old_path: str = ""
    new_path: str = ""
    old_line: int | None = None
    new_line: int | None = None


class DiscussionNote(GitLabModel):
    id: int
    body: str = ""
    author: User | None = None
    created_at: str = ""
    updated_at: str = ""
    system: bool = False
    resolvable: bool = False
    resolved: bool = False
    resolved_by: User | None = None
    position: DiscussionPosition | None = None
    type: str | None = None


class Discussion(GitLabModel):
    id: str = ""
    individual_note: bool = False
    notes: list[DiscussionNote] = []
