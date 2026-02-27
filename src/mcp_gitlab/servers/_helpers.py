"""Shared helper functions for server modules."""

from __future__ import annotations

import functools
import re
from pathlib import Path
from urllib.parse import unquote


@functools.cache
def _load_file(base_dir: str, filename: str) -> str:
    """Load a file from the given directory with path traversal protection.

    Results are cached — static files do not change at runtime.
    """
    if "/" in filename or "\\" in filename or ".." in filename:
        msg = f"Invalid filename: {filename}"
        raise ValueError(msg)
    base = Path(base_dir)
    path = base / filename
    if not path.resolve().is_relative_to(base.resolve()):
        msg = f"Invalid filename: {filename}"
        raise ValueError(msg)
    return path.read_text(encoding="utf-8")


# ════════════════════════════════════════════════════════════════════
# GitLab URL parsing
# ════════════════════════════════════════════════════════════════════

# Matches:  <host>/<namespace/project>/-/merge_requests/<iid>
_MR_RE = re.compile(r"https?://[^/]+/(.+?)/-/merge_requests/(\d+)")
# Matches:  <host>/<namespace/project>/-/pipelines/<id>
_PIPELINE_RE = re.compile(r"https?://[^/]+/(.+?)/-/pipelines/(\d+)")
# Matches:  <host>/<namespace/project> (no /-/ suffix)
_PROJECT_RE = re.compile(r"https?://[^/]+/(.+?)(?:/-/.*)?$")


def _parse_gitlab_mr_url(value: str) -> tuple[str, str]:
    """Extract (project_path, mr_iid) from a GitLab MR URL.

    If *value* is not a URL, returns it unchanged as (value, "").
    """
    m = _MR_RE.match(value)
    if m:
        return unquote(m.group(1)), m.group(2)
    return value, ""


def _parse_gitlab_pipeline_url(value: str) -> tuple[str, str]:
    """Extract (project_path, pipeline_id) from a GitLab pipeline URL.

    If *value* is not a URL, returns it unchanged as (value, "").
    """
    m = _PIPELINE_RE.match(value)
    if m:
        return unquote(m.group(1)), m.group(2)
    return value, ""


def _parse_gitlab_project_url(value: str) -> str:
    """Extract project_path from a GitLab project URL.

    If *value* is not a URL, returns it unchanged.
    """
    if not value.startswith(("http://", "https://")):
        return value
    m = _PROJECT_RE.match(value)
    if m:
        return unquote(m.group(1))
    return value
