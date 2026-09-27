#!/usr/bin/env python3
"""Derive the two release-tracked artifacts from their sources.

Both files stay committed on purpose: the Gemini CLI installs
``gemini-extension.json`` straight from the repo and ``llms.txt`` is fetched
from ``main``. Hand-maintaining them let their versions drift from
``server.json``; instead a release bumps only the sources and runs this script.

- ``gemini-extension.json``: ``name`` and ``version`` come from ``server.json``
  (``name`` is the last path segment of the registry name). The Gemini-specific
  presentation fields (``description``, ``mcpServers``, ``settings``) are the
  extension's own and are kept here verbatim -- ``server.json``'s description and
  environment-variable list intentionally differ from what the Gemini CLI shows.
- ``llms.txt``: the byte-exact prefix of ``llms-full.txt`` up to the first
  section that only the full document carries (``## Configuration``).

Run with no arguments from anywhere; it rewrites both files in place. Stdlib
only, so the release workflow needs no dependencies to invoke it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LLMS_SPLIT_MARKER = "\n## Configuration"

_GEMINI_DESCRIPTION = (
    "MCP server for GitLab API — projects, MRs, pipelines, CI/CD variables, approvals, and more"
)


def derive_gemini_extension() -> str:
    """Build gemini-extension.json (name + version from server.json)."""
    server = json.loads((ROOT / "server.json").read_text())
    name = server["name"].rsplit("/", 1)[-1]
    extension = {
        "name": name,
        "version": server["version"],
        "description": _GEMINI_DESCRIPTION,
        "mcpServers": {
            name: {
                "command": "uvx",
                "args": [name],
            }
        },
        "settings": [
            {
                "name": "GITLAB_URL",
                "description": "GitLab instance URL (e.g., https://gitlab.com)",
                "required": True,
                "sensitive": False,
            },
            {
                "name": "GITLAB_TOKEN",
                "description": "GitLab personal access token",
                "required": True,
                "sensitive": True,
            },
        ],
    }
    return json.dumps(extension, indent=2) + "\n"


def derive_llms_txt() -> str:
    """Return llms.txt: the prefix of llms-full.txt before ## Configuration."""
    full = (ROOT / "llms-full.txt").read_text()
    if LLMS_SPLIT_MARKER not in full:
        msg = (
            f"llms-full.txt has no {LLMS_SPLIT_MARKER!r} section; llms.txt can no "
            "longer be derived as its prefix -- update scripts/derive_artifacts.py."
        )
        raise SystemExit(msg)
    return full.split(LLMS_SPLIT_MARKER, 1)[0]


def main() -> int:
    (ROOT / "gemini-extension.json").write_text(derive_gemini_extension())
    (ROOT / "llms.txt").write_text(derive_llms_txt())
    return 0


if __name__ == "__main__":
    sys.exit(main())
