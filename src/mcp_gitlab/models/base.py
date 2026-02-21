"""Base model for GitLab API responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class GitLabModel(BaseModel):
    """Base model with common behavior for all GitLab API models."""

    model_config = {"extra": "ignore", "populate_by_name": True}

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)
