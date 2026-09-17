"""自动日志告警监控器。

基于 log_alert_rules.yaml 配置文件，实时监控日志输出并触发告警。

用法:
    # 监控标准日志文件
    python -m umcp_core.transport.log_monitor --log-file /var/log/umcp/app.log

    # 同时监控 stderr 管道
    python -m umcp_core.transport.log_monitor --stdin

    # 仅测试告警规则（不启动监控循环）
    python -m umcp_core.transport.log_monitor --dry-run --log-file tests/_test_run.log
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
import yaml
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 日志解析正则（匹配当前日志格式）
# 格式: %(asctime)s [%(levelname)s] %(name)s: %(message)s
# 示例: 2026-08-08 14:30:00 [INFO] umcp_core.transport.auth: Issuing tokens for user
LOG_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
    r" \[(?P<level>\w+)\]"
    r" (?P<logger>[^:]+):"
    r" (?P<message>.*)$"
)


class AlertRule:
    """单条告警规则。"""

    def __init__(self, config: dict[str, Any]) -> None:
        self.name: str = config["name"]
        self.severity: str = config.get("severity", "warning")
        self.level: str = config.get("level", "ERROR")
        self.logger_prefix: str | None = config.get("logger")
        self.pattern: str = config["pattern"]
        self.regex: re.Pattern = re.compile(config["pattern"])
        self.channels: list[str] = config.get("channels", [])
        self.message_template: str = config.get("message", "[{severity}] {name}: {matched_line}")
        self._last_alert_at: float = 0.0

    def matches(self, parsed: dict[str, str] | None) -> bool:
        if parsed is None:
            return False
        if parsed["level"] != self.level:
            return False
        if self.logger_prefix and not parsed["logger"].startswith(self.logger_prefix):
            return False
        return bool(self.regex.search(parsed["message"]))

    def should_alert(self, cooldown: float) -> bool:
        now = time.time()
        if now - self._last_alert_at < cooldown:
            return False
        self._last_alert_at = now
        return True

    def format_message(self, parsed: dict[str, str]) -> str:
        return self.message_template.format(
            severity=self.severity,
            name=self.name,
            matched_line=parsed["message"],
            logger=parsed["logger"],
            level=parsed["level"],
            timestamp=parsed["timestamp"],
        )


class RateLimitRule:
    """速率限制告警规则（基于滑动窗口计数）。"""

    def __init__(self, config: dict[str, Any]) -> None:
        self.name: str = config["name"]
        self.pattern: str = config["pattern"]
        self.regex: re.Pattern = re.compile(config["pattern"])
        self.window_seconds: int = config["window_seconds"]
        self.threshold: int = config["threshold"]
        self.severity: str = config.get("severity", "warning")
        self.channels: list[str] = config.get("channels", [])
        self.message_template: str = config.get("message", "[{severity}] 速率告警: {name} ({count}次/{window}s)")
        self._timestamps: list[float] = []
        self._last_alert_at: float = 0.0

    def record(self, parsed: dict[str, str] | None) -> None:
        if parsed is None:
            return
        if not self.regex.search(parsed["message"]):
            return
        now = time.time()
        self._timestamps.append(now)
        # 清理窗口外的记录
        cutoff = now - self.window_seconds
        self._timestamps = [t for t in self._timestamps if t > cutoff]

    def check(self, cooldown: float) -> str | None:
        now = time.time()
        if now - self._last_alert_at < cooldown:
            return None
        count = len(self._timestamps)
        if count >= self.threshold:
            self._last_alert_at = now
            return self.message_template.format(
                severity=self.severity,
                name=self.name,
                count=count,
                window=self.window_seconds,
                threshold=self.threshold,
            )
        return None


class LogMonitor:
    """日志监控器：读取日志流，匹配规则，触发告警。"""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = Path(config_path) if config_path else self._default_config_path()
        self.rules: list[AlertRule] = []
        self.rate_limits: list[RateLimitRule] = []
        self.channels: dict[str, Any] = {}
        self.check_interval: int = 60
        self.alert_cooldown: int = 300
        self._load_config()

    @staticmethod
    def _default_config_path() -> Path:
        return Path(__file__).resolve().parent / "log_alert_rules.yaml"

    def _load_config(self) -> None:
        if not self.config_path.exists():
            logger.warning("告警规则配置文件不存在: %s", self.config_path)
            return
        with open(self.config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        if not config:
            return

        global_cfg = config.get("global", {})
        self.check_interval = global_cfg.get("check_interval_seconds", 60)
        self.alert_cooldown = global_cfg.get("alert_cooldown_seconds", 300)
        self.channels = config.get("channels", {})
        default_channels = global_cfg.get("default_channels", ["console"])

        for rule_cfg in config.get("rules", []):
            if "channels" not in rule_cfg:
                rule_cfg["channels"] = default_channels
            self.rules.append(AlertRule(rule_cfg))

        for rl_cfg in config.get("rate_limits", []):
            if "channels" not in rl_cfg:
                rl_cfg["channels"] = default_channels
            self.rate_limits.append(RateLimitRule(rl_cfg))

        logger.info(
            "已加载 %d 条告警规则 + %d 条速率限制规则",
            len(self.rules), len(self.rate_limits),
        )

    def parse_line(self, line: str) -> dict[str, str] | None:
        """解析单行日志，返回结构化字段。"""
        line = line.strip()
        if not line:
            return None
        m = LOG_PATTERN.match(line)
        if not m:
            return None
        return m.groupdict()

    def dispatch_alert(self, message: str, channels: list[str]) -> None:
        """分发告警到指定通道。"""
        for channel in channels:
            if channel == "console":
                print(f"[ALERT] {message}", file=sys.stderr, flush=True)
            elif channel == "file":
                self._write_to_file(message)

    def _write_to_file(self, message: str) -> None:
        """写入告警到文件。"""
        channel_cfg = self.channels.get("file", {})
        filepath = channel_cfg.get("path", "logs/alerts.log")
        p = Path(filepath)
        p.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} [ALERT] {message}\n")

    def process_line(self, line: str) -> list[str]:
        """处理单行日志，返回触发的告警消息列表。"""
        alerts: list[str] = []
        parsed = self.parse_line(line)
        if parsed is None:
            return alerts

        # 检查告警规则
        for rule in self.rules:
            if rule.matches(parsed) and rule.should_alert(self.alert_cooldown):
                msg = rule.format_message(parsed)
                alerts.append(msg)
                self.dispatch_alert(msg, rule.channels)

        # 记录速率限制
        for rl in self.rate_limits:
            rl.record(parsed)

        return alerts

    def check_rate_limits(self) -> list[str]:
        """检查所有速率限制，返回触发的告警。"""
        alerts: list[str] = []
        for rl in self.rate_limits:
            msg = rl.check(self.alert_cooldown)
            if msg:
                alerts.append(msg)
                self.dispatch_alert(msg, rl.channels)
        return alerts

    def run_forever(self, log_file: str | None = None, stdin: bool = False) -> None:
        """启动监控循环。

        Args:
            log_file: 监控的文件路径（支持 tail -f 模式）
            stdin: 是否从标准输入读取
        """
        print(f"[LogMonitor] 启动告警监控 (interval={self.check_interval}s)", file=sys.stderr)
        print(f"[LogMonitor] 已加载 {len(self.rules)} 条规则, {len(self.rate_limits)} 条速率限制", file=sys.stderr)

        if log_file:
            self._tail_file(log_file)
        elif stdin:
            self._read_stdin()
        else:
            print("[LogMonitor] 请指定 --log-file 或 --stdin", file=sys.stderr)
            sys.exit(1)

    def _tail_file(self, filepath: str) -> None:
        """类似 tail -f 监控文件。"""
        path = Path(filepath)
        if not path.exists():
            print(f"[LogMonitor] 日志文件不存在: {filepath}", file=sys.stderr)
            sys.exit(1)

        # 先读到文件末尾
        with open(path, encoding="utf-8") as f:
            f.seek(0, os.SEEK_END)
            last_rate_check = time.time()

            try:
                while True:
                    line = f.readline()
                    if line:
                        self.process_line(line)
                    else:
                        # 定时检查速率限制
                        now = time.time()
                        if now - last_rate_check >= self.check_interval:
                            self.check_rate_limits()
                            last_rate_check = now
                        time.sleep(0.1)
            except KeyboardInterrupt:
                print("\n[LogMonitor] 已停止", file=sys.stderr)

    def _read_stdin(self) -> None:
        """从标准输入读取日志流。"""
        last_rate_check = time.time()
        try:
            for line in sys.stdin:
                if line:
                    self.process_line(line)
                now = time.time()
                if now - last_rate_check >= self.check_interval:
                    self.check_rate_limits()
                    last_rate_check = now
        except KeyboardInterrupt:
            print("\n[LogMonitor] 已停止", file=sys.stderr)


# =============================================================================
# 命令行入口
# =============================================================================

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="UMCP 日志告警监控器")
    parser.add_argument("--log-file", help="监控的日志文件路径")
    parser.add_argument("--stdin", action="store_true", help="从标准输入读取日志")
    parser.add_argument("--config", help="告警规则配置文件路径（默认: log_alert_rules.yaml）")
    parser.add_argument("--dry-run", action="store_true", help="仅测试规则，不启动监控循环")
    args = parser.parse_args()

    monitor = LogMonitor(config_path=args.config)

    if args.dry_run:
        print(f"[LogMonitor] 规则加载测试完成: {len(monitor.rules)} 条告警规则, {len(monitor.rate_limits)} 条速率限制")
        print(f"[LogMonitor] 配置文件: {monitor.config_path}")
        for rule in monitor.rules:
            print(f"  - [{rule.severity}] {rule.name}: {rule.pattern}")
        for rl in monitor.rate_limits:
            print(f"  - [RATE:{rl.severity}] {rl.name}: {rl.pattern} ({rl.threshold}次/{rl.window_seconds}s)")
        return

    monitor.run_forever(log_file=args.log_file, stdin=args.stdin)


if __name__ == "__main__":
    main()