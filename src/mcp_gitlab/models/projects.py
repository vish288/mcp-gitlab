"""Project and group models."""

from __future__ import annotations

from .base import GitLabModel
from .common import Namespace


class SharedWithGroup(GitLabModel):
    group_id: int
    group_name: str = ""
    group_full_path: str = ""
    group_access_level: int = 0


class Project(GitLabModel):
    id: int
    name: str = ""
    name_with_namespace: str = ""
    path: str = ""
    path_with_namespace: str = ""
    description: str | None = None
    default_branch: str = ""
    web_url: str = ""
    ssh_url_to_repo: str = ""
    http_url_to_repo: str = ""
    namespace: Namespace | None = None
    created_at: str = ""
    last_activity_at: str = ""
    visibility: str = ""
    archived: bool = False
    open_issues_count: int = 0
    forks_count: int = 0
    star_count: int = 0
    only_allow_merge_if_pipeline_succeeds: bool | None = None
    only_allow_merge_if_all_discussions_are_resolved: bool | None = None
    remove_source_branch_after_merge: bool | None = None
    squash_option: str | None = None
    merge_method: str | None = None
    shared_with_groups: list[SharedWithGroup] = []


class Group(GitLabModel):
    id: int
    name: str = ""
    path: str = ""
    full_name: str = ""
    full_path: str = ""
    description: str = ""
    visibility: str = ""
    web_url: str = ""
    parent_id: int | None = None
    created_at: str = ""
    shared_with_groups: list[SharedWithGroup] = []
