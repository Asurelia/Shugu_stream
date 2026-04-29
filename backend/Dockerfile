# ── Builder ────────────────────────────────────────────────────────────────
# Uses python:3.13-slim — pyproject requires >=3.12, local venv is 3.13.
# libpq-dev needed by psycopg2/asyncpg compile step (C extension).
FROM python:3.13-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy entire backend first so hatchling can resolve the shugu/ package during
# install (pyproject.toml + source must be co-located for hatchling's editable
# build to work).  We install non-editable so the runtime stage gets pure
# installed packages without .pth files pointing at builder paths.
COPY backend/ /app/

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/install .

# ── Runtime ────────────────────────────────────────────────────────────────
# libpq5 = shared library needed by asyncpg at runtime (no headers needed).
# curl is needed by the HEALTHCHECK.
FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder, then application source.
COPY --from=builder /install /usr/local
COPY --from=builder /app /app

# Personalities are loaded from SHUGU_PERSONALITY_DIR at runtime — default
# path inside the container is /app/shugu/personalities (relative to WORKDIR).
ENV SHUGU_PERSONALITY_DIR=/app/shugu/personalities

# SHUGU_ENV=dev disables the ip_hash_salt production guard (pydantic-settings
# validator requires a non-empty salt only in production).
ENV SHUGU_ENV=dev

# Drop root: create a non-privileged user and own the working directory.
RUN groupadd --gid 1001 shugu && \
    useradd --uid 1001 --gid shugu --no-create-home shugu && \
    chown -R shugu:shugu /app
USER shugu

EXPOSE 8701

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8701/health || exit 1

CMD ["uvicorn", "shugu.app:app", "--host", "0.0.0.0", "--port", "8701"]
