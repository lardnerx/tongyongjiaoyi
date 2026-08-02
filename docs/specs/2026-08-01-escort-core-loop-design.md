# 陪驾业务核心闭环（阶段三）设计规格

**版本**：1.0.0
**创建日期**：2026-08-01
**适用范围**：在阶段二前端基础之上，实现学员端+教练端核心闭环（下单→接单→签到→签退→评价）
**前置依赖**：阶段二前端基础已完成（登录/路由守卫/API 客户端/WS 客户端），阶段一后端陪驾插件+router 已完成

---

## 一、概述

### 1.1 阶段目标

在已完成的登录认证、路由守卫、API/WS 客户端基础上，实现陪驾业务的完整端到端闭环：

- **实时单全流程**：学员发单 → 教练抢单 → 签到 → 签退 → 双向评价
- **预约单全流程**：学员发单 → Top3 推荐 → 选教练 → Mock 支付定金 → 教练确认 → 签到 → 签退 → 双向评价
- **角色动态切换**：同一用户可在学员/教练身份间切换，看到不同页面

### 1.2 核心决策汇总

| 决策项 | 采纳方案 | 理由 |
|--------|---------|------|
| 范围 | 学员端+教练端+评价，完整闭环 | 端到端可验证，不留半成品 |
| 地图 | 高德地图 JS SDK | 国内体验最佳，选点/定位/展示 |
| 支付 | Mock 支付 | 闭环可验证，后续替换真实网关 |
| 角色切换 | 动态切换（active_role） | 一个账号可同时是学员和教练 |
| 实时单匹配 | 抢单模式 | 学员发单后 WS 广播给在线教练，教练抢单竞争 |
| 实现策略 | 垂直切片 | 切片1=实时单，切片2=预约单，每片可独立验证 |

### 1.3 不在本阶段范围

- 动态扩圈（2km→5km→10km 自动扩圈）— 留待后续优化
- 真实支付宝/微信支付接入 — Mock 支付替代
- 好友关系 + 好友预约 — 留待阶段四
- 信用分计算 + 教练等级自动升降 — 留待阶段四
- 运营后台 UI — 留待阶段五
- 短信/订阅消息通知 — 仅 WS 推送

---

## 二、整体架构

### 2.1 前端路由结构（阶段三新增）

```
web/src/app/
├── (auth)/login/                    # 已有
├── (protected)/
│   ├── dashboard/                   # 改造：角色切换入口
│   │   └── page.tsx
│   └── escort/                      # 新增：陪驾业务路由组
│       ├── student/                 # 学员端（active_role=demander）
│       │   ├── book-instant/        # 实时单下单（地图选点+等级偏好）
│       │   ├── book-scheduled/      # 预约单下单（时间+地点+Top3+Mock支付）
│       │   ├── orders/              # 订单列表（按状态筛选）
│       │   │   └── [id]/            # 订单详情（状态追踪+评价入口）
│       │   └── coaches/             # 教练列表（浏览，预留）
│       └── coach/                   # 教练端（active_role=supplier）
│           ├── page.tsx             # 接单大厅（WS 实时推送+抢单）
│           ├── orders/              # 我的订单
│           │   └── [id]/            # 订单详情（签到/签退+评价学员）
│           └── profile/             # 教练资料（出车/收车，预留）
```

### 2.2 角色守卫增强

middleware.ts 扩展：
- 读取 `active-role` cookie
- 学员（demander）不能访问 `/escort/coach/*`
- 教练（supplier）不能访问 `/escort/student/*`
- dashboard 页面提供角色切换功能，切换时写入 cookie 并刷新

### 2.3 状态管理分层

```
┌─────────────────────────────────────────────────┐
│  React Query（服务端状态，缓存+失效）             │
│  - 订单列表 useQuery (staleTime=30s)             │
│  - 订单详情 useQuery (WS 事件触发 refetch)        │
│  - Top3 候选 useQuery (enabled=预约单)           │
├─────────────────────────────────────────────────┤
│  Zustand store（客户端状态，WS 实时同步）         │
│  - useOrderRealtimeStore: WS 事件→订单状态更新   │
│  - useAuthStore (已有，扩展): switchRole+activeRole │
└─────────────────────────────────────────────────┘
```

---

## 三、后端 API 扩展

### 3.1 API 端点清单

| 端点 | 方法 | 说明 | 状态 |
|------|------|------|------|
| `/api/v1/escort/orders` | POST | 学员下单（实时/预约） | 已有，需扩展广播 |
| `/api/v1/escort/orders?demander_id=` | GET | 学员订单列表 | 已有 |
| `/api/v1/escort/orders/{task_id}` | GET | 订单详情 | 已有 |
| `/api/v1/escort/orders/{task_id}/cancel` | POST | 学员取消 | 已有 |
| `/api/v1/escort/orders/{task_id}/claim` | POST | **新增**：教练抢单 | 待实现 |
| `/api/v1/escort/orders/{task_id}/select-coach` | POST | **新增**：预约单学员选教练 | 待实现 |
| `/api/v1/escort/coaches/{coach_id}/online` | POST | **新增**：教练上线 | 待实现 |
| `/api/v1/escort/coaches/{coach_id}/offline` | POST | **新增**：教练下线 | 待实现 |
| `/api/v1/escort/orders/{task_id}/check-in` | POST | 教练签到 | 已有 |
| `/api/v1/escort/orders/{task_id}/check-out` | POST | 教练签退 | 已有 |
| `/api/v1/escort/orders/{task_id}/reviews` | POST | **新增**：提交评价 | 待实现 |
| `/api/v1/escort/orders/{task_id}/reviews` | GET | **新增**：查询评价 | 待实现 |
| `/api/v1/escort/deals/{deal_id}/confirm` | POST | **新增**：教练确认预约单 | 待实现 |
| `/api/v1/escort/deals/{deal_id}/reject` | POST | **新增**：教练拒绝预约单 | 待实现 |
| `/api/v1/escort/deals/{deal_id}` | GET | **新增**：查询 Deal | 待实现 |
| `/api/v1/escort/payments/mock-pay` | POST | **新增**：Mock 支付 | 待实现 |
| `/api/v1/escort/payments/{deal_id}` | GET | **新增**：查询支付状态 | 待实现 |
| `/api/v1/auth/switch-role` | POST | **新增**：切换角色 | 待实现 |

### 3.2 实时单抢单流程

```
1. 学员 POST /orders (order_type=REALTIME)
   后端：task.save + publish
         + 手动广播 "order.published" 给所有在线教练
   响应：{task_id, status: "PUBLISHED"}

2. 教练端 WS 收到 "order.published" → 接单大厅新增订单卡片
   教练 POST /orders/{task_id}/claim
   后端：校验 task.status==PUBLISHED
        → task.assign_to(coach_id) + task.start_execution()
        → publish TASK_ASSIGNED + TASK_CLAIMED 事件
        → WS 推送 "task.assigned" 给学员（payload.demander_id）
        → WS 推送 "task.claimed" 给其他在线教练（广播，移除该订单）
   响应：{task_id, status: "ACTIVE"} 或错误（已被抢）

3. 学员端 WS 收到 "task.assigned" → 订单状态 ACTIVE，显示教练信息

4. 教练 POST /orders/{task_id}/check-in
   后端：task.status ACTIVE→IN_SERVICE
        → WS 推送 "task.in_service" 给学员

5. 教练 POST /orders/{task_id}/check-out
   后端：task.status IN_SERVICE→COMPLETED
        → WS 推送 "task.completed" 给双方

6. 双方 POST /orders/{task_id}/reviews
   后端：写入 escort_reviews + 更新 trust_profile
```

### 3.3 预约单流程

```
1. 学员 POST /orders (order_type=SCHEDULED, scheduled_at, coach_level_pref)
   后端：ScheduledMatchStrategy.execute → 返回 Top3 候选 resource_ids
   响应：{task_id, candidates: ["res_1","res_2","res_3"]}

2. 学员 POST /orders/{task_id}/select-coach {resource_id}
   后端：task.assign_to(resource_id)
        → 创建 Deal(PENDING, deposit_amount=时薪*时长*30%)
        → WS 推送 "deal.created" 给教练（payload.supplier_id）
   响应：{deal_id, deposit_amount}

3. 学员 POST /payments/mock-pay {deal_id, type: DEPOSIT}
   后端：MockGateway.create_payment
        → Deal.deposit_status=PAID
        → WS 推送 "deal.paid" 给教练

4. 教练 POST /deals/{deal_id}/confirm
   后端：Deal.status PENDING→ACTIVE
        → WS 推送 "deal.confirmed" 给学员
   （或 POST /deals/{deal_id}/reject → CANCELLED + 退款 + WS "deal.cancelled"）

5-7. 同实时单的签到→签退→评价
```

### 3.4 评价规则

**学员评教练（reviewer_role=STUDENT）3 维：**
- teaching_score（教学能力，1-5）
- patience_score（耐心程度，1-5）
- safety_score（安全记录，1-5）

**教练评学员（reviewer_role=COACH）3 维：**
- punctuality_score（守时程度，1-5）
- cooperation_score（配合度，1-5）
- payment_score（付款及时性，1-5）

**校验规则：**
- task.status 必须为 COMPLETED
- 同一订单同一 reviewer_role 不可重复评价
- 评价写入后调用 `trust_engine.update_profile()` 更新双方 trust_profile

---

## 四、WS 推送扩展

### 4.1 现有机制

- `ConnectionManager` 按 user_id 维护连接，`send_to_user(uid, message)` 定向推送
- `make_ws_event_bridge` 订阅 EventBus，自动推送 `WS_PUSHABLE_EVENTS` 中的事件
- `_extract_user_ids` 从 event.payload 提取 `demander_id`/`supplier_id`/`user_id` 作为推送目标

### 4.2 扩展：教练广播

**问题：** `TASK_PUBLISHED` 事件 payload 只含 `demander_id`（学员），按现有逻辑教练收不到新订单通知。

**解决方案：**
1. `ConnectionManager` 新增 `broadcast_to_online_coaches(message)` 方法
2. 维护在线教练 user_id 集合（教练调用 `/coaches/{id}/online` 时加入，`/offline` 时移除）
3. `routers/escort/orders.py` 的 `create_order` 实时单分支：publish 后手动调用广播 `order.published` 给所有在线教练
4. 教练抢单成功后，广播 `task.claimed` 给其他在线教练（通知移除该订单）

### 4.3 新增 EventType

- `TASK_CLAIMED` - 教练抢单成功（广播给其他教练）
- `TASK_IN_SERVICE` - 签到，服务开始
- `DEAL_CONFIRMED` - 教练确认预约单
- `DEAL_REJECTED` - 教练拒绝预约单

加入 `WS_PUSHABLE_EVENTS` 集合。

### 4.4 WS 事件 → 前端动作映射

| WS 事件类型 | 前端动作 | 受影响页面 |
|------------|---------|-----------|
| `task.published` | 教练端：新增订单卡片 | 接单大厅 |
| `task.assigned` | 学员端：订单→ACTIVE | 学员订单详情 |
| `task.assigned` | 教练端：移除该订单 | 接单大厅 |
| `task.claimed` | 教练端：移除该订单（被抢） | 接单大厅 |
| `task.in_service` | 学员端：订单→IN_SERVICE | 学员订单详情 |
| `task.completed` | 双方：订单→COMPLETED，开放评价 | 订单详情 |
| `task.cancelled` | 双方：订单→CANCELLED | 订单详情 |
| `deal.created` | 学员端：提示支付定金 | 学员订单详情 |
| `deal.paid` | 教练端：提示确认 | 教练订单详情 |
| `deal.confirmed` | 学员端：预约成立 | 学员订单详情 |
| `deal.rejected` | 学员端：预约失败+退款 | 学员订单详情 |

### 4.5 WS 连接生命周期

- 登录成功后建立 WS 连接（已有 `WSClient`）
- 组件挂载时 `ws.on(eventType, handler)` 注册，卸载时 `ws.off` 清理
- 角色切换时不重连 WS（同一 token），只切换前端路由和事件订阅

---

## 五、前端组件设计

### 5.1 新增组件

**`components/amap-picker.tsx`** - 高德地图选点组件
- 动态加载高德 JS SDK（`NEXT_PUBLIC_AMAP_KEY`）
- 地图实例 + 标记 + 点击选点 + 逆地理编码（经纬度→地址）
- 受控组件：`value={lat,lng}` / `onChange={lat,lng,address}`

**`components/coach-card.tsx`** - 教练卡片
- 头像 / 等级徽章 / 综合评分 / 距离 / 时薪 / 评价数
- 用于 Top3 候选展示和教练列表

**`components/mock-payment.tsx`** - Mock 支付弹窗
- 金额展示 + "模拟支付"按钮 + 成功动画
- 调用 `/payments/mock-pay` 接口

**`components/order-status-badge.tsx`** - 订单状态徽章
- PUBLISHED/ACTIVE/IN_SERVICE/COMPLETED/CANCELLED 不同颜色

**`components/review-form.tsx`** - 评价表单
- 根据 reviewer_role 显示不同维度（学员3维/教练3维）
- 星级评分 + 文字评价

### 5.2 新增 Hooks

**`hooks/use-ws-events.ts`** - WS 事件订阅封装
- `useWsEvent(eventType, handler)` 自动 on/off + 清理
- 内部使用 `WSClient` 单例

**`hooks/use-orders.ts`** - 订单查询 hooks（React Query）
- `useOrders(demander_id)` / `useOrder(task_id)` / `useCoachOrders(coach_id)`
- WS 事件触发 `queryClient.invalidateQueries`

### 5.3 新增 Store

**`lib/order-realtime-store.ts`** - 订单实时状态
- `activeOrders: Map<task_id, Order>`
- WS 事件 → 更新对应订单状态
- 触发 React Query 失效

**扩展 `lib/auth-store.ts`**：
- `activeRole: string | null` 字段
- `switchRole(role)` 方法：调后端 `/auth/switch-role` + 同步 `active-role` cookie

### 5.4 高德地图集成

**环境变量：**
- `NEXT_PUBLIC_AMAP_KEY` - 高德 JS SDK key（前端）
- `AMAP_SERVER_KEY` - 服务端 key（逆地理编码，可选）

**SDK 加载策略：**
- `components/amap-picker.tsx` 动态 `script` 标签加载
- 全局 `_AMapSecurityConfig` 配置安全密钥
- 加载完成后初始化地图实例

---

## 六、任务分解

### 6.1 切片1：实时单全流程

**后端任务：**

1. **扩展 EventType + WS_PUSHABLE_EVENTS**
   - 新增 TASK_CLAIMED / TASK_IN_SERVICE / DEAL_CONFIRMED / DEAL_REJECTED
   - 加入 WS_PUSHABLE_EVENTS 集合

2. **扩展 ConnectionManager 广播能力**
   - 新增 `broadcast_to_online_coaches(message)` 方法
   - 维护在线教练 user_id 集合（register_online_coach / unregister_online_coach）

3. **扩展 orders.py：抢单接口 + 广播**
   - `create_order` 实时单分支：publish 后广播 `order.published` 给在线教练
   - 新增 `POST /orders/{task_id}/claim`：校验 PUBLISHED → assign_to → start_execution → publish 事件

4. **扩展 coaches.py：上线/下线接口**
   - `POST /coaches/{coach_id}/online`：注册 CoachResource + 加入在线教练集合
   - `POST /coaches/{coach_id}/offline`：下线 CoachResource + 移除在线教练集合

5. **新增 reviews.py：评价 router**
   - `POST /orders/{task_id}/reviews`：校验 COMPLETED + 未重复 + 写入 escort_reviews + 更新 trust_profile
   - `GET /orders/{task_id}/reviews`：查询订单评价

6. **扩展 auth.py：角色切换**
   - `POST /auth/switch-role`：校验 roles 包含目标角色 + 更新 user.active_role + 返回新 token

**前端任务：**

7. **扩展 auth-store + middleware 角色守卫**
   - auth-store: switchRole + activeRole + cookie 同步
   - middleware: active-role cookie 读取 + 角色路径校验

8. **改造 dashboard：角色切换入口**
   - 角色切换按钮 + 学员/教练入口卡片

9. **新增 order-realtime-store + use-ws-events hook**
   - Zustand store: WS 事件 → 订单状态
   - useWsEvent hook: 自动 on/off

10. **新增 amap-picker 组件**
    - 高德 JS SDK 动态加载 + 地图选点 + 逆地理编码

11. **新增学员端实时单下单页**
    - `escort/student/book-instant/page.tsx`：地图选点 + 等级偏好 + 下单表单

12. **新增学员端订单列表 + 详情**
    - `orders/page.tsx`：按状态筛选 Tab + React Query
    - `orders/[id]/page.tsx`：状态追踪 + WS 实时 + 评价表单

13. **新增教练端接单大厅**
    - `coach/page.tsx`：WS 实时推送订单卡片 + 抢单按钮

14. **新增教练端订单列表 + 详情**
    - `coach/orders/page.tsx`：我的订单
    - `coach/orders/[id]/page.tsx`：签到/签退 + 评价学员

15. **切片1端到端验证**
    - 启动后端+前端 → 模拟学员+教练两端 → 走完整实时单流程

### 6.2 切片2：预约单全流程

**后端任务：**

16. **扩展 orders.py：选教练接口**
    - `POST /orders/{task_id}/select-coach`：assign_to + 创建 Deal(PENDING)

17. **新增 deals.py：Deal router**
    - `POST /deals/{deal_id}/confirm`：PENDING→ACTIVE
    - `POST /deals/{deal_id}/reject`：PENDING→CANCELLED + 退款
    - `GET /deals/{deal_id}`：查询 Deal

18. **新增 payments.py：Mock 支付**
    - `POST /payments/mock-pay`：MockGateway + 更新 Deal.deposit_status
    - `GET /payments/{deal_id}`：查询支付状态

**前端任务：**

19. **新增学员端预约单下单页**
    - `book-scheduled/page.tsx`：时间+地点+等级 → Top3 → 选教练 → Mock 支付 → 等待确认

20. **扩展学员端订单详情：预约单分支**
    - PENDING→待付定金/待确认 → ACTIVE → IN_SERVICE → COMPLETED

21. **扩展教练端订单详情：预约单分支**
    - 待确认 Deal + 确认/拒绝按钮

22. **新增 coach-card + mock-payment 组件**
    - coach-card: Top3 候选展示
    - mock-payment: Mock 支付弹窗

23. **切片2端到端验证**
    - 启动后端+前端 → 走完整预约单流程

---

## 七、测试策略

### 7.1 后端测试

每个新 router 用 TestClient 测试：
- happy path（正常流程）
- 错误分支（抢单竞争、重复评价、状态非法转移、未授权访问等）
- WS 推送验证（mock ConnectionManager 验证推送调用）

### 7.2 前端测试

- Vitest 测试 store/hook 逻辑（order-realtime-store、use-ws-events）
- MSW mock API 测试页面交互（下单、抢单、评价）
- 组件单元测试（amap-picker mock、coach-card、review-form）

### 7.3 端到端验证

每个切片完成后用浏览器子代理验证：
- 启动后端（加载 escort 插件）+ 前端
- 模拟学员+教练两端（两个浏览器窗口或两次登录）
- 走完整流程，验证状态流转和 WS 实时推送

---

## 八、技术债与限制

1. **高德地图 key**：MVP 阶段用测试 key，生产前替换为正式 key
2. **Mock 支付**：不校验签名，生产前替换为真实支付宝/微信网关
3. **教练抢单竞争**：用乐观锁（task 状态校验）+ 先到先得，无分布式锁（单实例够用）
4. **WS 广播在线教练列表**：存内存，单实例够用，多实例需 Redis pub/sub
5. **动态扩圈**：本阶段不实现，留待后续优化
6. **评价防刷**：仅校验订单状态+重复评价，无频率限制（留待后续）

---

**文档结束**
