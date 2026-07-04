FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# 先设置镜像源并安装通用包
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip install --no-cache-dir \
    fastapi uvicorn httpx pydantic

# 安装torch
RUN pip install --no-cache-dir torch

# 安装ML包
RUN pip install --no-cache-dir transformers sentence-transformers numpy

# 安装modelscope
RUN pip install --no-cache-dir modelscope

COPY main.py .

EXPOSE 8003

CMD ["python", "main.py"]
