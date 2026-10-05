"""MCP server for GitLab API."""

import asyncio
import logging
import os

import click
from dotenv import load_dotenv


@click.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse", "streamable-http"]),
    default="stdio",
    help="MCP transport type (sse is deprecated; use streamable-http)",
)
@click.option("--port", default=8000, help="Port for HTTP transports")
@click.option("--host", default="127.0.0.1", help="Host for HTTP transports")
@click.option("--gitlab-url", envvar="GITLAB_URL", help="GitLab instance URL")
@click.option("--gitlab-token", envvar="GITLAB_TOKEN", help="GitLab personal access token")
@click.option("--read-only", is_flag=True, help="Disable write operations")
@click.option(
    "--auth",
    type=click.Choice(["token", "oauth"]),
    envvar="GITLAB_AUTH",
    default="token",
    help="token (PAT from env, default) or oauth (OAuth 2.1 proxy to GitLab; streamable-http only)",
)
def main(
    transport: str,
    port: int,
    host: str,
    gitlab_url: str | None,
    gitlab_token: str | None,
    read_only: bool,
    auth: str,
) -> None:
    """Run the GitLab MCP server."""
    load_dotenv()

    if gitlab_url:
        os.environ["GITLAB_URL"] = gitlab_url
    if gitlab_token:
        os.environ["GITLAB_TOKEN"] = gitlab_token
    if read_only:
        os.environ["GITLAB_READ_ONLY"] = "true"
    os.environ["GITLAB_AUTH"] = auth

    if auth == "oauth" and transport != "streamable-http":
        msg = (
            "--auth oauth requires --transport streamable-http "
            "(OAuth applies to HTTP only; stdio uses env credentials)"
        )
        raise click.UsageError(msg)

    if transport == "sse":
        click.echo(
            "Warning: --transport sse uses the HTTP+SSE transport, deprecated in MCP 2026-07-28. "
            "Use --transport streamable-http.",
            err=True,
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s | %(message)s",
    )

    from .servers import prompts, resources  # noqa: F401 — registers decorators
    from .servers.gitlab import mcp

    if auth == "oauth":
        from .config import GitLabConfig
        from .oauth import GitLabProvider

        cfg = GitLabConfig.from_env()
        cfg.validate()
        mcp.auth = GitLabProvider(cfg)
        logging.getLogger(__name__).info(
            "Auth: oauth (GitLab app %s, scopes %s)", cfg.oauth_client_id, cfg.oauth_scopes
        )

    run_kwargs: dict = {"transport": transport}
    if transport != "stdio":
        run_kwargs["host"] = host
        run_kwargs["port"] = port

    asyncio.run(mcp.run_async(show_banner=False, **run_kwargs))


if __name__ == "__main__":
    main()
