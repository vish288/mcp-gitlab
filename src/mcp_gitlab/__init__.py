"""MCP server for GitLab API."""

import asyncio
import os

import click
from dotenv import load_dotenv


@click.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse", "streamable-http"]),
    default="stdio",
    help="MCP transport type",
)
@click.option("--port", default=8000, help="Port for HTTP transports")
@click.option("--host", default="127.0.0.1", help="Host for HTTP transports")
@click.option("--gitlab-url", envvar="GITLAB_URL", help="GitLab instance URL")
@click.option("--gitlab-token", envvar="GITLAB_TOKEN", help="GitLab personal access token")
@click.option("--read-only", is_flag=True, help="Disable write operations")
def main(
    transport: str,
    port: int,
    host: str,
    gitlab_url: str | None,
    gitlab_token: str | None,
    read_only: bool,
) -> None:
    """Run the GitLab MCP server."""
    load_dotenv()

    if gitlab_url:
        os.environ["GITLAB_URL"] = gitlab_url
    if gitlab_token:
        os.environ["GITLAB_TOKEN"] = gitlab_token
    if read_only:
        os.environ["GITLAB_READ_ONLY"] = "true"

    from .servers import prompts, resources  # noqa: F401 — registers decorators
    from .servers.gitlab import mcp

    run_kwargs: dict = {"transport": transport}
    if transport != "stdio":
        run_kwargs["host"] = host
        run_kwargs["port"] = port

    asyncio.run(mcp.run_async(show_banner=False, **run_kwargs))


if __name__ == "__main__":
    main()
