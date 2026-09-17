#!/usr/bin/env python3
"""微信支付部署检查清单。

验证所有微信支付 V3 所需的环境变量和证书文件是否已就绪。

用法：
    python scripts/deploy_checklist.py

检查项：
  1. 微信支付环境变量（WECHAT_APP_ID, WECHAT_MCH_ID 等）
  2. 商户私钥 PEM 文件是否存在且可读
  3. 回调地址是否为 HTTPS
  4. APIv3 密钥长度是否合法（32 字节）
  5. 证书序列号格式
  6. 网络连通性（可选，通过 --check-network 启用）
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# 检查函数
# ---------------------------------------------------------------------------

REQUIRED_VARS = [
    "WECHAT_APP_ID",
    "WECHAT_MCH_ID",
    "WECHAT_API_V3_KEY",
    "WECHAT_MCH_SERIAL_NO",
    "WECHAT_PRIVATE_KEY_PATH",
    "WECHAT_NOTIFY_URL",
]

VAR_LABELS = {
    "WECHAT_APP_ID": "微信开放平台 AppID",
    "WECHAT_MCH_ID": "微信商户号",
    "WECHAT_API_V3_KEY": "APIv3 密钥（32 字节）",
    "WECHAT_MCH_SERIAL_NO": "商户证书序列号",
    "WECHAT_PRIVATE_KEY_PATH": "商户私钥 PEM 文件路径",
    "WECHAT_NOTIFY_URL": "支付回调通知地址",
}


def check_env_vars() -> int:
    """检查微信支付环境变量是否配置。返回缺失数量。"""
    missing = 0
    for var in REQUIRED_VARS:
        value = os.getenv(var, "")
        if not value:
            print(f"  ❌ {VAR_LABELS.get(var, var)}: 未设置 (环境变量 {var})")
            missing += 1
        else:
            print(f"  ✅ {VAR_LABELS.get(var, var)}: {_mask_value(var, value)}")
    return missing


def _mask_value(var: str, value: str) -> str:
    """对敏感变量做脱敏显示。"""
    sensitive = {"WECHAT_APP_ID", "WECHAT_MCH_ID", "WECHAT_API_V3_KEY", "WECHAT_MCH_SERIAL_NO"}
    if var in sensitive:
        return value[:4] + "****" + value[-4:] if len(value) > 8 else "****"
    return value


def check_private_key() -> bool:
    """检查商户私钥文件是否存在且可读。"""
    key_path = os.getenv("WECHAT_PRIVATE_KEY_PATH", "")
    if not key_path:
        return False

    path = Path(key_path)
    if not path.exists():
        print(f"  ❌ 商户私钥文件不存在: {key_path}")
        return False
    if not path.is_file():
        print(f"  ❌ 商户私钥路径不是文件: {key_path}")
        return False

    # 检查文件内容是否为 PEM 格式
    try:
        content = path.read_text("utf-8")
        if "-----BEGIN PRIVATE KEY-----" not in content:
            print(f"  ❌ 商户私钥文件不是 PEM 格式: {key_path}")
            return False
        print(f"  ✅ 商户私钥文件存在且格式正确: {key_path}")
        return True
    except Exception as e:
        print(f"  ❌ 商户私钥文件读取失败: {e}")
        return False


def check_notify_url() -> bool:
    """检查回调地址格式。"""
    notify_url = os.getenv("WECHAT_NOTIFY_URL", "")
    if not notify_url:
        return False

    if not notify_url.startswith("https://"):
        print(f"  ❌ 回调地址不是 HTTPS: {notify_url}")
        return False
    if not notify_url.startswith("https://") or len(notify_url) < 10:
        print(f"  ❌ 回调地址格式异常: {notify_url}")
        return False
    print(f"  ✅ 回调地址格式正确: {notify_url}")
    return True


def check_api_v3_key() -> bool:
    """检查 APIv3 密钥长度（应为 32 字节）。"""
    key = os.getenv("WECHAT_API_V3_KEY", "")
    if not key:
        return False

    key_bytes = key.encode("utf-8")
    if len(key_bytes) != 32:
        print(f"  ❌ APIv3 密钥长度异常: {len(key_bytes)} 字节（应为 32 字节）")
        return False
    print(f"  ✅ APIv3 密钥长度正确: 32 字节")
    return True


def check_serial_no() -> bool:
    """检查证书序列号格式。"""
    serial = os.getenv("WECHAT_MCH_SERIAL_NO", "")
    if not serial:
        return False

    # 序列号通常是十六进制字符串
    if not all(c in "0123456789ABCDEFabcdef" for c in serial):
        print(f"  ❌ 证书序列号包含非法字符: {serial}")
        return False
    print(f"  ✅ 证书序列号格式正确: {serial[:8]}...")
    return True


def check_network_connectivity() -> bool:
    """检查与微信支付 API 的网络连通性。"""
    import urllib.request
    import urllib.error

    url = "https://api.mch.weixin.qq.com/v3/certificates"
    print(f"  ⏳ 正在检查网络连通性: {url}...")
    try:
        req = urllib.request.Request(url, method="GET")
        # 只检查连接，不关心响应，设置短超时
        resp = urllib.request.urlopen(req, timeout=5)
        print(f"  ✅ 网络连通性正常 (HTTP {resp.status})")
        return True
    except urllib.error.HTTPError as e:
        # HTTP 401/403 说明网络是通的，只是认证失败，这符合预期
        if e.code in (401, 403):
            print(f"  ✅ 网络连通性正常 (HTTP {e.code}，认证拒绝符合预期)")
            return True
        print(f"  ❌ 网络连通性异常: HTTP {e.code}")
        return False
    except Exception as e:
        print(f"  ❌ 网络连通性异常: {e}")
        return False


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="微信支付部署检查清单")
    parser.add_argument("--check-network", action="store_true", help="检查与微信支付 API 的网络连通性")
    args = parser.parse_args()

    print("=" * 60)
    print("  微信支付 V3 部署检查清单")
    print("=" * 60)

    failed = 0
    total = 0

    # 1. 环境变量
    print("\n📋 1. 环境变量检查")
    total += 1
    missing = check_env_vars()
    if missing > 0:
        failed += 1

    # 2. APIv3 密钥长度
    print("\n📋 2. APIv3 密钥长度检查")
    total += 1
    if not check_api_v3_key():
        failed += 1

    # 3. 证书序列号格式
    print("\n📋 3. 证书序列号格式检查")
    total += 1
    if not check_serial_no():
        failed += 1

    # 4. 商户私钥文件
    print("\n📋 4. 商户私钥文件检查")
    total += 1
    if not check_private_key():
        failed += 1

    # 5. 回调地址
    print("\n📋 5. 回调地址检查")
    total += 1
    if not check_notify_url():
        failed += 1

    # 6. 网络连通性（可选）
    if args.check_network:
        print("\n📋 6. 网络连通性检查")
        total += 1
        if not check_network_connectivity():
            failed += 1

    # 汇总
    print()
    print("=" * 60)
    if failed == 0:
        print(f"  ✅ 全部 {total} 项检查通过，可以部署微信支付")
        sys.exit(0)
    else:
        print(f"  ❌ {failed}/{total} 项检查未通过，请修复后再部署")
        sys.exit(1)


if __name__ == "__main__":
    main()