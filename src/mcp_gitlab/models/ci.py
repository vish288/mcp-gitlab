"""CI/CD variable, tag, and release models."""

from __future__ import annotations

from .base import GitLabModel
from .common import User
from .repositories import Commit


class Variable(GitLabModel):
    key: str = ""
    value: str = ""
    variable_type: str = "env_var"
    protected: bool = False
    masked: bool = False
    raw: bool = False
    environment_scope: str = "*"
    description: str | None = None


class Tag(GitLabModel):
    name: str = ""
    message: str | None = None
    target: str = ""
    commit: Commit | None = None
    protected: bool = False


class ReleaseLink(GitLabModel):
    id: int
    name: str = ""
    url: str = ""
    direct_asset_url: str = ""
    link_type: str = ""


class ReleaseAssets(GitLabModel):
    count: int = 0
    links: list[ReleaseLink] = []


class Release(GitLabModel):
    tag_name: str = ""
    name: str = ""
    description: str = ""
    created_at: str = ""
    released_at: str = ""
    author: User | None = None
    commit: Commit | None = None
    assets: ReleaseAssets | None = None
