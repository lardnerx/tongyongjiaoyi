# 真实试用上线计划

- 制定日期：2026-11-17
- 适用环境：生产 ECS（182.61.33.203）+ PostgreSQL 16 本机实例 + pm2/Next.js + systemd/umcp
- 目标：让系统进入「真实用户、真实支付、可运营」的试用状态

## 零、现状基线（已具备）

| 能力 | 状态 |
|---|---|
| 域名 / HTTPS / ICP 备案 / 用户协议 / 隐私政策 / 关于我们 | 已上线 |
| PostgreSQL 持久化（8 张表）+ 每日备份 | 已接入 |
| 严格认证（禁自动建号、强制密码） | 已生效 |
| 任务/交易双状态机、匹配、评价、信用 | 已实现 |
| 订单全流程 API（下单→接单→打卡→完成→评价→退款） | 已实现 |
| 微信支付 V3 代码、回调验签、支付超时 Worker | 已实现，默认走 Mock |
| 短信通知（互亿/阿里云/开发模式） | 已实现，仅用于业务通知 |

## 一、P0 阶段 1：真实收款

- [~] 1.1 配置微信支付真实凭证（凭证已配置，被 AppID 未认证阻塞）
  - 已完成：`.env` 5 项 `WECHAT_*` 已配置；私钥已落到 `/opt/umcp/certs/` 并 `chmod 600`；回调地址 `https://jishi100.online/api/v1/escort/payments/callback`
  - 已完成：修复启动顺序 bug（插件在配置注入前注册，导致回退 Mock），commit `1edeb97`
  - 阻塞 1：商户号未开通 Native 支付（`NO_AUTH`）
  - 阻塞 2：AppID 未通过微信认证，无法关联商户号（`APPID_MCHID_NOT_MATCH`）
  - 待办：完成微信认证 → 商户平台关联 AppID → 开通 Native 支付 → 恢复 `WECHAT_APP_ID` 并重启
  - 当前状态：临时注释 `WECHAT_APP_ID`，回落 Mock 继续联调其余环节
- [x] 1.2 支付单落库
  - 新增 `payments` 表（与 `InMemoryPaymentRepository` 接口对齐）
  - 新增 `PostgresPaymentRepository`
  - 启动时按是否配置 DSN 注入，与其它仓储保持同一套切换逻辑
  - 验收：支付完成→重启后端→支付记录仍可查
- [ ] 1.3 支付对账
  - 脚本：拉取微信订单与本地 deal 状态比对，输出差异清单
  - 覆盖：已支付未激活、已关闭未退款、回调丢失
- [ ] 1.4 退款联调
  - 全额 / 部分退款、取消赔付档位（`escort.cancel.scheduled.penalty_tiers`）
- [ ] 1.5 教练结算说明
  - 系统无提现/分账模块，试用期线下人工结算
  - 在用户协议与订单页写明结算周期与方式

## 二、P0 阶段 2：账号安全闭环

- [ ] 2.1 短信验证码接口
  - `POST /api/v1/auth/sms/send`、`POST /api/v1/auth/sms/verify`
  - 注册、登录、重置密码接入
- [ ] 2.2 防刷策略
  - 同号 60s 一次、单日上限、验证码 5 分钟有效、失败 5 次锁定
- [ ] 2.3 自助重置密码
  - 严格模式下改为「手机号 + 验证码 + 新密码」，重新开放 `/auth/reset-password`
- [ ] 2.4 限流与 CORS
  - `UMCP_RATE_LIMIT_ENABLED=true`，登录/发码接口单独更严阈值
  - `UMCP_CORS_ORIGINS` 收敛为 `https://jishi100.online`

## 三、P0 阶段 3：服务资质

- [ ] 3.1 实名与驾照
  - 学员/教练实名信息字段、驾照照片上传、有效期校验
- [ ] 3.2 后台审核
  - 审核列表、通过/驳回/封禁；未审核教练不可上线接单
- [ ] 3.3 行程安全（按试用范围裁剪）
  - 紧急联系人、行程分享链接

## 四、P1 阶段 4：稳定性与运维

- [x] 4.1 规则配置持久化（`PostgresRuleRepository` 注入 + `business_rules` / `business_rule_history` 建表，支持标量/列表值）
  - 生产验证通过（2026-11-17，commit `dbc5e6e`）：PUT 后 `version=1`，`systemctl restart umcp` 后 GET 仍为 `version=1`、`is_default=false`，两表各有 1 行
  - 顺带修复 `user_from_orm` 对 roles 脏数据（列表）的容错，并支持还原 admin 角色
  - 同步清单补齐 `repositories/postgres/converters.py`、`transport/routers/admin/rules.py`
- [x] 4.2 通知留痕（站内消息表）
  - `NotificationCenter` 落库（`notifications` 表），渠道发送失败/未注册不影响留痕
  - `InMemoryNotificationRepository` / `PostgresNotificationRepository` 双实现，启动时自动建表
  - 新增接口：`GET /api/v1/notifications`、`GET /api/v1/notifications/unread-count`、`POST /api/v1/notifications/{id}/read`、`POST /api/v1/notifications/read-all`
  - 生产验证通过（2026-11-17，commit `b0e72b6`）：日志 `站内消息仓储: PostgresNotificationRepository`；写入 1 条后列表 `total_unread=1`，标记已读后未读数归 0，`notifications.read_at` 已更新
  - 业务通知渠道由「WS + SMS」改为「WS + 站内」（`_NOTIFY_CHANNELS = ["IN_APP", "WS_PUSH"]`）；SMS 渠道保留但仅用于后续验证码等场景
- [x] 4.3 监控告警（可用性、5xx、DB 连接数、磁盘、备份失败）
  - 已提供 `deploy/healthwatch.sh` + `umcp-healthwatch.service` + `umcp-healthwatch.timer`（每分钟巡检，仅写本地日志，状态变化才记录）
  - 生产验证通过（2026-11-17，commit `1a1ffb2`/`08a8f02`）：`-v` 五项全 ok（db 连接数 2、磁盘 25%）；`list-timers` 每分钟按时触发；模拟故障输出 `[ALERT] backend 异常: HTTP 000`；状态文件落在 `/run/umcp-healthwatch/`
  - 首次 `enable --now` 时出现一次 `203/EXEC`，12:32 起恢复正常，判定为首次拉起竞态，无需处理
  - 备份检查暂未启用（`BACKUP_DIR` 为空自动跳过），4.4 完成后填入
- [~] 4.4 备份异地副本（COS/OSS）
  - 决策（2026-11-17）：先只做本地备份，异地副本待对象存储开通后再接
  - 备份对象：PostgreSQL 全库（`umcp`）+ `/opt/umcp/.env` + `/opt/umcp/certs/`
  - 已实现：
    1. `deploy/backup.sh`：`pg_dump -Fc` 输出 `/var/backups/umcp/umcp_YYYYmmdd_HHMM.dump`，`pg_restore --list` 自检，`.env`+`certs` 打包为 600 权限 tar.gz，本地保留 14 天
    2. `umcp-backup.service` + `umcp-backup.timer`：每日 03:30（`Persistent=true` 补跑错过的执行）
    3. 成功 `touch /var/backups/umcp/.last_success`，失败写 `/var/log/umcp/healthwatch.log`
    4. 4.3 联动：`umcp-healthwatch.service` 设 `BACKUP_DIR=/var/backups/umcp`、`BACKUP_MAX_AGE_HOURS=26`，超期自动 ALERT
  - 本地部分生产验证通过（2026-11-17，commit `fb8fff5`/`18bcf8e`）：首次备份产出 `umcp_20261117_1340.dump`（21K）与 `umcp_secrets_*.tar.gz`（2.1K），`pg_restore --list` 自检通过；`umcp-backup.timer` NEXT 为次日 03:30；巡检 `backup ok 最新备份 0 小时前`
  - 恢复演练通过：`pg_restore` 到 `umcp_restore_test` 后 `users=2 / deals=0 / notifications=1`，与生产一致；注意 dump 为 600/root，恢复时用 `sudo -u postgres pg_restore ... < "$DUMP"` 由 root 读文件
  - 已知坑：`sync.sh` 覆盖文件会丢可执行位，systemd 单元已改为 `/bin/bash <script>` 调用
  - 待接入（异地）：rclone 上传私有 COS `umcp/db/`，保留 30 天
  - 恢复演练（验收项 6）：取最新 dump → 创建 `umcp_restore_test` → `pg_restore` → 抽查 `users`/`deals`/`notifications` 行数 → 删除测试库
- [ ] 4.5 发布通道固化（`/opt/umcp/sync.sh` 已可用，补 commit 记录表）

## 五、P1 阶段 5：合规与运营

- [ ] 5.1 公安联网备案号、客服电话、发票与退款规则页
- [ ] 5.2 计价规则、抽成比例、取消赔付档位按真实业务配置
- [ ] 5.3 种子数据与闭环演练（下单→接单→支付→打卡→完成→评价→退款）
- [ ] 5.4 试用期客服 SOP（改密、退款、投诉）

## 六、验收标准

1. 真实微信支付 1 分钱订单可回调入库，重启后端后记录仍在
2. 未审核教练无法上线接单，审核通过后可被匹配
3. 新用户必须短信验证码注册，错码/超频被拒
4. 忘记密码可自助重置，无需人工
5. 重启后端后取消政策与支付超时配置不丢失
6. 备份存在异地副本，并完成一次恢复演练
7. 服务不可用 5 分钟内触发告警

## 七、执行顺序与依赖

```
1.1（需商户凭证）─→ 1.2 ─→ 1.3 ─→ 1.4
                                └─→ 1.5（文档）
2.1（需短信凭证）─→ 2.2 ─→ 2.3
2.4（可并行）
3.1 ─→ 3.2 ─→ 3.3
4.x、5.x（试用启动后迭代）
```

外部依赖（需业务方提供）：

- 微信支付商户号、APIv3 密钥、商户证书（1.1）
- 互亿无线 API ID / KEY / 签名（2.1）
- 公安联网备案号（5.1）
