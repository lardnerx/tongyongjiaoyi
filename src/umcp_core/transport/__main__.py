"""UMCP HTTP 服务入口。

用法：
    python -m umcp_core.transport

环境变量：
    UMCP_JWT_SECRET（必填）
    UMCP_DB_DSN（可选，不填用内存仓储）
    UMCP_HOST（默认 0.0.0.0）
    UMCP_PORT（默认 8000）
    UMCP_PLUGINS（可选，逗号分隔的插件名，如 escort_driving）
    UMCP_PLUGINS_DIR（可选，插件目录路径，默认自动发现项目根目录下的 plugins/）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from umcp_core.server import UMCPServer
from umcp_core.transport.app import create_app
from umcp_core.transport.config import TransportConfig


def _ensure_plugins_path() -> None:
    """将插件目录加入 sys.path，使 load_plugin(module_name) 可直接导入。

    优先级：
    1. UMCP_PLUGINS_DIR 环境变量指定的目录
    2. 自动发现：从 src/umcp_core/transport/__main__.py 向上回溯到项目根目录，拼接 plugins/
    3. 当前工作目录下的 plugins/
    """
    plugins_dir_env = os.environ.get("UMCP_PLUGINS_DIR", "").strip()
    candidates: list[Path] = []
    if plugins_dir_env:
        candidates.append(Path(plugins_dir_env))
    # __file__ = <root>/src/umcp_core/transport/__main__.py，向上4层到 <root>
    root = Path(__file__).resolve().parents[3]
    candidates.append(root / "plugins")
    candidates.append(Path.cwd() / "plugins")
    for cand in candidates:
        if cand.is_dir() and str(cand) not in sys.path:
            sys.path.insert(0, str(cand))
            return


def main() -> None:
    _ensure_plugins_path()
    # 加载 .env 文件（如果存在）
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    config = TransportConfig.from_env()
    server = UMCPServer()
    if config.db_dsn:
        server.use_postgres_repositories(
            config.db_dsn,
            pool_size=config.db_pool_size,
            max_overflow=config.db_max_overflow,
            pool_recycle=config.db_pool_recycle,
            pool_timeout=config.db_pool_timeout,
        )
    else:
        server.use_in_memory_repositories()

    # 加载插件（按 UMCP_PLUGINS 逗号分隔顺序）
    plugins_env = os.environ.get("UMCP_PLUGINS", "").strip()
    if plugins_env:
        for name in [p.strip() for p in plugins_env.split(",") if p.strip()]:
            try:
                server.load_plugin(name)
                print(f"[UMCP] 已加载插件: {name}", file=sys.stderr)
            except Exception as e:
                print(f"[UMCP] 加载插件 {name} 失败: {e}", file=sys.stderr)

    # 传入支付网关配置 + 短信通知配置（供插件 register_plugin 读取）
    payment_gw_config: dict[str, str] = {}
    if config.has_wechat_config:
        payment_gw_config.update(
            app_id=config.wechat_app_id,
            mch_id=config.wechat_mch_id,
            api_v3_key=config.wechat_api_v3_key,
            mch_serial_no=config.wechat_mch_serial_no,
            private_key_path=config.wechat_private_key_path,
            notify_url=config.wechat_notify_url,
        )
        print("[UMCP] 支付网关: 微信支付 V3 (Native)", file=sys.stderr)
    else:
        print("[UMCP] 支付网关: Mock（开发模式）", file=sys.stderr)

    # 短信通知配置（互亿无线优先，阿里云兜底）
    payment_gw_config.update(
        # 互亿无线
        sms_api_id=config.sms_api_id,
        sms_api_key=config.sms_api_key,
        sms_sign=config.sms_sign,
        # 阿里云（备选）
        sms_access_key_id=config.sms_access_key_id,
        sms_access_key_secret=config.sms_access_key_secret,
        sms_sign_name=config.sms_sign_name,
        sms_template_code=config.sms_template_code,
    )
    server.payment_gateway_config = payment_gw_config

    # 短信配置校验
    if config.sms_api_id:
        # 互亿无线模式
        if not config.sms_api_key:
            print(f"[UMCP] ⚠️ 互亿无线配置不完整: 缺少 IHUYI_SMS_API_KEY，将使用开发模式", file=sys.stderr)
            sms_mode = "开发(控制台输出)"
        else:
            sms_mode = "生产(互亿无线)"
    elif config.sms_access_key_id:
        # 阿里云模式
        missing = []
        if not config.sms_access_key_secret:
            missing.append("ALIYUN_SMS_ACCESS_KEY_SECRET")
        if not config.sms_sign_name:
            missing.append("ALIYUN_SMS_SIGN_NAME")
        if not config.sms_template_code:
            missing.append("ALIYUN_SMS_TEMPLATE_CODE")
        if missing:
            print(f"[UMCP] ⚠️ 阿里云配置不完整: 缺少 {', '.join(missing)}，将使用开发模式", file=sys.stderr)
            sms_mode = "开发(控制台输出)"
        else:
            sms_mode = "生产(阿里云)"
    else:
        sms_mode = "开发(控制台输出)"
    print(f"[UMCP] 短信通知: {sms_mode}模式", file=sys.stderr)

    server.start()
    app = create_app(server, config)

    try:
        import uvicorn
    except ImportError:
        print("请安装 uvicorn: pip install uvicorn[standard]", file=sys.stderr)
        sys.exit(1)

    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()