# Build context: the REPOSITORY ROOT (contracts/ is needed).  See docker-compose.yml.
# Base images are pinned by tag; pin by digest at release time (digests cannot be resolved offline).
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /src
# Runtime dependencies are pinned in a lockfile (no pytest/mypy/ruff in the image).
COPY apps/api/requirements.runtime.lock apps/api/requirements.runtime.lock
RUN pip install -r apps/api/requirements.runtime.lock
COPY contracts/python contracts/python
COPY packages/engine packages/engine
COPY packages/dataops packages/dataops
COPY apps/api apps/api
# The engine needs only contracts + pydantic (already in the lock); dataops needs polars (also in the lock).
# Without these two the API cannot start with GRIDORA_ENGINE=real / GRIDORA_DATAOPS=real.
RUN pip install --no-deps ./contracts/python ./packages/engine ./packages/dataops ./apps/api

FROM python:3.12-slim
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin gridora \
    && mkdir /data /app && chown 10001:10001 /data
COPY --from=build /opt/venv /opt/venv
COPY apps/api/alembic.ini /app/alembic.ini
COPY apps/api/migrations /app/migrations
COPY deploy/api/entrypoint.sh /app/entrypoint.sh
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 GRIDORA_DATA_ROOT=/data
USER 10001
WORKDIR /app
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
