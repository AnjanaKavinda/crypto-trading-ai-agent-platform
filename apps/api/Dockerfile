FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY apps/api/README.md apps/api/README.md
COPY apps/api/src apps/api/src
RUN pip install --no-cache-dir . \
    && mkdir -p /usr/local/share/trading-platform \
    && touch /usr/local/share/trading-platform/docker-local \
    && useradd --system --uid 10001 research
COPY apps/api/alembic.ini apps/api/alembic.ini
COPY apps/api/migrations apps/api/migrations
USER research
ENTRYPOINT ["python", "-m", "trading_platform_api.docker_local"]
