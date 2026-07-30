# 阶段五 D：部署就绪（本地容器化一键启动）设计规格

> **目标：** 通过 `docker compose up` 一键启动完整 UMCP 服务栈（PostgreSQL + app），包含应用容器化、启动时自动迁移、统一文本日志、健康检查增强与环境变量文档。

---

## 1. 背景与范围

### 1.1 现状

- `docker-compose.yml` 仅含 postgres 服务，无应用容器
- 无 Dockerfile、无 CI 配置
- `transport/__main__.py` 提供 `python -m umcp_core.transport` 启动入口
- `transport/config.py` 已支持环境变量加载（UMCP_JWT_SECRET/DB_DSN/HOST/PORT/LOG_LEVEL 等）
- `transport/routers/health.py` 有 /health（存活）和 /health/ready（就绪），但就绪检查未验证 DB 连通性
- `pyproject.toml` 无 [project.scripts] 入口点
- 日志为 uvicorn 默认 + app.py 散用的 `logger.info`，无统一格式

### 1.2 范围（本期包含）

1. **Dockerfile**：多阶段构建应用镜像
2. **docker-compose.yml 扩展**：新增 app 服务，依赖 postgres healthy
3. **启动时自动迁移**：app 容器 entrypoint 先运行 `alembic upgrade head` 再启动 uvicorn
4. **统一文本日志**：logging.conf 配置统一格式，app 启动时加载
5. **健康检查增强**：/health/ready 增加 DB 连通性验证
6. **环境变量文档**：.env.example
7. **入口点**：pyproject.toml 添加 [project.scripts]
8. **.dockerignore**：优化构建上下文

### 1.3 范围（本期不包含）

- CI/CD 流水线（GitHub Actions / GitLab CI）
- 结构化 JSON 日志（保留为后续扩展）
- 远程仓库推送
- 性能监控 / Prometheus 指标
- TLS / HTTPS 终止
- 水平扩展 / 负载均衡

---

## 2. 功能设计

### 2.1 功能 1：Dockerfile（多阶段构建）

#### 2.1.1 设计

采用 builder + runtime 两阶段构建：

- **builder 阶段**：基于 `python:3.11-slim`，安装 gcc + libpq-dev 编译依赖，`pip install .[postgres,http]` 安装完整运行时依赖
- **runtime 阶段**：基于 `python:3.11-slim`，仅安装 libpq5 + curl（运行时 + 健康检查），从 builder 拷贝 site-packages 和 bin，拷贝源码和迁移

#### 2.1.2 文件：`Dockerfile`

```dockerfile
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
```

#### 2.1.3 文件：`docker-entrypoint.sh`

启动前先运行数据库迁移，迁移失败则不启动服务：

```bash
#!/bin/sh
set -e

echo "Running database migrations..."
cd /app
alembic -c migrations/alembic.ini upgrade head

echo "Starting UMCP server..."
exec "$@"
```

**关键决策：**
- `set -e`：迁移失败立即退出（不启动服务），让 docker restart 策略重试
- `cd /app`：确保 `script_location = migrations`（alembic.ini 中的相对路径）能正确解析到 `/app/migrations/`
- `exec "$@"`：用 uvicorn 替换 shell 进程，接收 SIGTERM 信号

#### 2.1.4 alembic.ini 调整

当前 `migrations/alembic.ini` 的 `script_location = migrations` 是相对路径。当从 `/app` 运行 `alembic -c migrations/alembic.ini upgrade head` 时，alembic 会相对于 ini 文件所在目录（`/app/migrations/`）解析 `script_location`，导致查找 `/app/migrations/migrations/`（不存在）。

**修复**：将 `script_location` 改为 `%(here)s/migrations` 不可行（因为 ini 本身就在 migrations/ 内）。正确修复为：

```ini
[alembic]
script_location = .
```

`%(here)s` 是 alembic.ini 所在目录（即 `/app/migrations/`），`script_location = .` 让 alembic 在 ini 所在目录查找 `versions/` 子目录和 `env.py`。这样无论从哪个 CWD 运行都能正确解析。

### 2.2 功能 2：docker-compose.yml 扩展

#### 2.2.1 文件：`docker-compose.yml`

在现有 postgres 服务基础上新增 app 服务：

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: umcp_postgres
    environment:
      POSTGRES_USER: umcp
      POSTGRES_PASSWORD: umcp
      POSTGRES_DB: umcp_dev
    ports:
      - "5432:5432"
    volumes:
      - umcp_pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U umcp"]
      interval: 5s
      timeout: 3s
      retries: 5

  app:
    build: .
    container_name: umcp_app
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      UMCP_JWT_SECRET: ${UMCP_JWT_SECRET:-dev-secret-change-me-32bytes}
      UMCP_DB_DSN: postgresql+psycopg://umcp:umcp@postgres:5432/umcp_dev
      UMCP_HOST: 0.0.0.0
      UMCP_PORT: 8000
      UMCP_LOG_LEVEL: INFO
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    restart: unless-stopped

volumes:
  umcp_pg_data:
```

**关键决策：**
- `depends_on.postgres.condition: service_healthy`：等 PG healthy 后再启动 app
- `UMCP_DB_DSN` 指向 `postgres` 主机名（docker 网络 DNS）
- `start_period: 30s`：迁移 + uvicorn 启动需要时间，避免健康检查误判
- `restart: unless-stopped`：崩溃自动重启，但手动停止不重启
- `UMCP_JWT_SECRET` 用 `${VAR:-default}` 允许 .env 覆盖

### 2.3 功能 3：统一文本日志

#### 2.3.1 文件：`logging.conf`

```ini
[loggers]
keys=root,uvicorn,umcp

[handlers]
keys=console

[formatters]
keys=standard

[logger_root]
level=WARNING
handlers=console

[logger_uvicorn]
level=INFO
handlers=console
qualname=uvicorn
propagate=0

[logger_umcp]
level=INFO
handlers=console
qualname=umcp_core
propagate=0

[handler_console]
class=StreamHandler
level=INFO
formatter=standard
args=(sys.stdout,)

[formatter_standard]
format=%(asctime)s [%(levelname)s] %(name)s: %(message)s
datefmt=%Y-%m-%d %H:%M:%S
```

#### 2.3.2 文件：`src/umcp_core/transport/app.py` 改动

在 `create_app` 函数开头加载日志配置（仅当文件存在时加载，避免测试环境失败）：

```python
import logging.config
from pathlib import Path

# 模块级常量（app.py 在 src/umcp_core/transport/app.py，项目根需上溯 4 级）
_LOG_CONF_PATH = Path(__file__).resolve().parent.parent.parent.parent / "logging.conf"


def _setup_logging() -> None:
    """加载统一日志配置（若 logging.conf 存在）。"""
    if _LOG_CONF_PATH.exists():
        logging.config.fileConfig(_LOG_CONF_PATH, disable_existing_loggers=False)


def create_app(server=None, config=None):
    _setup_logging()
    # ... 现有逻辑保持不变
```

**输出样例：**
```
2026-07-30 14:23:01 [INFO] umcp_core.transport.app: UMCP HTTP 服务已启动
2026-07-30 14:23:05 [INFO] uvicorn.access: POST /api/v1/auth/login 200 12.3ms
```

### 2.4 功能 4：健康检查增强

#### 2.4.1 文件：`src/umcp_core/transport/routers/health.py` 改动

`/health/ready` 增加 DB 连通性检查：

```python
@router.get("/health/ready", response_model=Envelope)
async def ready(server: UMCPServer = Depends(get_server)) -> Envelope:
    """就绪检查：检查 server + 仓储 + DB 连通性。"""
    ready_status = {
        "server_running": server.is_running,
        "task_repo": server.task_repo is not None,
    }
    # DB 连通性检查
    if hasattr(server, "_postgres_bundle"):
        try:
            server.task_repo.list_all()
            ready_status["db_connected"] = True
        except Exception:
            ready_status["db_connected"] = False
    else:
        ready_status["db_connected"] = "in-memory"
    all_ready = all(
        v for v in ready_status.values() if isinstance(v, bool)
    )
    return ok(data={"ready": all_ready, "components": ready_status})
```

**关键决策：**
- 复用任务9-7 实现的 `list_all()` 做轻量查询验证连通性
- 内存模式返回 `"in-memory"` 字符串，不计入 all_ready 判断
- `all(v for v in values if isinstance(v, bool))`：只对 bool 字段做 AND，字符串字段跳过

### 2.5 功能 5：.env.example

#### 2.5.1 文件：`.env.example`

```bash
# UMCP 服务环境变量示例
# 复制为 .env 并按需修改

# 必填：JWT 签名密钥（生产环境至少 32 字节）
UMCP_JWT_SECRET=dev-secret-change-me-32bytes

# 可选：数据库 DSN（不填则用内存仓储）
# docker compose 内使用 postgres 主机名
UMCP_DB_DSN=postgresql+psycopg://umcp:umcp@localhost:5432/umcp_dev

# 可选：服务监听
UMCP_HOST=0.0.0.0
UMCP_PORT=8000

# 可选：日志级别
UMCP_LOG_LEVEL=INFO

# 可选：CORS 允许来源（逗号分隔）
UMCP_CORS_ORIGINS=*

# 可选：JWT TTL（秒）
UMCP_JWT_ACCESS_TTL=3600
UMCP_JWT_REFRESH_TTL=604800
```

### 2.6 功能 6：pyproject.toml 入口点

#### 2.6.1 修改 `pyproject.toml`

在 `[project]` 段后新增：

```toml
[project.scripts]
umcp-server = "umcp_core.transport.__main__:main"
```

安装后可直接 `umcp-server` 启动（等价于 `python -m umcp_core.transport`）。

### 2.7 功能 7：.dockerignore

#### 2.7.1 文件：`.dockerignore`

```
.git
.github
.venv
venv
__pycache__
*.pyc
.pytest_cache
tests
plugins/*/tests
docs
*.md
.env
.mypy_cache
.ruff_cache
```

**目的**：减小构建上下文，加速构建，避免测试/文档进入生产镜像。

---

## 3. 测试策略

### 3.1 单元测试

- **health.py 增强**：新增 `/health/ready` DB 连通性检查的测试
  - 内存模式：返回 `"in-memory"`，ready=True
  - PG 模式（mock）：list_all 成功返回 True，抛异常返回 False
- **app.py 日志加载**：验证 `_setup_logging` 在 logging.conf 存在时加载，不存在时不抛异常

### 3.2 集成测试（手动）

- `docker compose build`：镜像构建成功
- `docker compose up`：postgres + app 启动，迁移自动运行
- `curl http://localhost:8000/health`：返回 `{"code":0,"data":{"status":"ok"}}`
- `curl http://localhost:8000/health/ready`：返回 ready=true，db_connected=true
- `docker compose down`：清理

### 3.3 回归测试

- 全量 `pytest` 通过（不引入回归）
- 现有 /health 和 /health/ready 测试仍通过

---

## 4. 影响文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `Dockerfile` | 新建 | 多阶段构建应用镜像 |
| `docker-entrypoint.sh` | 新建 | 迁移 + 启动脚本 |
| `logging.conf` | 新建 | 统一文本日志配置 |
| `.env.example` | 新建 | 环境变量文档 |
| `.dockerignore` | 新建 | 构建上下文排除 |
| `docker-compose.yml` | 修改 | 新增 app 服务 |
| `migrations/alembic.ini` | 修改 | `script_location = .` |
| `pyproject.toml` | 修改 | 新增 [project.scripts] |
| `src/umcp_core/transport/app.py` | 修改 | 加载 logging.conf |
| `src/umcp_core/transport/routers/health.py` | 修改 | /health/ready 增强 |
| `tests/test_app_factory.py` | 修改 | 新增日志加载测试 |
| `tests/test_http_e2e.py` | 修改 | 新增 /health/ready DB 检查测试 |

---

## 5. 风险与约束

1. **alembic.ini script_location**：现有 `script_location = migrations` 在容器内会解析失败，需改为 `script_location = .`
2. **镜像大小**：runtime 阶段约 200-300MB（python:3.11-slim + libpq5 + 依赖），可接受
3. **迁移幂等性**：`alembic upgrade head` 幂等，重复运行无副作用
4. **JWT 密钥默认值**：`.env.example` 和 docker-compose 提供开发默认值，生产必须覆盖
5. **健康检查 start_period**：30s 应足够迁移 + 启动；若迁移大可能需要调大
