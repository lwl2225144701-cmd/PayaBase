FROM python:3.12-slim

WORKDIR /app

RUN mkdir -p /root/.config/pip && \
    echo '[global]\nindex-url = https://pypi.tuna.tsinghua.edu.cn/simple/\ntrusted-host = pypi.tuna.tsinghua.edu.cn' > /root/.config/pip/pip.conf

COPY celery-service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY core /app/core
COPY models /app/models

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["celery", "-A", "core.tasks", "worker", "--loglevel=info", "--concurrency=1"]
