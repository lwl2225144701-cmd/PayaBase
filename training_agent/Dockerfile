# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS python-base

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV UV_LINK_MODE=copy
# 容器时区设为北京时间，避免 celery/api 日志 UTC 与本地时间差 8 小时造成误读
ENV TZ=Asia/Shanghai

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir uv


FROM python-base AS deps

COPY pyproject.toml uv.lock /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python-base AS runtime-base

COPY --from=deps /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONPATH=/app


FROM runtime-base AS api-runtime

COPY api /app/api
COPY core /app/core
COPY models /app/models

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM runtime-base AS celery-runtime

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends fonts-wqy-zenhei fontconfig tzdata && \
    ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    fc-cache -f && \
    rm -rf /var/lib/apt/lists/*

COPY core /app/core
COPY models /app/models

CMD ["celery", "-A", "core.tasks", "worker", "--loglevel=info", "--concurrency=1"]
