# syntax=docker/dockerfile:1.7

############################
# Stage 1: builder — wheels only
############################
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip wheel --wheel-dir /wheels .


############################
# Stage 2: runtime
############################
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app --gid 10001 \
    && useradd --system --uid 10001 --gid 10001 --home-dir /app --shell /sbin/nologin app

WORKDIR /app
COPY --from=builder /wheels /wheels
COPY pyproject.toml README.md ./
COPY src ./src
COPY docker/entrypoint.sh /entrypoint.sh

RUN pip install --no-index --find-links=/wheels newsforge \
    && rm -rf /wheels \
    && chmod +x /entrypoint.sh \
    && chown -R app:app /app

USER app

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["api"]
