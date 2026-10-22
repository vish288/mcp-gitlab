# syntax=docker/dockerfile:1
# Minimal non-root image for mcp-gitlab.
#
#   docker build -t mcp-gitlab .
#
# Run (stdio; the image defaults to locked read-only — pass
# -e MCP_READ_ONLY=false to allow writes). Pass the server's environment
# variables with -e; see README.md for the configuration reference:
#   docker run --rm -i -e NAME=value … mcp-gitlab
#
# Serve over HTTP (requires a bearer token on a non-loopback host):
#   docker run --rm -p 9000:9000 -e NAME=value … \
#     mcp-gitlab --transport streamable-http --host 0.0.0.0 --port 9000
FROM python:3.13-slim

# uv provides reproducible, frozen installs from uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.9.2 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# Drop privileges: run as a non-root user that owns the venv.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

# Default to the locked read-only mode; override with `-e MCP_READ_ONLY=false`
# at `docker run` to allow writes.
ENV MCP_READ_ONLY=true

ENTRYPOINT ["mcp-gitlab"]
CMD []
