"""开发启动脚本，自动加载 .env 文件。"""
import os
from pathlib import Path

# 加载 .env
from dotenv import load_dotenv
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"[run_dev] 已加载 .env: {env_path}", flush=True)

# 确保插件目录在 sys.path 中
import sys
plugins_dir = Path(__file__).parent / "plugins"
if plugins_dir.is_dir() and str(plugins_dir) not in sys.path:
    sys.path.insert(0, str(plugins_dir))
    print(f"[run_dev] 已添加插件目录: {plugins_dir}", flush=True)

# 运行 transport main
from umcp_core.transport.__main__ import main
main()