"""GitLab OAuth provider: a fastmcp OAuthProxy in front of a GitLab instance.

Modelled on fastmcp's ``providers/github.py``. The verifier uses ``httpx``
(not fastmcp's ``httpx2``) so the test suite's ``respx`` can mock it.
"""

from __future__ import annotations

import httpx
from fastmcp.server.auth import TokenVerifier
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.oauth_proxy import OAuthProxy

from .config import GitLabConfig

# GitLab scope hierarchy: a broader scope satisfies the narrower one
# (MCP 2026-07-28, "Servers MUST account for scope hierarchies").
_IMPLIED = {"api": {"read_api", "read_user"}, "read_api": {"read_user"}}


def _expand_scopes(scopes: list[str]) -> list[str]:
    out = set(scopes)
    for s in scopes:
        out |= _IMPLIED.get(s, set())
    return sorted(out)


class GitLabTokenVerifier(TokenVerifier):
    """Validate a GitLab OAuth access token with ``GET /oauth/token/info``.

    ``required_scopes`` is passed to the base class so the OAuthProxy derives
    its metadata and the request-time scope check from it, but it is NOT
    re-checked here: scope enforcement is the resource server's job
    (``RequireAuthMiddleware`` → 403 ``insufficient_scope``). Rejecting an
    under-scoped-but-valid token here would instead surface as a misleading
    401 ``invalid_token`` and make the 403 path unreachable.
    """

    def __init__(
        self,
        *,
        gitlab_url: str,
        required_scopes: list[str],
        timeout: int = 10,
        ssl_verify: bool = True,
    ) -> None:
        super().__init__(required_scopes=required_scopes)
        self._info_url = f"{gitlab_url}/oauth/token/info"
        self._timeout = timeout
        self._ssl_verify = ssl_verify

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, verify=self._ssl_verify) as http:
                resp = await http.get(self._info_url, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None  # expired, revoked, or not a token
        info = resp.json()
        scopes = _expand_scopes(list(info.get("scope") or []))
        created, ttl = info.get("created_at"), info.get("expires_in")
        owner = str(info.get("resource_owner_id", ""))
        return AccessToken(
            token=token,  # the upstream GitLab token; tools read this
            client_id=str((info.get("application") or {}).get("uid", "")),
            scopes=scopes,
            expires_at=int(created + ttl) if created and ttl else None,
            subject=owner,
            claims={"sub": owner, "scope": scopes},
        )


class GitLabProvider(OAuthProxy):
    def __init__(self, config: GitLabConfig) -> None:
        super().__init__(
            upstream_authorization_endpoint=f"{config.url}/oauth/authorize",
            upstream_token_endpoint=f"{config.url}/oauth/token",
            upstream_revocation_endpoint=f"{config.url}/oauth/revoke",
            upstream_client_id=config.oauth_client_id,
            upstream_client_secret=config.oauth_client_secret,
            token_verifier=GitLabTokenVerifier(
                gitlab_url=config.url,
                required_scopes=config.scopes,
                timeout=config.timeout,
                ssl_verify=config.ssl_verify,
            ),
            base_url=config.oauth_base_url,
            jwt_signing_key=config.oauth_jwt_key or None,
        )
