# syntax=docker/dockerfile:1

# Minimal, non-root image for the GitLab MCP server. Builds from this repo with
# uv against the committed uv.lock, so the image pins exactly what the tests ran.
# No server is deployed by this file; it is prep for the Docker MCP catalog and a
# future hosted deployment.
FROM python:3.13-slim

# uv, copied from the official distroless image — no curl/pip bootstrap step.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

# Dependencies and project from the frozen lockfile. --no-dev keeps test/lint
# tooling out of the runtime image.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# Drop privileges: the server needs no root and writes nothing outside its home.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app
ENV PATH="/app/.venv/bin:$PATH"

# Default to the locked read-only mode; override with `-e MCP_READ_ONLY=false`
# at `docker run` to allow writes.
ENV MCP_READ_ONLY=true

# stdio transport by default (CMD []). For HTTP, append flags at run time:
#   docker run --rm -e GITLAB_URL=... -e GITLAB_TOKEN=... IMAGE \
#     --transport streamable-http --host 0.0.0.0
# A non-loopback HTTP bind in token mode requires GITLAB_HTTP_BEARER_TOKEN
# (>=16 chars) or GITLAB_AUTH=oauth — see the README.
ENTRYPOINT ["mcp-gitlab"]
CMD []
