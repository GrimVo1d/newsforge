# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/src
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app


# Dependencies only: the project itself runs from /app/src via PYTHONPATH.
FROM base AS builder
RUN python -m venv /opt/venv && pip install --upgrade pip
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install . && pip uninstall -y newsforge


# Tooling image for tests, linters and type checks; the repository is bind-mounted at /app.
FROM builder AS dev
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install ".[dev]" && pip uninstall -y newsforge
WORKDIR /app


FROM base AS runtime
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY manage.py ./
COPY src ./src
COPY --chmod=0755 docker/entrypoint.sh /entrypoint.sh
USER app
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["api"]
