# 《即时百分百》阶段性总结：规划 vs 现状

**版本**：1.0.0
**生成日期**：2026-09-18
**文档定位**：对比项目初期规划（开发架构 / 云环境 / 各类接口）与开发到现阶段的项目实际情况，作为阶段性交付与后续迭代的参考基线。

---

## 一、总览

| 维度 | 早期规划（2026-07-30 MVP 设计规格） | 当前实际（commit d684ef7） | 达成度 |
|------|-----------------------------------|---------------------------|--------|
| 后端架构 | umcp-core 七层协议栈 + FastAPI + 共享基础设施层 | 核心库、3 插件、共享层 5 模块全部落地 | 很高 |
| 前端架构 | Next.js 14 App Router + 业务路由分区 | Next.js 前端已建成（web/ 目录） | 较高 |
| 云环境 | 国内云 ECS×2 + RDS 主从 + CDN/SLB + OSS | 单台 ECS + Docker Compose + Nginx + 域名 | 中等 |
| 接口 | 认证/任务/交易/信任/陪驾/平台/共享层 | 71 个端点，覆盖规划的大部分 | 较高 |
| 支付 | 支付宝 + 微信双网关 | 微信支付 V3 已配置待实测，无支付宝 | 中等 |
| 部署 | 生产就绪 + CI/CD | 生产部署完成，GitHub Actions 就绪 | 较高 |

---

## 二、开发架构对比

### 2.1 规划版（方案 A'：混合共享）

- 三层共享架构：共享基础设施层（认证/支付/LBS/通知/存储/规则）→ 共享领域层（umcp-core）→ 业务层（escort/ride/group 按 domain 隔离）
- 前端：Next.js 14 + shadcn/ui + Zustand + React Query + 高德地图
- 数据库：核心表复用 + 业务扩展表（escort_*）+ 共享基础设施表（payments/notifications/lbs_locations/files/business_rules），PostGIS 空间索引

### 2.2 实际版

- 核心库完整落地：L1-L7 七层协议栈、EventBus、任务/交易双状态机、6 种支付模式抽象全部实现
- 共享层落地：payment（base/wechat/mock）、notification（WS/短信/模板/中心）、rules（配置/仓储/模型）、storage（本地/仓储）、lbs（内存/仓储）五模块齐全
- 三个插件：escort_driving（实际运行）、ride_hailing、group_buying（代码+测试完整，未接入路由）
- Web 前端实际路由：
  - 身份层：login / register / reset-password
  - 学员端：book-instant（实时单）、book-scheduled（预约单）、orders 列表/详情/支付页
  - 教练端：接单大厅、orders、订单详情
  - 个人中心：dashboard / profile / settings/password
  - 好友：friends；运营：admin/rules；组件含地图选择器、支付页组件族

### 2.3 差异

规划的"多业务路由分区"目前仅 escort 真正跑通；教练列表/日程管理、admin 的 dashboard/教练审核/争议处理、平台级运营页（users/stats）尚未建页面；高德地图仅为前端组件，后端 LBS 为内存实现（无 PostGIS）。

---

## 三、云环境对比

| 项 | 规划 | 实际 |
|----|------|------|
| 拓扑 | CDN → SLB → ECS×2 → RDS（主从+PostGIS）/ Redis（主从）/ OSS | 单台 ECS 182.61.33.203，生产目录 /opt/umcp |
| 容器编排 | compose 双副本水平扩展 | postgres:16 + redis:7 + app + pgbackup（每日备份留 7 天），均仅监听 127.0.0.1 |
| 入口 | SLB 负载均衡 | Nginx 反代：jishi100.online 域名 + Let's Encrypt 证书、HTTP→HTTPS 301、WebSocket 升级、安全头 |
| 支付 | 支付宝 + 微信 | 微信支付 V3（回调 182.61.33.203，私钥 /opt/umcp/certs/apiclient_key.pem），已配置待实测；支付宝未接入 |
| 短信 | 阿里云短信 | 互亿无线（IHUYI_SMS_*） |
| 其他外部服务 | 高德地图 API、小程序订阅消息、OSS | 均未接入（存储用本地 uploads 目录） |

**结论**：云环境从"双机高可用"规划收敛为"单机低成本落地"，域名、HTTPS、数据库、备份、限流、日志监控均已就位，满足生产可用的最小闭环。

---

## 四、接口对比

### 4.1 规划版接口面

`/api/v1/auth/*`、`/users/*`、`/ws/*`、`/events/*`、`/escort/tasks|deals|trust/*`、平台级 `/admin/users|stats|rules`，统一响应信封 `{"code":0,...}`

### 4.2 实际版接口面（共 71 个端点）

| 分组 | 实际端点 | 状态 |
|------|---------|------|
| 健康 | /health、/health/ready（含 DB 连通性） | 完成 |
| 认证 | login/register/refresh/logout/me/switch-role/change-password/reset-password/avatar | 完成 |
| 核心 | tasks、resources、matches、deals（含 dispute/cancel/resolve）、trust、events | 完成 |
| 陪驾订单 | orders 创建/列表/详情/取消/抢单/签到/签退/选教练/cancel-rules | 完成 |
| 教练 | 接单（deals/accept）、check-in/out、上线/下线 | 完成 |
| 评价 | orders/{task_id}/reviews 双向互评 | 完成 |
| 支付 | create/callback/{deal_id}/{payment_id}/close/{deal_id}/timeout/mock-pay | 完成 |
| 规则 | admin/rules 增查改/历史/回滚 | 完成 |
| 社交 | friends 请求/接受/拒绝/列表/删除 | 完成 |
| LBS | /nearby、coaches/{id}/location | 基础版 |
| 实时 | /api/v1/ws/events（WebSocket 推送）、/metrics、/api/v1/uploads | 完成 |

### 4.3 差异

规划中的 `/api/v1/users/*` 平台级用户管理和 `/admin/stats` 统计未实现；`/events` 仅支持查询（规划为事件回放）；LBS 无真实空间索引。实际新增了规划外能力：限流中间件（支付回调豁免）、支付超时 worker、实时单取消 worker、日志监控告警。

---

## 五、关键功能达成度

| 功能 | 规划 | 实际 |
|------|------|------|
| 实时单（派单+抢单+扩圈） | 动态扩圈匹配 | 抢单 claim + 实时取消 worker，扩圈参数可配 |
| 预约单（Top3 推荐+选教练） | Top3 评分 | select-coach + scheduled_match 实现 |
| 双向互评 + 信任分 | 3+3 维度 | reviews + trust/evaluations 完成 |
| 支付（定金/尾款/退款/超时） | 支付宝+微信 | 微信 V3 + mock，超时自动关闭 worker |
| 规则配置中心 | 12 类规则可配置 | business_rules 表 + 缓存 + 历史回滚 |
| 取消策略与信用扣减 | 策略矩阵 | cancel-rules + credit 逻辑 |
| 好友关系 | 服务后加好友 | 完整 |
| 通知 | WS+短信+订阅消息 | WS + 互亿短信（无订阅消息） |
| 文件存储 | OSS | 本地 uploads + 头像上传 |
| 可观测性 | Prometheus + 日志 + 告警 | /metrics + 统一日志 + 日志监控告警 |

---

## 六、遗留差距（下一步方向）

1. 支付实测：微信支付 V3 已配置，需真实下单验证回调闭环
2. 支付宝接入：双网关仅完成微信侧
3. LBS 升级：内存实现 → PostGIS + 高德真实定位
4. 前端补齐：教练列表/日程、运营后台（审核/争议/统计）
5. 高可用：单机 → 双副本 + RDS 主从（MVP 阶段可接受）

---

**文档结束**
