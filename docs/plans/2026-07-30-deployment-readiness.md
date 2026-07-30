# 阶段五 D：部署就绪（本地容器化一键启动）实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 通过 `docker compose up` 一键启动完整 UMCP 服务栈（PostgreSQL + app），包含应用容器化、启动时自动迁移、统一文本日志、健康检查增强。

**架构：** 1) Dockerfile 多阶段构建应用镜像；2) docker-compose.yml 新增 app 服务，depends_on postgres healthy；3) docker-entrypoint.sh 启动前运行 alembic upgrade head；4) logging.conf 统一日志格式，app.py 启动时加载；5) /health/ready 增加 DB 连通性检查；6) .env.example + pyproject.toml 入口点 + .dockerignore。

**技术栈：** Docker、docker-compose、Python 3.11、FastAPI、uvicorn、Alembic、SQLAlchemy

**规格文档：** `docs/specs/2026-07-30-deployment-readiness-design.md`

---

## 文件结构

### 新建
- `Dockerfile` — 多阶段构建应用镜像（builder 编译依赖 + runtime 运行）
- `docker-entrypoint.sh` — 启动前运行 alembic 迁移，再 exec uvicorn
- `logging.conf` — 统一文本日志配置（root/uvicorn/umcp 三个 logger）
- `.env.example` — 环境变量文档
- `.dockerignore` — 构建上下文排除

### 修改
- `migrations/alembic.ini` — `script_location` 改为 `.`（适配容器内相对路径）
- `pyproject.toml` — 新增 `[project.scripts]` 入口点
- `docker-compose.yml` — 新增 app 服务
- `src/umcp_core/transport/app.py` — 加载 logging.conf
- `src/umcp_core/transport/routers/health.py` — /health/ready 增加 DB 连通性检查
- `tests/test_app_factory.py` — 新增日志加载测试
- `tests/test_http_e2e.py` — 新增 /health/ready DB 检查测试

---

## 任务分解

### 任务 1：alembic.ini script_location 修复

**文件：**
- 修改：`migrations/alembic.ini:2`

- [ ] **步骤 1：修改 alembic.ini 的 script_location**

修改 `migrations/alembic.ini` 第 2 行，将 `script_location = migrations` 改为 `script_location = .`：

```ini
[alembic]
script_location = .
sqlalchemy.url = postgresql://umcp:umcp@localhost:5432/umcp_dev
```

**原因**：alembic.ini 位于 `migrations/` 目录内，`script_location` 相对于 ini 文件所在目录解析。改为 `.` 让 alembic 在 `migrations/` 目录内查找 `versions/` 和 `env.py`，无论从哪个 CWD 运行都能正确解析。

- [ ] **步骤 2：验证本地迁移仍能工作（若有 PG 服务）**

运行：`docker compose up -d postgres` 然后等待 healthy，再运行：
```bash
alembic -c migrations/alembic.ini upgrade head
```
预期：迁移成功（或报 "Target database is not up to date" 表示已是最新）。若迁移失败，检查 `script_location` 解析。

若无 PG 服务，跳过此步（不阻断）。

- [ ] **步骤 3：运行全量测试验证无回归**

运行：`python -m pytest -v --tb=short`
预期：所有测试通过（不引入回归）

- [ ] **步骤 4：Commit**

```bash
git add migrations/alembic.ini
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "fix(alembic): script_location 改为 .，适配容器内相对路径"
```

---

### 任务 2：logging.conf 统一日志配置

**文件：**
- 创建：`logging.conf`
- 修改：`src/umcp_core/transport/app.py`（加载日志配置）
- 测试：`tests/test_app_factory.py`

- [ ] **步骤 1：创建 logging.conf**

在项目根目录创建 `logging.conf`：

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

- [ ] **步骤 2：编写失败的测试**

先 Read `tests/test_app_factory.py` 检查现有结构与 imports。在文件末尾追加：

```python
class TestLoggingSetup:
    """验证 _setup_logging 加载 logging.conf。"""

    def test_setup_logging_loads_config_when_exists(self):
        """logging.conf 存在时，_setup_logging 应配置 umcp_core logger。"""
        import logging
        from umcp_core.transport.app import _setup_logging

        _setup_logging()
        logger = logging.getLogger("umcp_core")
        assert logger.level == logging.INFO

    def test_setup_logging_no_raise_when_config_absent(self, tmp_path, monkeypatch):
        """logging.conf 不存在时，_setup_logging 不应抛异常。"""
        from umcp_core.transport import app as app_module

        # 模拟 logging.conf 不存在的路径
        monkeypatch.setattr(app_module, "_LOG_CONF_PATH", tmp_path / "nonexistent.conf")
        app_module._setup_logging()  # 不抛异常即通过
```

- [ ] **步骤 3：运行测试验证失败**

运行：`python -m pytest tests/test_app_factory.py::TestLoggingSetup -v`
预期：FAIL，`ImportError: cannot import name '_setup_logging' from 'umcp_core.transport.app'`

- [ ] **步骤 4：修改 app.py 添加 _setup_logging**

先 Read `src/umcp_core/transport/app.py` 确认现有 import 和 create_app 结构。

在文件顶部 import 区域添加（若未有）：

```python
import logging.config
from pathlib import Path
```

在模块级（create_app 函数之前）添加常量和函数：

```python
_LOG_CONF_PATH = Path(__file__).resolve().parent.parent.parent.parent / "logging.conf"


def _setup_logging() -> None:
    """加载统一日志配置（若 logging.conf 存在）。"""
    if _LOG_CONF_PATH.exists():
        logging.config.fileConfig(_LOG_CONF_PATH, disable_existing_loggers=False)
```

在 `create_app` 函数体开头（现有逻辑之前）调用：

```python
def create_app(server=None, config=None):
    _setup_logging()
    # ... 现有逻辑保持不变
```

- [ ] **步骤 5：运行测试验证通过**

运行：`python -m pytest tests/test_app_factory.py::TestLoggingSetup -v`
预期：PASS（2 个测试全过）

- [ ] **步骤 6：运行 app_factory 全量回归**

运行：`python -m pytest tests/test_app_factory.py -v`
预期：PASS（含原有测试 + 新增 2 个）

- [ ] **步骤 7：Commit**

```bash
git add logging.conf src/umcp_core/transport/app.py tests/test_app_factory.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(logging): 统一文本日志配置，app 启动时加载 logging.conf"
```

---

### 任务 3：health.py /health/ready 增强 DB 连通性检查

**文件：**
- 修改：`src/umcp_core/transport/routers/health.py:20-27`
- 测试：`tests/test_http_e2e.py`

- [ ] **步骤 1：编写失败的测试**

先 Read `tests/test_http_e2e.py` 检查现有结构与 helper（_make_client、_login 等）。在文件末尾追加：

```python
class TestHealthReadyEnhanced:
    """/health/ready 应包含 DB 连通性检查。"""

    def test_ready_in_memory_mode(self):
        """内存仓储模式下，db_connected 应为 'in-memory'，ready 为 True。"""
        client = _make_client()
        token = _login(client)
        resp = client.get(
            "/api/v1/health/ready",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["ready"] is True
        assert data["components"]["db_connected"] == "in-memory"
        assert data["components"]["server_running"] is True
        assert data["components"]["task_repo"] is True

    def test_ready_pg_mode_db_failure(self, monkeypatch):
        """PG 模式下 DB 查询失败时，db_connected 应为 False，ready 为 False。"""
        from umcp_core.transport.app import create_app
        from umcp_core.transport.config import TransportConfig
        from umcp_core.server import UMCPServer
        from fastapi.testclient import TestClient

        # 构造一个带 _postgres_bundle 属性的 server（模拟 PG 模式）
        server = UMCPServer()
        server.use_in_memory_repositories()
        server.start()
        # 模拟 PG 模式标记
        object.__setattr__(server, "_postgres_bundle", object())
        # 让 task_repo.list_all 抛异常模拟 DB 不通
        original_list_all = server.task_repo.list_all
        def _raise():
            raise RuntimeError("DB connection lost")
        monkeypatch.setattr(server.task_repo, "list_all", _raise)

        config = TransportConfig(jwt_secret="test-secret")
        app = create_app(server, config)
        client = TestClient(app)
        token = _login(client)
        resp = client.get(
            "/api/v1/health/ready",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["ready"] is False
        assert data["components"]["db_connected"] is False
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_http_e2e.py::TestHealthReadyEnhanced -v`
预期：FAIL，`KeyError: 'db_connected'`（现有 /health/ready 未返回此字段）

- [ ] **步骤 3：修改 health.py**

先 Read `src/umcp_core/transport/routers/health.py` 确认现状。修改 `ready` 函数：

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

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_http_e2e.py::TestHealthReadyEnhanced -v`
预期：PASS（2 个测试全过）

- [ ] **步骤 5：运行 HTTP E2E 全量回归**

运行：`python -m pytest tests/test_http_e2e.py -v`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/transport/routers/health.py tests/test_http_e2e.py
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(health): /health/ready 增加 DB 连通性检查"
```

---

### 任务 4：pyproject.toml 入口点

**文件：**
- 修改：`pyproject.toml`

- [ ] **步骤 1：修改 pyproject.toml**

先 Read `pyproject.toml` 确认现状。在 `[project]` 段之后（`classifiers` 数组之后、`[project.optional-dependencies]` 之前）新增：

```toml
[project.scripts]
umcp-server = "umcp_core.transport.__main__:main"
```

完整的插入位置示例：

```toml
[project]
name = "umcp-core"
version = "2.0.0"
# ... 现有字段
classifiers = [
    # ... 现有 classifiers
]

[project.scripts]
umcp-server = "umcp_core.transport.__main__:main"

[project.optional-dependencies]
# ... 现有内容
```

- [ ] **步骤 2：验证入口点可安装**

运行：`pip install -e .` 然后 `umcp-server --help`（或直接验证 console_script 生成）
预期：`umcp-server` 命令可用（或至少 pip install 成功无报错）

- [ ] **步骤 3：运行全量测试验证无回归**

运行：`python -m pytest -v --tb=short`
预期：所有测试通过

- [ ] **步骤 4：Commit**

```bash
git add pyproject.toml
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(packaging): 添加 umcp-server console_script 入口点"
```

---

### 任务 5：.env.example 和 .dockerignore

**文件：**
- 创建：`.env.example`
- 创建：`.dockerignore`

- [ ] **步骤 1：创建 .env.example**

在项目根目录创建 `.env.example`：

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

- [ ] **步骤 2：创建 .dockerignore**

在项目根目录创建 `.dockerignore`：

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

- [ ] **步骤 3：验证 .gitignore 已忽略 .env**

运行：`git check-ignore .env`（若 .env 文件不存在则先 `touch .env`）
预期：输出 `.env`（表示已被忽略，不会被提交）

若未被忽略，在 `.gitignore` 中追加 `.env`。

- [ ] **步骤 4：Commit**

```bash
git add .env.example .dockerignore
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(deploy): 添加 .env.example 和 .dockerignore"
```

---

### 任务 6：Dockerfile 和 docker-entrypoint.sh

**文件：**
- 创建：`Dockerfile`
- 创建：`docker-entrypoint.sh`

- [ ] **步骤 1：创建 docker-entrypoint.sh**

在项目根目录创建 `docker-entrypoint.sh`：

```bash
#!/bin/sh
set -e

echo "Running database migrations..."
cd /app
alembic -c migrations/alembic.ini upgrade head

echo "Starting UMCP server..."
exec "$@"
```

- [ ] **步骤 2：创建 Dockerfile**

在项目根目录创建 `Dockerfile`：

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

- [ ] **步骤 3：设置 docker-entrypoint.sh 可执行权限（git 中）**

运行：
```bash
git update-index --chmod=+x docker-entrypoint.sh
```

- [ ] **步骤 4：验证 Dockerfile 语法（若有 Docker 环境）**

运行：`docker build -t umcp-core:test .`
预期：构建成功（builder 阶段安装依赖，runtime 阶段拷贝）

若无 Docker 环境，跳过此步（不阻断，实际构建在任务 8 验证）。

- [ ] **步骤 5：Commit**

```bash
git add Dockerfile docker-entrypoint.sh
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(docker): 多阶段构建 Dockerfile 和 entrypoint 脚本"
```

---

### 任务 7：docker-compose.yml 扩展

**文件：**
- 修改：`docker-compose.yml`

- [ ] **步骤 1：修改 docker-compose.yml**

先 Read `docker-compose.yml` 确认现有 postgres 服务配置。替换为完整内容（保留 postgres，新增 app）：

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

- [ ] **步骤 2：验证 docker-compose 配置语法（若有 Docker 环境）**

运行：`docker compose config`
预期：输出完整配置无报错

若无 Docker 环境，跳过此步。

- [ ] **步骤 3：Commit**

```bash
git add docker-compose.yml
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(docker): docker-compose 新增 app 服务，一键启动全栈"
```

---

### 任务 8：全量回归与验证

**文件：** 无（仅运行测试和验证）

- [ ] **步骤 1：运行全量测试套件**

运行：`python -m pytest -v --tb=short`
预期：所有测试通过（in-memory 模式下），PG 测试在无 PG 服务时 SKIP

- [ ] **步骤 2：若有 Docker 环境，一键启动验证**

运行：
```bash
docker compose up -d --build
# 等待 app healthy
timeout 60 sh -c 'until docker inspect --format="{{.State.Health.Status}}" umcp_app 2>/dev/null | grep -q healthy; do sleep 2; done'
# 验证健康检查
curl -s http://localhost:8000/health | head -100
curl -s http://localhost:8000/health/ready | head -100
# 清理
docker compose down
```
预期：
- app 容器 healthy
- `/health` 返回 `{"code":0,"data":{"status":"ok"},...}`
- `/health/ready` 返回 `{"code":0,"data":{"ready":true,"components":{"server_running":true,"task_repo":true,"db_connected":true}},...}`

若无 Docker 环境，跳过此步（不阻断）。

- [ ] **步骤 3：检查无新增警告**

运行：`python -m pytest -W error::DeprecationWarning -v 2>&1 | head -50`
预期：无新增 DeprecationWarning（已有的 Starlette/httpx 弃用和 JWT 短密钥警告属非目标，可忽略）

- [ ] **步骤 4：使用 finishing-a-development-branch 技能收尾**

调用 `finishing-a-development-branch` 技能，验证测试通过后展示收尾选项。

---

## 自检

### 1. 规格覆盖度

| 规格章节 | 对应任务 |
|---------|---------|
| 2.1 Dockerfile（多阶段构建） | 任务 6 |
| 2.1.3 docker-entrypoint.sh | 任务 6 |
| 2.1.4 alembic.ini 调整 | 任务 1 |
| 2.2 docker-compose.yml 扩展 | 任务 7 |
| 2.3 统一文本日志（logging.conf + app.py） | 任务 2 |
| 2.4 健康检查增强（/health/ready DB 检查） | 任务 3 |
| 2.5 .env.example | 任务 5 |
| 2.6 pyproject.toml 入口点 | 任务 4 |
| 2.7 .dockerignore | 任务 5 |
| 3.3 回归测试 | 任务 8 |

所有规格章节均有对应任务。无遗漏。

### 2. 占位符扫描

- 无 "待定"、"TODO"、"后续实现"
- 无 "添加适当的错误处理"（所有错误处理均显式写出）
- 无 "类似任务 N"（每个任务的代码均完整给出）
- 所有步骤的代码块均包含实际代码

### 3. 类型一致性

- `_setup_logging() -> None`：任务 2 的 app.py 定义与测试调用一致
- `_LOG_CONF_PATH` 路径计算：`Path(__file__).resolve().parent.parent.parent.parent`（4 级，app.py → transport → umcp_core → src → 项目根）与规格一致
- `script_location = .`：任务 1 与规格 2.1.4 一致
- `umcp-server = "umcp_core.transport.__main__:main"`：任务 4 与规格 2.6 一致
- docker-compose 的 `UMCP_DB_DSN` 指向 `postgres` 主机名：任务 7 与规格 2.2 一致

类型与命名均一致。
