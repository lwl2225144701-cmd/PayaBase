# syntax=docker/dockerfile:1.7

FROM python:3.11-slim AS python-service-base

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_DEFAULT_TIMEOUT=1200
ENV PIP_RETRIES=12
ENV PIP_PROGRESS_BAR=off

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn && \
    pip config set global.timeout 300

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir \
    fastapi \
    uvicorn \
    httpx \
    pydantic \
    redis


FROM python-service-base AS ml-service-base

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir numpy
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir torch==2.6.0
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir sentence-transformers modelscope transformers


FROM ml-service-base AS vector-runtime

COPY vector-service/main.py /app/main.py

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]


FROM ml-service-base AS rerank-runtime

COPY rerank-service/main.py /app/main.py

EXPOSE 8003

CMD ["python", "main.py"]


FROM python-service-base AS search-runtime

COPY search-service/main.py /app/main.py

EXPOSE 8004

CMD ["python", "main.py"]
