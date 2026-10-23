# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.14
ARG UV_VERSION=0.12

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# --- build: resolve the locked runtime deps into /app/.venv ---------------------
FROM python:${PYTHON_VERSION}-slim-trixie AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# Dependencies first so this layer is cached until uv.lock changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# --- runtime: venv only, no build tools, non-root -------------------------------
FROM python:${PYTHON_VERSION}-slim-trixie AS runtime

LABEL org.opencontainers.image.title="twingate-mcp" \
      org.opencontainers.image.description="Read-only MCP server for the Twingate GraphQL Admin API" \
      org.opencontainers.image.licenses="MIT"

# pip is unused at runtime and its vendored deps (urllib3, msgpack, ...) carry CVEs.
RUN python -m pip uninstall --yes --quiet pip \
 && groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
USER app:app
EXPOSE 8000

ENTRYPOINT ["twingate-mcp"]
CMD ["serve", "--transport", "stdio"]
