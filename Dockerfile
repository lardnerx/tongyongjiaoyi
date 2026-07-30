# ---- builder 阶段：编译依赖 ----
FROM python:3.11-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .[postgres,http]

# ---- runtime 阶段：运行时镜像 ----
FROM python:3.11-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl && rm -rf /var/lib/apt/lists/*
# 从 builder 拷贝已安装的依赖
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
# 拷贝应用代码与迁移
COPY src/ /app/src/
COPY migrations/ /app/migrations/
COPY logging.conf /app/logging.conf
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
WORKDIR /app
ENV PYTHONPATH=/app/src
EXPOSE 8000
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "umcp_core.transport.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
