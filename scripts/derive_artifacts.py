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
SERVER_JSON = ROOT / "server.json"
LLMS_SPLIT_MARKER = "\n## Configuration"

    "MCP server for GitLab API — projects, MRs, pipelines, CI/CD variables, approvals, and more"
)


def derive_gemini_extension() -> str:
    """gemini-extension.json from server.json — the single source, as in the
    sibling servers. Settings are the registry's environment variables under
    Gemini's field names; the description is the registry description."""
    server = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
    pkg = server["packages"][0]
    identifier = pkg["identifier"]
    data = {
        "name": identifier,
        "version": server["version"],
        "description": server["description"],
        "mcpServers": {identifier: {"command": "uvx", "args": [identifier]}},
        "settings": [
            {
                "name": env["name"],
                "description": env["description"],
                "required": env["isRequired"],
                "sensitive": env["isSecret"],
            }
            for env in pkg["environmentVariables"]
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"

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
