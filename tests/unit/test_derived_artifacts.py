"""The committed derived artifacts must equal what derive_artifacts.py produces.

If these fail, run ``python scripts/derive_artifacts.py`` and commit the result
(or fix the source), so gemini-extension.json and llms.txt never drift from
server.json / llms-full.txt.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "derive_artifacts", ROOT / "scripts" / "derive_artifacts.py"
)
assert _spec and _spec.loader
derive_artifacts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(derive_artifacts)


def test_gemini_extension_matches_derivation():
    committed = (ROOT / "gemini-extension.json").read_text()
    assert committed == derive_artifacts.derive_gemini_extension()


def test_llms_txt_matches_derivation():
    committed = (ROOT / "llms.txt").read_text()
    assert committed == derive_artifacts.derive_llms_txt()
