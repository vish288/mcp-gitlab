"""Approval rule models."""

from __future__ import annotations

from .base import GitLabModel
from .common import User


class ApprovalGroup(GitLabModel):
    id: int
    name: str = ""
    full_path: str = ""


class ApprovalRule(GitLabModel):
    id: int
    name: str = ""
    rule_type: str = ""
    eligible_approvers: list[User] = []
    approvals_required: int = 0
    users: list[User] = []
    groups: list[ApprovalGroup] = []
    contains_hidden_groups: bool = False
    approved_by: list[User] = []
    approved: bool = False
