"""Validate all external URLs in README.md, pyproject.toml, and server.json.

Runs as part of CI to catch broken links before merge.
Skips placeholder/example domains and only checks real HTTP(S) URLs.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent

# Files to scan for URLs
FILES_TO_CHECK = ["README.md", "pyproject.toml", "server.json"]

# Domains that are intentional placeholders — never fetch these
PLACEHOLDER_DOMAINS = {
    "example.com",
    "example.org",
    "gitlab.example.com",
    "your-company.atlassian.net",
    "your-org.atlassian.net",
    "your-domain.atlassian.net",
    "localhost",
}

# GitHub Pages SPA routes — served via client-side routing, return 404 from server
SPA_DOMAINS = {"vish288.github.io"}

# URL pattern: match http(s) URLs, stop at whitespace, quotes, backticks, or markdown closers
URL_RE = re.compile(r"https?://[^\s\)\]\"\'>`]+")


def _extract_urls() -> list[tuple[str, str]]:
    """Extract all URLs from project files. Returns (file, url) pairs."""
    results = []
    for filename in FILES_TO_CHECK:
        path = ROOT / filename
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for match in URL_RE.finditer(text):
            url = match.group(0).rstrip(".,;:`")
            results.append((filename, url))
    return results


def _is_placeholder(url: str) -> bool:
    """Check if URL uses a known placeholder domain."""
    try:
        # Extract hostname from URL
        host = url.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0]
        return host in PLACEHOLDER_DOMAINS or host.endswith(".example.com")
    except (IndexError, ValueError):
        return False


def _is_badge_image(url: str) -> bool:
    """Badge images (shields.io) can be flaky — skip them."""
    return "img.shields.io" in url


def _is_schema_url(url: str) -> bool:
    """JSON schema URLs are fetched by tools, not browsers."""
    return "static.modelcontextprotocol.io/schemas" in url


def _is_spa_route(url: str) -> bool:
    """GitHub Pages SPA routes use client-side routing — server returns 404."""
    try:
        host = url.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0]
        has_path = "/" in url.split("://", 1)[1]
        return host in SPA_DOMAINS and has_path
    except (IndexError, ValueError):
        return False


# Collect all real URLs to check
_all_urls = _extract_urls()
_checkable = [
    (f, url)
    for f, url in _all_urls
    if not _is_placeholder(url)
    and not _is_badge_image(url)
    and not _is_schema_url(url)
    and not _is_spa_route(url)
]


@pytest.fixture(scope="module")
def http_client():
    """Shared HTTP client for all link checks."""
    with httpx.Client(
        follow_redirects=True,
        timeout=15.0,
        headers={"User-Agent": "link-check/1.0"},
    ) as client:
        yield client


@pytest.mark.parametrize(
    ("source_file", "url"),
    _checkable,
    ids=[f"{f}:{url[:60]}" for f, url in _checkable],
)
def test_url_is_reachable(http_client: httpx.Client, source_file: str, url: str) -> None:
    """Every non-placeholder URL in project files must return HTTP 2xx or 3xx."""
    resp = http_client.head(url)

    # Some servers reject HEAD — fall back to GET
    if resp.status_code == 405:
        resp = http_client.get(url)

    # 401/403 are valid for API endpoints that require authentication
    assert resp.status_code < 400 or resp.status_code in {401, 403}, (
        f"{source_file}: {url} returned {resp.status_code}"
    )
