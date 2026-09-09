# SentinelMesh application image.
#
# Builds the Python distributions (contracts, common, api-gateway,
# ingestion-gateway, normalization-engine, stream-processor, graph-service, ml-py, ml-inference) into a virtualenv in a builder stage, then copies only that
# venv into a slim runtime. One image serves every service; the compose
# `command:` selects which `python -m ...` entrypoint runs. The runtime has no
# compiler, no build cache and runs as a non-root user.
#
# Build from the repository root:
#   docker build -f deploy/docker/Dockerfile.app -t sentinelmesh/app:dev .

# --------------------------------------------------------------------------- #
# builder
# --------------------------------------------------------------------------- #
FROM python:3.11-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# asyncpg and argon2-cffi ship wheels for this platform, but keep a compiler
# available so a source-only dependency does not break the build.
RUN apt-get update \
 && apt-get install --no-install-recommends -y build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /src

# Copy only what the installs need, so a source edit does not invalidate the
# dependency layer.
COPY packages/contracts-py/pyproject.toml packages/contracts-py/README.md packages/contracts-py/
COPY packages/common-py/pyproject.toml   packages/common-py/README.md   packages/common-py/
COPY services/api-gateway/pyproject.toml services/api-gateway/README.md services/api-gateway/
COPY services/ingestion-gateway/pyproject.toml services/ingestion-gateway/README.md services/ingestion-gateway/
COPY services/normalization-engine/pyproject.toml services/normalization-engine/README.md services/normalization-engine/
COPY services/stream-processor/pyproject.toml services/stream-processor/README.md services/stream-processor/
COPY packages/ml-py/pyproject.toml packages/ml-py/README.md packages/ml-py/
COPY services/graph-service/pyproject.toml services/graph-service/README.md services/graph-service/
COPY services/ml-inference/pyproject.toml services/ml-inference/README.md services/ml-inference/

COPY packages/contracts-py/src packages/contracts-py/src
COPY packages/common-py/src    packages/common-py/src
COPY services/api-gateway/src  services/api-gateway/src
COPY services/ingestion-gateway/src services/ingestion-gateway/src
COPY services/normalization-engine/src services/normalization-engine/src
COPY services/stream-processor/src services/stream-processor/src
COPY packages/ml-py/src packages/ml-py/src
COPY services/graph-service/src services/graph-service/src
COPY services/ml-inference/src services/ml-inference/src

RUN pip install ./packages/contracts-py ./packages/common-py ./services/api-gateway ./services/ingestion-gateway ./services/normalization-engine ./packages/ml-py ./services/stream-processor ./services/graph-service ./services/ml-inference \
 && pip install "alembic>=1.13"

# --------------------------------------------------------------------------- #
# runtime
# --------------------------------------------------------------------------- #
FROM python:3.11-slim-bookworm AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin sentinelmesh

COPY --from=builder /opt/venv /opt/venv

# Migrations are run by the dedicated `migrate` service, which needs the
# Alembic scripts at runtime.
WORKDIR /app
COPY migrations /app/migrations
COPY scripts /app/scripts

USER 10001

EXPOSE 8000

# The image has no curl; use the interpreter that is already here.
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"]

CMD ["python", "-m", "sm_api_gateway"]
