# 陪驾 Web 应用 MVP 设计规格

**版本**：1.0.0
**创建日期**：2026-07-30
**适用范围**：基于 umcp-core 构建的陪驾业务 Web 应用 MVP
**文档定位**：面向开发团队，完整说明陪驾 Web 应用 MVP 的架构、数据库、业务流程、共享层、前端、部署、错误处理与测试设计。

---

## 一、概述

### 1.1 背景

umcp-core（Universal Market Coordination Protocol）已完阶段一至五D的全部产出，包括：

- 核心固件库（任务/资源/交易/事件/状态机）
- 三个行业插件（ride_hailing / escort_driving / group_buying）
- 多插件并存 + 跨域信任隔离 + 复合任务编排
- PostgreSQL 持久化 + HTTP API + JWT 认证 + WebSocket 推送
- 部署就绪（Docker / CI/CD / Prometheus / 统一日志）

本阶段在 umcp-core 之上构建**首个实际可用的 Web 应用**，验证 umcp-core 的生产可用性，同时为后续多业务扩展奠定架构基础。

### 1.2 阶段目标

- **业务目标**：交付生产可用的陪驾 Web 应用，支撑 500-1000 学员 + 20-100 教练的中等规模运营
- **技术目标**：验证 umcp-core 核心能力（匹配/信任/事件/编排），补齐生产所需的共享基础设施（支付/LBS/通知/存储）
- **架构目标**：单业务起步但架构层面预留多业务扩展能力，新增业务成本最小化

### 1.3 核心约束

| 维度 | 决策 |
|------|------|
| 业务 | 陪驾（escort_driving），单业务起步 |
| 目标 | 生产可用型（真实用户使用） |
| 规模 | 中等（500-1000 学员 + 20-100 教练） |
| 后端 | umcp-core（Python FastAPI）+ PostgreSQL |
| 前端 | React + Next.js 14（App Router） |
| 匹配模式 | 实时单（系统派单+教练抢单）+ 预约单（Top3 推荐+学员选择） |
| 部署 | 国内云服务器（阿里云/腾讯云 ECS + RDS） |
| 社交 | 服务后双方可互加好友、双向互评 |
| 规则 | 业务规则后台可配置（等级/取消/押金/信用等） |

### 1.4 核心设计决策

| 决策项 | 选项 | 采纳 | 理由 |
|--------|------|------|------|
| 应用架构 | 单体重型 / SaaS 多租户 / 混合共享 | 混合共享（方案 A'） | 契合 umcp-core 多 domain 设计，共享层一次建设多业务复用 |
| 前端组织 | 平铺路由 / 业务路由分区 | 业务路由分区 | 为多业务扩展预留，MVP 仅多一层 `/escort` 前缀 |
| 数据库 | 单 schema 平铺 / 表前缀隔离 | 核心表复用 + 业务扩展表 + 共享基础设施表 | 契合 umcp-core domain_tag 设计 |
| 匹配模式 | 单一模式 / 双模式 | 实时单 + 预约单双模式 | 覆盖下班约车与提前规划两种场景 |
| 评价方向 | 单向 / 双向 | 双向互评 | 学员与教练互评，双向信任分 |
| 规则管理 | 硬编码 / 配置化 | 规则配置中心 | 运营可后台调整，无需改代码 |
| 部署 | PaaS / 自建 / 国内云 | 国内云 ECS + RDS | 国内用户访问快，备案简单 |

---

## 二、整体架构

### 2.1 方案 A'：多业务路由分区 + 共享身份层

```
                          ┌─── Nginx (443/80) ──────────────┐
                          │   SSL 终止 + 静态资源 + 反代     │
                          └──────────┬───────────────────────┘
                                     │
            ┌────────────────────────┴────────────────────────┐
            │                                                   │
   ┌────────▼─────────────────────┐              ┌────────────▼────────────┐
   │  Next.js 单应用               │              │  FastAPI (umcp-core)     │
   │                              │              │                          │
   │  ┌─共享身份层──────────────┐ │   HTTP/WS    │  共享层                   │
   │  │ /login    /register     │ │ ───────────► │  /api/v1/auth/*          │
   │  │ /profile  /settings     │ │              │  /api/v1/users/*         │
   │  │ /notifications          │ │              │  /api/v1/ws/*            │
   │  └─────────────────────────┘ │              │  /api/v1/events/*        │
   │                              │              │                          │
   │  ┌─业务路由分区（按业务）──┐ │              │  业务层（按 domain 路由） │
   │  │ /escort/student/* 学员  │ │              │  /api/v1/escort/tasks/*  │
   │  │ /escort/coach/*   教练  │ │              │  /api/v1/escort/deals/*  │
   │  │ /escort/admin/*   业务管│ │              │  /api/v1/escort/trust/*  │
   │  │                         │ │              │                          │
   │  │ (未来) /ride/*  打车    │ │              │  (未来) /api/v1/ride/*   │
   │  │ (未来) /group/* 集采    │ │              │  (未来) /api/v1/group/*  │
   │  └─────────────────────────┘ │              │                          │
   │                              │              │  插件按 domain 注册      │
   │  ┌─平台运营层──────────────┐ │              │  (umcp-core 多插件并存)  │
   │  │ /admin/platform/* 平台级│ │              │                          │
   │  │   跨业务用户/订单/统计   │ │              │                          │
   │  └─────────────────────────┘ │              │                          │
   └──────────────────────────────┘              └────────────┬────────────┘
                                                                │
                                            ┌───────────────────┴───────────────┐
                                            │                                     │
                                   ┌────────▼─────────┐               ┌─────────▼─────────┐
                                   │  RDS PostgreSQL   │               │  Redis            │
                                   │  shared.users     │               │  会话/缓存/限流   │
                                   │  escort.*  表前缀 │               │                   │
                                   │  (未来) ride.*    │               │                   │
                                   │  (未来) group.*   │               │                   │
                                   └──────────────────┘               └───────────────────┘
```

### 2.2 三层共享架构

```
┌─────────────────────────────────────────────────────────┐
│  共享基础设施层（一次建设，多业务复用）                   │
│  ┌──────────┬──────────┬──────────┬──────────┬────────┐ │
│  │ 认证 JWT │ 支付网关 │ LBS 定位 │ 消息通知 │ 文件存储│ │
│  │ (已有)   │ (需新建) │ (需新建) │ (需新建) │ (需新建)│ │
│  └──────────┴──────────┴──────────┴──────────┴────────┘ │
├─────────────────────────────────────────────────────────┤
│  共享领域层（umcp-core 已实现）                          │
│  ┌──────────┬──────────┬──────────┬──────────┬────────┐ │
│  │ 用户/凭证 │ 事件总线 │ 任务编排 │ 信任引擎 │ 匹配引擎│ │
│  │ (已有)   │ (已有)   │ (已有)   │ (已有)   │ (需扩展)│ │
│  └──────────┴──────────┴──────────┴──────────┴────────┘ │
├─────────────────────────────────────────────────────────┤
│  业务层（按 domain 隔离，插件化）                        │
│  ┌────────────┬────────────┬────────────┐               │
│  │ escort 陪驾│ ride 打车  │ group 集采 │               │
│  │ (MVP)      │ (未来)     │ (未来)     │               │
│  └────────────┴────────────┴────────────┘               │
└─────────────────────────────────────────────────────────┘
```

### 2.3 组件复用矩阵

| 组件 | umcp-core 现状 | 复用方式 | MVP 需补充 |
|------|---------------|---------|-----------|
| 登录/认证 | 已实现 JWT（access+refresh）+ 吊销 + WS 认证 | 完全共享 | 无 |
| 用户身份/凭证 | credentials 跨 domain 共享 | 完全共享 | 无 |
| 事件总线/WS推送 | EventBus + WebSocket + WS_PUSHABLE_EVENTS | 完全共享 | 无 |
| 任务编排 | CompositeTask DAG 编排 | 完全共享 | 无 |
| 信任评价 | 4维信任 + domain 隔离 + 跨域聚合 | 共享引擎 | 陪驾3维（teaching/patience/safety）已有 |
| 匹配引擎 | InstantMatch 返回单一最优 | 共享引擎 | 扩展返回 Top3 候选 |
| 支付 | PaymentSchema 抽象 + Hourly/Installment | 共享账面计算 | 新增支付宝/微信支付网关 |
| 定位 LBS | 未实现 | 需新建为共享基础设施 | 新增 PostGIS + 高德 API |
| 消息通知 | WS 推送已有 | WS 共享 | 新增短信/订阅消息 |
| 运营后台 | 无 UI | 共享平台级后台 | 新建 |

---

## 三、项目结构

### 3.1 整体目录结构

```
tongyongjiaoyi/
├── umcp-core/                          # 后端核心库（已有，需扩展）
│   ├── src/umcp_core/
│   │   ├── transport/
│   │   │   ├── routers/
│   │   │   │   ├── auth.py             # 共享（已有）
│   │   │   │   ├── escort/             # 陪驾业务 router（新建）
│   │   │   │   │   ├── tasks.py
│   │   │   │   │   ├── coaches.py
│   │   │   │   │   ├── reviews.py
│   │   │   │   │   └── friends.py
│   │   │   │   └── platform/           # 平台级 router（新建）
│   │   │   │       ├── users.py
│   │   │   │       ├── stats.py
│   │   │   │       └── rules.py
│   │   │   └── shared/                 # 共享基础设施层（新建）
│   │   │       ├── payment/
│   │   │       ├── lbs/
│   │   │       ├── notification/
│   │   │       ├── storage/
│   │   │       └── rules/
│   │   └── ...
│   ├── plugins/escort_driving/         # 陪驾插件（已有，需扩展 Top3）
│   ├── migrations/                     # Alembic 迁移（新增迁移脚本）
│   └── pyproject.toml
│
├── web/                                # 前端 Next.js 应用（新建）
│   ├── src/
│   │   ├── app/                        # App Router
│   │   │   ├── (auth)/                 # 共享身份层
│   │   │   ├── (escort)/               # 陪驾业务路由组
│   │   │   │   ├── student/
│   │   │   │   ├── coach/
│   │   │   │   └── admin/
│   │   │   └── (platform)/             # 平台运营层
│   │   ├── components/
│   │   ├── lib/
│   │   └── middleware.ts
│   ├── package.json
│   └── next.config.js
│
├── infra/                              # 部署配置（新建）
│   ├── docker-compose.yml
│   ├── docker-compose.prod.yml
│   ├── nginx/
│   └── scripts/
│
└── docs/                               # 文档
```

### 3.2 前端路由结构

```
web/src/app/
├── layout.tsx                    # 根布局
├── (auth)/                       # 共享身份层（无需登录）
│   ├── login/                    # 登录（手机+验证码）
│   ├── register/                 # 注册（学员/教练角色选择）
│   └── forgot-password/
├── (escort)/                     # 陪驾业务（需登录）
│   ├── student/                  # 学员端
│   │   ├── book/instant/         # 实时单（定位+等级+呼叫）
│   │   ├── book/scheduled/       # 预约单（时间+地点+Top3选择）
│   │   ├── orders/               # 订单列表与详情
│   │   ├── coaches/              # 教练列表与详情
│   │   ├── friends/              # 我的好友
│   │   └── profile/              # 个人中心（信用分）
│   ├── coach/                    # 教练端
│   │   ├── page.tsx              # 接单大厅
│   │   ├── orders/               # 我的订单
│   │   ├── schedule/             # 日程管理
│   │   └── profile/              # 教练资料 + 证件认证
│   └── admin/                    # 陪驾业务管理
│       ├── dashboard/
│       ├── coaches/              # 教练审核
│       ├── orders/               # 订单监控
│       └── disputes/             # 争议处理
├── (platform)/                   # 平台运营（需管理员权限）
│   └── admin/
│       ├── dashboard/            # 平台总览
│       ├── users/                # 跨业务用户管理
│       ├── rules/                # 规则配置中心
│       ├── stats/                # 数据统计
│       └── system/               # 系统配置
└── middleware.ts                 # 路由守卫
```

---

## 四、数据库设计

### 4.1 设计原则

- **核心表复用**：umcp-core 已有的 `users`/`credentials`/`tasks`/`resources`/`deals`/`event_logs` 通过 `domain_tag='escort'` 过滤陪驾数据
- **业务扩展表**：陪驾特有数据（教练资料/评价/服务记录）作为扩展表，通过外键关联核心表
- **共享基础设施表**：支付/通知/定位/文件等所有业务复用的表
- **规则配置表**：业务规则配置化存储

### 4.2 表结构

#### 4.2.1 共享核心表（umcp-core 已有，通过 domain_tag 区分）

| 表名 | 说明 | 陪驾过滤 |
|------|------|---------|
| users | 用户基础信息 | 所有业务共享 |
| credentials | 用户凭证 | 所有业务共享 |
| tasks | 任务（陪驾需求） | `domain_tag='escort'` |
| resources | 资源（教练） | `domain_tag='escort'` |
| deals | 交易 | `domain_tag='escort'` |
| event_logs | 事件日志 | 按 domain 过滤 |
| trust_profiles | 信任画像 | 按 domain 隔离 |

#### 4.2.2 陪驾业务扩展表（新建）

**escort_coach_profiles**（教练资料扩展）

| 字段 | 类型 | 说明 |
|------|------|------|
| profile_id | PK | |
| user_id | FK users | 教练用户 ID |
| car_model | varchar | 车型 |
| license_plate | varchar | 车牌 |
| service_areas | JSONB | 服务区域（多边形 GeoJSON） |
| hourly_rate | decimal | 时薪（按等级自动设置） |
| coach_level | varchar | BRONZE/SILVER/GOLD/PLATINUM |
| level_updated_at | timestamp | 等级最后更新时间 |
| bio | text | 简介 |
| verified | bool | 是否已审核 |
| verified_at | timestamp | 审核时间 |
| verified_by | FK users | 审核人 |

**escort_reviews**（双向评价）

| 字段 | 类型 | 说明 |
|------|------|------|
| review_id | PK | |
| deal_id | FK deals | 关联订单 |
| reviewer_id | FK users | 评价发起方 |
| reviewee_id | FK users | 被评价方 |
| reviewer_role | varchar | STUDENT / COACH |
| teaching_score | int | 教学能力（学员评教练时填写，1-5） |
| patience_score | int | 耐心程度（学员评教练时填写） |
| safety_score | int | 安全记录（学员评教练时填写） |
| punctuality_score | int | 守时程度（教练评学员时填写） |
| cooperation_score | int | 配合度（教练评学员时填写） |
| payment_score | int | 付款及时性（教练评学员时填写） |
| comment | text | 文字评价 |
| created_at | timestamp | |

**escort_service_records**（服务执行记录）

| 字段 | 类型 | 说明 |
|------|------|------|
| record_id | PK | |
| deal_id | FK deals | 关联订单 |
| check_in_at | timestamp | 签到时间 |
| check_out_at | timestamp | 签退时间 |
| check_in_location | geometry(Point) | 签到位置 |
| check_out_location | geometry(Point) | 签退位置 |
| duration_min | int | 服务时长（分钟） |
| route_geojson | JSONB | 行驶轨迹 |
| status | varchar | IN_SERVICE / COMPLETED |

**friendships**（好友关系，跨业务共享）

| 字段 | 类型 | 说明 |
|------|------|------|
| friendship_id | PK | |
| user_id_a | FK users | 发起方 |
| user_id_b | FK users | 接收方 |
| source_deal_id | FK deals | 建立好友关系的订单 |
| status | varchar | PENDING / ACCEPTED / REJECTED / BLOCKED |
| created_at | timestamp | |
| accepted_at | timestamp | |

#### 4.2.3 共享基础设施表（新建）

**payments**（支付记录）

| 字段 | 类型 | 说明 |
|------|------|------|
| payment_id | PK | |
| deal_id | FK deals | 关联订单 |
| user_id | FK users | 支付用户 |
| amount | decimal | 金额 |
| type | varchar | DEPOSIT / BALANCE / FULL / REFUND |
| status | varchar | PENDING / PAID / REFUNDED / FAILED |
| gateway | varchar | ALIPAY / WECHAT / MOCK |
| trade_no | varchar | 第三方交易号 |
| paid_at | timestamp | 支付时间 |
| refunded_at | timestamp | 退款时间 |
| metadata_ | JSONB | 扩展元数据 |

**notifications**（站内通知）

| 字段 | 类型 | 说明 |
|------|------|------|
| notification_id | PK | |
| user_id | FK users | 接收用户 |
| type | varchar | DEAL_CREATED / DEAL_CONFIRMED / ... |
| title | varchar | 标题 |
| body | text | 正文 |
| channels | JSONB | 已发送渠道 |
| read_at | timestamp | 已读时间 |
| created_at | timestamp | |

**notification_templates**（通知模板，可后台配置）

| 字段 | 类型 | 说明 |
|------|------|------|
| template_key | PK | 如 deal.created.student |
| event_type | varchar | 如 DEAL_CREATED |
| recipient_role | varchar | STUDENT / COACH / ADMIN |
| channels | JSONB | ["WS_PUSH","SMS"] |
| title_template | text | Jinja2 模板 |
| body_template | text | Jinja2 模板 |
| enabled | bool | |

**lbs_locations**（位置信息，PostGIS）

| 字段 | 类型 | 说明 |
|------|------|------|
| location_id | PK | |
| resource_id | FK resources | 教练资源 ID |
| location | geometry(Point,4326) | 地理坐标 |
| heading | float | 方向 |
| speed | float | 速度 |
| updated_at | timestamp | 最后上报时间 |

**files**（文件存储）

| 字段 | 类型 | 说明 |
|------|------|------|
| file_id | PK | |
| uploader_id | FK users | 上传者 |
| url | varchar | OSS URL |
| file_type | varchar | LICENSE / AVATAR / REVIEW / CONTRACT |
| biz_type | varchar | 业务类型 |
| biz_id | varchar | 业务 ID |
| size | bigint | 文件大小 |
| mime | varchar | MIME 类型 |
| created_at | timestamp | |

#### 4.2.4 规则配置表（新建）

**business_rules**（业务规则配置）

| 字段 | 类型 | 说明 |
|------|------|------|
| rule_key | PK | 如 escort.coach.level_config |
| rule_value | JSONB | 规则值 |
| description | text | 描述 |
| category | varchar | coach / match / cancel / payment / credit |
| version | int | 乐观锁版本号 |
| updated_by | FK users | 最后修改人 |
| updated_at | timestamp | |

**business_rule_history**（规则变更历史）

| 字段 | 类型 | 说明 |
|------|------|------|
| history_id | PK | |
| rule_key | FK business_rules | |
| old_value | JSONB | 旧值 |
| new_value | JSONB | 新值 |
| changed_by | FK users | 修改人 |
| changed_at | timestamp | |
| change_reason | text | 变更原因（可选） |

**credit_logs**（信用分变更日志）

| 字段 | 类型 | 说明 |
|------|------|------|
| log_id | PK | |
| user_id | FK users | |
| delta | int | 变更值（正/负） |
| reason | varchar | 变更原因 |
| deal_id | FK deals | 关联订单（可选） |
| created_at | timestamp | |

#### 4.2.5 核心表新增字段

**tasks 表新增字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| order_type | varchar | INSTANT / SCHEDULED |
| scheduled_at | timestamp | 预约单服务时间（实时单为空） |
| coach_level_pref | varchar | 学员等级偏好 BRONZE/SILVER/GOLD/PLATINUM/ANY |

**deals 表新增字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| deposit_amount | decimal | 定金金额 |
| deposit_status | varchar | UNPAID / PAID / REFUNDED / DEDUCTED |
| cancel_reason | text | 取消原因 |
| cancel_initiator | varchar | STUDENT / COACH / SYSTEM |

**users 表新增字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| credit_score | int | 信用分（默认 100） |

**DealStatus 枚举新增**

- `IN_SERVICE`：服务执行中（ACTIVE→IN_SERVICE→COMPLETED）

---

## 五、核心业务流程

### 5.1 下单分流

学员发布需求时选择订单类型：

- **实时单**：立即出发，下班约车开回家场景，秒级响应
- **预约单**：指定未来时间，提前规划，分钟级响应

### 5.2 实时单匹配流程（动态扩圈）

```
学员发布实时单
    ↓
[T+0s] 初始召回：附近 2km + 空闲 + 信任≥4.0 + 等级匹配
    ↓
派单给 Top1 教练，15秒等待
    ↓
┌─ 教练接单 → Deal 成立
│
├─ 15秒超时无响应
│   ↓
│  [T+15s] 扩圈召回：5km 范围
│   ↓
│  派单给 Top1，15秒等待
│   ↓
│  ┌─ 教练接单 → Deal 成立
│  ├─ 15秒超时
│  │   ↓
│  │  [T+30s] 扩圈召回：10km 范围
│  │   ↓
│  │  派单给 Top1，30秒等待
│  │   ↓
│  │  ┌─ 教练接单 → Deal 成立
│  │  └─ 30秒超时
│  │      ↓
│  │     [T+60s] 提示"附近暂无教练，是否继续等待/切换预约单"
│  │
└─ 教练拒绝 → 立即派给 Top2，流程同上
```

### 5.3 预约单匹配流程（Top3 推荐）

```
学员发布预约单（时间+地点+等级偏好）
    ↓
[InstantMatch 扩展]
- 召回：符合时间窗 + 服务区域 + 信任≥4.0 + 等级匹配
- 评分：EscortMatchScorer（技能/距离/信任/等级）
- 返回 Top3 候选（含评分理由）
    ↓
学员浏览 Top3 教练卡片（头像/评分/距离/时薪/评价）
    ↓
学员选择一位教练
    ↓
[创建 Deal]
- 状态：PENDING
- 学员支付定金（30%）
- 推送 WS 通知给教练
    ↓
教练确认/拒绝（30分钟超时）
    ↓
Deal.status: PENDING → ACTIVE (确认) / CANCELLED (拒绝/超时)
    ↓
预约成立通知（WS + 短信）
```

### 5.4 服务执行流程

```
到约定时间
    ↓
[签到] 教练触发 check_in
- 记录 lbs_locations
- Deal.status: ACTIVE → IN_SERVICE
    ↓
陪驾服务进行中（可选：实时位置追踪，每10秒上报）
    ↓
[签退] 教练触发 check_out
- 计算时长 duration_min
- Deal.status: IN_SERVICE → COMPLETED
    ↓
生成 escort_service_records
```

### 5.5 双向评价流程

```
Deal.status = COMPLETED
    ↓
┌────────────────────────────────┐
│  学员评价教练                   │
│  - teaching_ability (教学能力)  │
│  - patience (耐心程度)          │
│  - safety_record (安全记录)     │
└────────────────────────────────┘
┌────────────────────────────────┐
│  教练评价学员                   │
│  - punctuality (守时程度)       │
│  - cooperation (配合度)         │
│  - payment (付款及时性)         │
└────────────────────────────────┘
    ↓
[TrustEngine 双向更新]
- 教练 trust_profile（escort domain）
- 学员 trust_profile（escort domain）
    ↓
触发结算（Hourly 时薪 × 时长，平台抽成 20%）
```

### 5.6 社交延伸流程

```
评价完成后
    ↓
弹出"加好友"提示（双向，任一方可发起）
    ↓
发起好友请求
friendships.status = PENDING
推送 WS 通知对方
    ↓
对方接受/拒绝
    ↓
好友关系建立（跨业务通用）
    ↓
后续可直接预约好友教练（跳过匹配，可配置优惠）
```

### 5.7 教练等级体系

| 等级 | 时薪 | 信任分 | 完单量 | 注册时长 |
|------|------|--------|--------|---------|
| BRONZE 初级 | 60元/时 | ≥4.0 | ≥10 | ≥30天 |
| SILVER 中级 | 80元/时 | ≥4.3 | ≥50 | ≥90天 |
| GOLD 高级 | 120元/时 | ≥4.6 | ≥200 | ≥180天 |
| PLATINUM 金牌 | 200元/时 | ≥4.8 | ≥500 | ≥365天 |

- **升级规则**：信任分 + 完单量 + 注册时长 三项同时满足自动升级
- **降级规则**：信任分连续30天低于阈值自动降级
- **重算周期**：每24小时重算一次（定时任务）
- **等级参数可后台配置**

### 5.8 取消策略矩阵

| 场景 | 实时单 | 预约单 |
|------|--------|--------|
| 派单超时 | 自动取消，无惩罚 | N/A |
| 学员手动取消（服务前） | 派单后60秒内：无惩罚；60秒-5分钟：扣5信用分；>5分钟：扣10信用分 | 服务前≥24h：无惩罚；2-24h：扣10%押金+扣10信用；<2h：扣50%押金+扣20信用；<30分钟：扣全额定金+扣30信用 |
| 教练取消（服务前） | 扣20信用分，连续3次降级 | 扣30信用分 + 退还学员全额定金 + 赔偿学员10%订单金额，连续2次降级 |
| 服务中取消 | 进入争议流程（DISPUTED），运营介入判定 | 同左 |
| 系统取消 | 不可抗力：无惩罚；平台主动取消：通知双方+补偿券 | 同左 |

- **所有取消规则参数可后台配置**

### 5.9 押金/定金机制（预约单专属）

```
预约单支付流程：
学员下单 → 支付定金 30% → 教练确认 → 服务执行 → 结算（定金抵扣+尾款70%）→ 完成
                                                    ↓
                                              或取消时
                                                    ↓
                                              按取消策略扣除定金
                                                    ↓
                                              剩余定金退还

payments 表记录：
- type: DEPOSIT (定金) / BALANCE (尾款) / REFUND (退款)
- status: PENDING / PAID / REFUNDED / DEDUCTED
```

### 5.10 信用分体系

**信用分 vs 信任分**：
- `trust_score`：评价维度（教学/耐心/安全等），分 domain 隔离
- `credit_score`：行为维度（取消/违约/投诉等），全局共享

**信用分影响**：
- `credit_score < 60`：限制预约单（需全额预付）
- `credit_score < 40`：限制实时单（高峰期禁止）
- `credit_score < 20`：封号

**信用分规则可后台配置**。

### 5.11 Deal 状态机（陪驾扩展）

```
PENDING ──教练确认──► ACTIVE ──签到──► IN_SERVICE ──签退──► COMPLETED
   │                     │                                           ↑
   │                     │                                         评价
   └─教练拒绝──► CANCELLED                                       [终态]

争议分支:
IN_SERVICE ──任一方发起争议──► DISPUTED ──运营介入──► RESOLVED
                                                  └─► COMPLETED 或 CANCELLED
```

---

## 六、规则配置中心

### 6.1 架构

```
运营后台 UI → business_rules 表 → RuleConfig 服务（内存缓存）→ 业务代码读取
```

### 6.2 可配置规则清单

| rule_key | 说明 | category |
|----------|------|----------|
| escort.coach.level_config | 教练等级体系配置 | coach |
| escort.instant.expand_radius | 实时单动态扩圈参数 | match |
| escort.cancel.policy | 取消策略与信用扣减 | cancel |
| escort.payment.deposit_ratio | 预约单定金比例 | payment |
| escort.payment.commission_rate | 平台抽成比例 | payment |
| escort.trust.admission_threshold | 教练准入信任分阈值 | coach |
| escort.credit.score_rules | 信用分加减规则 | credit |
| escort.friend.discount_rate | 好友预约优惠比例 | payment |
| escort.coach.level_recalc_interval_hours | 等级重算周期 | coach |
| escort.match.top_n | 预约单推荐候选数量 | match |
| notification.templates | 通知模板配置 | notification |

### 6.3 RuleConfig 服务

```python
class RuleConfig:
    """规则配置服务（带内存缓存 + 变更订阅）"""
    
    def __init__(self, repo: RuleRepository):
        self._repo = repo
        self._cache: dict[str, Any] = {}
        self._lock = RLock()
    
    def get(self, key: str, default: Any = None) -> Any: ...
    def set(self, key: str, value: Any, updated_by: str) -> None: ...
    def reload(self) -> None: ...
    def subscribe(self, key: str, callback: Callable) -> None: ...
```

### 6.4 后台界面

运营后台 `/admin/rules/*`：
- 规则列表（按分类筛选）
- 规则编辑（JSON 编辑器 + 表单混合）
- 变更历史（支持回滚）

---

## 七、共享基础设施层

### 7.1 模块组织

```
umcp-core/src/umcp_core/shared/
├── payment/
│   ├── base.py              # PaymentGateway 抽象 + PaymentIntent
│   ├── alipay.py            # AlipayGateway
│   ├── wechat.py            # WechatPayGateway
│   ├── mock.py              # MockGateway（测试）
│   ├── repository.py        # PaymentRepository
│   └── service.py           # PaymentService
├── lbs/
│   ├── base.py              # LBSService 抽象
│   ├── postgis.py           # PostGIS 实现
│   ├── amap.py              # 高德地图 API 客户端
│   └── repository.py        # LocationRepository
├── notification/
│   ├── base.py              # NotificationChannel 抽象
│   ├── ws_channel.py        # WS 推送通道
│   ├── sms_channel.py       # 阿里云短信通道
│   ├── subscribe_channel.py # 小程序订阅消息通道
│   ├── center.py            # NotificationCenter
│   ├── template.py          # 模板渲染（Jinja2）
│   └── repository.py        # NotificationRepository
├── storage/
│   ├── base.py              # FileStorage 抽象
│   ├── oss.py               # OSS 实现
│   ├── local.py             # 本地存储（开发）
│   └── repository.py        # FileRepository
└── rules/
    ├── config.py            # RuleConfig
    ├── repository.py        # RuleRepository
    └── history.py           # 变更历史审计
```

### 7.2 支付网关

**抽象接口**：
- `create_payment(deal_id, amount, type) → PaymentIntent`
- `query_payment(trade_no) → PaymentStatus`
- `refund(trade_no, amount, reason) → RefundResult`
- `handle_callback(raw_data) → CallbackResult`
- `verify_signature(raw_data, signature) → bool`

**实现**：AlipayGateway / WechatPayGateway / MockGateway

**支付类型**：DEPOSIT（定金）/ BALANCE（尾款）/ FULL（全额）/ REFUND（退款）

### 7.3 LBS 定位服务

**存储层**：PostGIS（PG 扩展，复用现有 RDS），lbs_locations 表 geometry 列 + GIST 空间索引

**服务接口**：
- `update_location(resource_id, lat, lng) → None`
- `nearby_coaches(lat, lng, radius_km, level?) → List`
- `distance(lat1, lng1, lat2, lng2) → float`
- `geocode(address) / reverse_geocode(lat, lng)`

**前端集成**：高德地图 JS SDK（地图展示/定位/路径规划/实时轨迹）

### 7.4 消息通知中心

**通知渠道**：
- WS_PUSH（WebSocket 实时推送，umcp-core 已有）
- SMS（阿里云短信）
- SUBSCRIBE（微信小程序订阅消息）
- IN_APP（应用内消息中心）

**NotificationCenter**：
- `notify(user_id, event_type, channels, params)`
- `notify_both(student_id, coach_id, event_type, params)`

**事件→通知映射**（模板可后台配置）：
- DEAL_CREATED → 通知教练（WS+短信）
- DEAL_CONFIRMED → 通知学员（WS+短信）
- CHECK_IN_REMINDER → 通知双方（WS+订阅消息）
- REVIEW_REQUEST → 通知学员（WS+订阅消息）
- PAYMENT_PAID → 通知双方（WS）
- FRIEND_REQUEST → 通知对方（WS+订阅消息）

### 7.5 文件存储

**抽象接口**：
- `upload(file, biz_type, biz_id) → FileMeta`
- `download(file_id) → Stream`
- `get_signed_url(file_id, expire_sec) → str`
- `delete(file_id) → None`

**实现**：OSSStorage（阿里云 OSS）/ LocalStorage（开发）

**业务场景**：教练证件 / 头像 / 评价图片 / 服务轨迹截图 / 合同协议

### 7.6 与 umcp-core 集成

UMCPServer 扩展 `set_payment_gateway` / `set_lbs_service` / `set_notification_center` / `set_file_storage` / `set_rule_config` 方法，应用工厂自动装配。

---

## 八、前端架构

### 8.1 技术栈

| 维度 | 选型 | 理由 |
|------|------|------|
| 框架 | Next.js 14 (App Router) | React 生态最大，SSR/ISR 支持 |
| UI 库 | shadcn/ui + Tailwind CSS | 可定制、无运行时、体积小 |
| 状态管理 | Zustand + React Query | Zustand 客户端状态，React Query 服务端状态 |
| 表单 | React Hook Form + Zod | 类型安全校验 |
| 地图 | 高德地图 JS SDK | 国内体验最佳 |
| 支付 | 支付宝 JSAPI + 微信 JSAPI | 国内主流支付 |
| WebSocket | 原生 WebSocket + 重连封装 | umcp-core WS 已就绪 |
| 图表 | Recharts | 运营后台数据可视化 |
| 认证 | next-auth（JWT strategy） | 与 umcp-core JWT 对接 |

### 8.2 鉴权与路由守卫

`middleware.ts` 核心逻辑：
1. 未登录访问受保护路由 → 跳登录
2. 已登录访问身份层 → 跳首页
3. 角色校验（学员不能访问 /coach/*）
4. 管理员校验（非管理员不能访问 /admin/*）

### 8.3 API 客户端

- `ApiClient` 封装 fetch + JWT 拦截器
- 解析统一响应信封 `{"code":0,"data":...,"message":"ok"}`
- 401 自动跳登录，403/404/409/500 分别处理
- React Query 封装服务端状态管理

### 8.4 WebSocket 客户端

- 连接 `/api/v1/ws/events?token=<access_token>`
- 指数退避重连（最大 30 秒）
- 消息分发到 Zustand store
- 心跳保活（ping/pong）

---

## 九、部署架构

### 9.1 生产部署拓扑

```
Internet → CDN（静态资源）→ SLB（负载均衡 443/80）→ 
  ECS #1（Nginx + Next.js + FastAPI Docker）
  ECS #2（Nginx + Next.js + FastAPI Docker）
→ RDS PG（主从 + PostGIS）/ Redis（主从）/ OSS

外部服务：支付宝/微信支付 API / 阿里云短信 / 高德地图 API / 微信小程序订阅消息
```

### 9.2 环境配置

关键环境变量（完整清单见 `.env.example`）：

| 变量 | 说明 |
|------|------|
| UMCP_DB_DSN | PostgreSQL 连接串 |
| UMCP_DB_POOL_SIZE | 连接池大小（默认 20） |
| REDIS_URL | Redis 连接串 |
| UMCP_JWT_SECRET | JWT 密钥 |
| ALIPAY_APP_ID / ALIPAY_PRIVATE_KEY / ALIPAY_PUBLIC_KEY | 支付宝配置 |
| WECHAT_APP_ID / WECHAT_MCH_ID / WECHAT_API_KEY | 微信支付配置 |
| ALIYUN_SMS_ACCESS_KEY / ALIYUN_SMS_SECRET / ALIYUN_SMS_SIGN_NAME | 短信配置 |
| OSS_ACCESS_KEY / OSS_SECRET / OSS_BUCKET / OSS_ENDPOINT | OSS 配置 |
| AMAP_SERVER_KEY / NEXT_PUBLIC_AMAP_KEY | 高德地图配置 |

### 9.3 Docker Compose 生产配置

- `app` 服务：构建 Next.js + FastAPI 镜像，2 副本水平扩展
- `nginx` 服务：SSL 终止 + 反向代理
- `postgres` 服务：postgis/postgis:16-3.4 镜像（含 PostGIS）
- `redis` 服务：redis:7-alpine

---

## 十、错误处理与可观测性

### 10.1 错误处理分层

- **前端层**：Next.js error.tsx 全局错误边界 + React Query onError + WebSocket onError
- **API 客户端层**：解析统一响应信封，按 code 分流处理
- **后端层**：FastAPI 异常处理器（umcp-core 已有 + 扩展共享层错误）
- **共享层错误**：PaymentError / LBSError / NotificationError / StorageError / RuleConfigError

### 10.2 错误码规范

| 范围 | 类别 |
|------|------|
| 0 | 成功 |
| 1xxx | 认证类 |
| 2xxx | 用户类 |
| 3xxx | 交易类 |
| 4xxx | 支付类 |
| 5xxx | 匹配类 |
| 6xxx | 信用类 |
| 9xxx | 系统类 |

### 10.3 可观测性三支柱

**Metrics**（umcp-core 已有 Prometheus，扩展业务指标）：
- http_requests_total / http_request_duration_seconds（已有）
- escort_orders_total / escort_match_duration_seconds / escort_match_success_rate（新增）
- payment_amount_total / escort_active_coaches / escort_realtime_wait_seconds（新增）

**Logs**（umcp-core 已有 logging.conf，扩展结构化）：
- JSON 结构化日志，含 request_id / user_id / deal_id / event_type
- Logger：umcp_core.escort / umcp_core.payment / umcp_core.lbs

**Tracing**（新增，可选）：
- OpenTelemetry SDK
- FastAPI middleware 自动埋点
- 数据库查询 span
- 第三方调用 span
- 导出到 Jaeger / 阿里云链路追踪

### 10.4 告警规则

- 5xx 错误率 > 1% → 告警
- 匹配成功率 < 80% → 告警
- 支付失败率 > 5% → 告警
- 平均等待时长 > 60秒 → 告警
- RDS CPU > 80% / Redis 内存 > 80% → 告警
- 通知渠道：钉钉机器人 / 短信

---

## 十一、安全考量

### 11.1 认证授权

- JWT access + refresh（umcp-core 已有）
- Token 吊销黑名单（umcp-core 已有）
- 路由守卫前端 + 后端双重校验
- RBAC 角色权限（STUDENT / COACH / ADMIN / PLATFORM_ADMIN）
- 操作频率限制（Redis + 滑动窗口）：登录 5次/分钟、发单 10次/分钟、评价 1次/订单、好友请求 20次/天

### 11.2 数据安全

- 密码哈希（bcrypt）
- 敏感数据加密存储（手机号/身份证号 AES 加密）
- 数据库定期备份（RDS 自动备份 + 跨可用区）
- OSS 私有桶 + 临时签名 URL
- SQL 注入防护（SQLAlchemy ORM 参数化）

### 11.3 传输安全

- HTTPS 强制（Nginx SSL）+ HSTS 头
- CSRF 防护（SameSite Cookie）
- XSS 防护（CSP 头 + React 转义）

### 11.4 支付安全

- 支付回调签名校验（支付宝/微信 RSA 签名）
- 幂等性处理（同一 trade_no 不重复处理）
- 金额服务端计算（不信任前端金额）
- 大额支付短信验证码二次验证

### 11.5 业务安全

- 防刷单（频繁取消 → 信用扣分）
- 防刷评价（只有完成订单才能评价）
- 防恶意加好友（频率限制 + 拉黑机制）
- 防位置伪造（服务端校验教练位置合理性）

---

## 十二、测试策略

### 12.1 测试金字塔

```
        /\          E2E 测试（10%）：Playwright 端到端
       /  \         
      /----\        集成测试（30%）：API + DB + 共享层 + WebSocket
     /      \       
    /--------\      单元测试（60%）：业务逻辑/状态机/规则/匹配算法/组件
   /          \     
  /------------\    
```

### 12.2 后端测试（扩展现有 pytest 体系）

| 测试类型 | 覆盖范围 | 工具 |
|---------|---------|------|
| 单元测试 | 等级计算/信用分/取消策略/匹配算法 | pytest（已有） |
| 集成测试 | API 端点/数据库/事件链路 | pytest + TestClient（已有） |
| 支付测试 | 支付流程/回调/退款/幂等 | MockGateway |
| LBS 测试 | 附近查询/距离计算/扩圈 | PostGIS + 测试数据 |
| 规则配置 | 读取/更新/缓存失效/历史回滚 | pytest + RuleConfig |
| E2E 测试 | 完整业务闭环 | pytest + TestClient |

### 12.3 前端测试

| 测试类型 | 覆盖范围 | 工具 |
|---------|---------|------|
| 单元测试 | 组件渲染/hooks/工具函数 | Vitest + React Testing Library |
| 集成测试 | 页面交互/表单/路由守卫 | Vitest + MSW（Mock API） |
| E2E 测试 | 下单/支付/评价全流程 | Playwright |

### 12.4 关键 E2E 场景

1. 实时单全流程：教练上线 → 学员发实时单 → 系统派单 → 教练接单 → 签到 → 签退 → 双向评价 → 支付 → 完成
2. 预约单全流程：学员发预约单 → Top3 推荐 → 学员选择 → 教练确认 → 定金支付 → 服务执行 → 尾款支付 → 评价 → 加好友
3. 取消与退款：预约单支付定金 → 学员取消（按时间窗）→ 定金扣除 → 退款
4. 争议处理：服务中争议 → 提交争议 → 运营介入 → 判定 → 退款/完成
5. 信用分影响：学员多次取消 → 信用分下降 → 触发限制 → 恢复路径
6. 教练等级升级：完成订单 → 信任分提升 → 达到阈值 → 自动升级 → 时薪调整
7. 好友预约：完成订单 → 加好友 → 好友预约 → 优惠应用

---

## 十三、性能优化

### 13.1 数据库

- PostGIS 空间索引（GIST）加速附近查询
- 读写分离（RDS 主从，读走从库）
- 慢查询监控 + 索引优化
- 分页查询（cursor-based，避免 OFFSET）

### 13.2 缓存（Redis）

- 教练位置缓存（ZSET，按地理位置排序）
- 教练资料缓存（Hash，TTL 5分钟）
- 规则配置缓存（RuleConfig 已有）
- 热门教练评价缓存
- 用户会话缓存

### 13.3 应用层

- Next.js ISR（教练详情页增量静态生成）
- React Query 缓存（订单列表 staleTime 30秒）
- WebSocket 心跳保活（减少重连）
- 图片懒加载 + OSS 缩略图

### 13.4 前端

- 代码分割（按路由）
- Tree shaking
- 图片优化（next/image + WebP）
- Bundle 分析监控

---

## 十四、已知限制与未来扩展

### 14.1 已知限制

- MVP 仅陪驾业务，打车/集采为未来扩展
- 支付仅支持支付宝/微信，未支持银行卡/余额
- LBS 基于高德，未支持百度/腾讯地图切换
- 通知仅支持短信/WS/订阅消息，未支持邮件/Push
- 单实例部署（2 ECS 副本），未实现自动伸缩
- 未实现读写分离（RDS 主从仅备份用）
- 未实现分布式追踪（OpenTelemetry 可选）
- 未实现 A/B 测试框架

### 14.2 未来扩展路径

**多业务扩展**：
- 新增业务只需：注册新插件 + 新增路由分区 + 新增数据库表前缀
- 共享层（认证/支付/LBS/通知/存储/规则）一次建设多业务复用

**技术演进**：
- 模块化单体 → 微服务（当单业务负载过高时拆分）
- 单 RDS → 读写分离 → 分库分表（按用户 ID 哈希）
- Redis 单机 → Redis Cluster
- 单 ECS → K8s + HPA（自动伸缩）

**业务演进**：
- 打车业务（ride_hailing）：复用 LBS/支付/通知/认证
- 集采业务（group_buying）：复用支付/通知/认证，新增招标流程
- 跨业务 CompositeTask 编排（umcp-core 已支持）

---

## 十五、实施建议

### 15.1 建议实施顺序

1. **基础设施层**：数据库迁移 + 共享层骨架（payment/lbs/notification/storage/rules）
2. **后端业务层**：陪驾插件扩展（Top3 推荐）+ 陪驾 router + 规则配置
3. **前端基础**：项目搭建 + 共享身份层 + 路由守卫
4. **前端学员端**：下单（实时/预约）+ 订单管理 + 评价
5. **前端教练端**：接单 + 服务执行 + 评价学员
6. **支付集成**：支付宝/微信网关 + 定金/尾款流程
7. **LBS 集成**：PostGIS + 高德地图 + 实时定位
8. **通知集成**：短信 + 订阅消息 + WS 推送联调
9. **运营后台**：规则配置中心 + 教练审核 + 订单监控 + 争议处理
10. **社交功能**：好友关系 + 好友预约
11. **信用/等级**：信用分计算 + 教练等级自动升降
12. **测试与部署**：E2E 测试 + 生产部署 + 监控告警

### 15.2 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 支付集成复杂度 | 高 | 先用 MockGateway 跑通流程，再接入真实网关 |
| LBS 精度问题 | 中 | 高德 SDK + 服务端校验，异常位置丢弃 |
| 实时单匹配延迟 | 高 | 动态扩圈 + Redis 位置缓存 + 异步派单 |
| 规则配置错误 | 中 | 配置校验 + 历史回滚 + 灰度发布 |
| 信用分计算争议 | 中 | 规则透明化 + 用户可查看 + 申诉流程 |

---

**文档结束**
