# 陪驾业务测试执行计划

> 项目：UMCP 通用市场交易协调引擎
> 版本：v2.0.0
> 日期：2026-08-15
> 模式：Mock 支付（开发环境）

---

## 测试环境

| 项目 | 说明 |
|------|------|
| 服务地址 | http://localhost:8000 |
| API 前缀 | `/api/v1` |
| 支付网关 | MockGateway（模拟支付） |
| 短信通道 | 开发模式（控制台输出） |
| 限流策略 | 60s 窗口 / 100 次/IP |
| 数据存储 | 内存仓储（重启后数据清空） |

---

## 一、用户认证（3 个场景）

### TC-01 用户注册与登录
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 学员注册 | `POST /auth/register` `{phone, name, role: "demander"}` | 200，返回 `access_token` + `refresh_token` |
| 2 | 教练注册 | `POST /auth/register` `{phone, name, role: "supplier"}` | 200，返回 `access_token` + `refresh_token` |
| 3 | 角色切换 | `POST /auth/switch-role` `{role: "supplier"}` | 200，返回新 token 含 `supplier` 角色 |
| 4 | 获取用户信息 | `GET /auth/me` | 200，返回用户详情含角色列表 |

### TC-02 未认证访问
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 无 token 请求 | `GET /auth/me` | 401 `Unauthorized` |
| 2 | 无效 token 请求 | `GET /auth/me` `Authorization: Bearer invalid` | 401 `Unauthorized` |

### TC-03 Token 刷新
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 使用 refresh_token | `POST /auth/refresh` `{refresh_token}` | 200，返回新 `access_token` |
| 2 | 过期 access_token | 等待 TTL 过期后请求 | 401 |

---

## 二、陪驾订单（5 个场景）

### TC-04 发布实时单
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 发布实时陪驾需求 | `POST /escort/orders` `{order_type: "REALTIME", origin_lat, origin_lng, car_type, duration_hours}` | 200，返回 `task_id` + `candidates`（附近教练列表） |
| 2 | 查询订单详情 | `GET /escort/orders/{task_id}` | 200，任务状态为 `published` |
| 3 | 列出附近教练 | `GET /lbs/nearby?lat=...&lng=...&domain=escort` | 200，返回空闲教练列表 |

### TC-05 发布预约单
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 发布预约陪驾需求 | `POST /escort/orders` `{order_type: "SCHEDULED", scheduled_at, origin_lat, origin_lng, car_type, duration_hours}` | 200，返回 `task_id` + `candidates` |
| 2 | 查看任务状态 | `GET /escort/orders/{task_id}` | 200，任务状态为 `published` |
| 3 | 选择教练 | `POST /escort/orders/{task_id}/select-coach` `{resource_id}` | 200，返回 `deal_id` + `deposit_amount` |

### TC-06 教练接单（实时单）
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 教练抢单 | `POST /escort/orders/{task_id}/claim` | 200，返回 `deal_id` |
| 2 | 查询 Deal | `GET /deals/{deal_id}` | 200，状态为 `pending` |
| 3 | 查询任务 | `GET /escort/orders/{task_id}` | 200，任务状态为 `assigned` |

### TC-07 取消订单
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 学员取消订单 | `POST /escort/orders/{task_id}/cancel` | 200，任务状态 `cancelled` |
| 2 | 查询取消规则 | `GET /escort/cancel-rules` | 200，返回违约金阶梯规则 |
| 3 | 验证重复取消 | 再次请求取消 | 400/409 幂等错误 |

### TC-08 实时单超时自动取消
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 发布实时单 | `POST /escort/orders` `{order_type: "REALTIME"}` | 200 |
| 2 | 等待超时（60s） | 等待 RealtimeCancelWorker 触发 | 任务状态自动变为 `cancelled` |
| 3 | 验证状态 | `GET /escort/orders/{task_id}` | 200，状态为 `cancelled` |

---

## 三、支付流程（5 个场景）

### TC-09 创建支付订单
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 创建支付 | `POST /escort/payments/create` `{deal_id, payment_type: "deposit"}` | 200，返回 `payment_id` + `status: "paid"`（Mock 模式自动确认） |
| 2 | 查询支付状态 | `GET /escort/payments/{deal_id}` | 200，返回支付记录详情 |

### TC-10 支付超时自动关闭
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 创建支付（Mock 自动确认） | 同 TC-09 | 200 |
| 2 | 关闭支付 | `POST /escort/payments/{payment_id}/close` | 200，`closed: true` |
| 3 | 验证关闭后状态 | 再次查询支付 | 200，状态为 `failed` |

### TC-11 支付超时流程
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | Mock 支付 | `POST /escort/payments/mock-pay` `{deal_id, payment_type: "deposit"}` | 200，状态 `paid` |
| 2 | 手动触发超时 | `POST /escort/payments/{deal_id}/timeout` | 200，deal → `cancelled`，task → `cancelled`，payment → `refunded` |
| 3 | 验证重复超时 | 再次请求 timeout | 400/409 幂等错误 |

### TC-12 关闭订单
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 创建支付 | `POST /escort/payments/create` | 200 |
| 2 | 关闭未支付订单 | `POST /escort/payments/{payment_id}/close` | 200，`closed: true` |
| 3 | 关闭已关闭订单 | 再次请求 close | 200，`closed: false`（非 pending 状态跳过） |

---

## 四、教练确认与执行（4 个场景）

### TC-13 教练确认接单
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 教练确认 Deal | `POST /escort/deals/{deal_id}/confirm` | 200，deal 状态 → `active` |
| 2 | 查询 Deal | `GET /deals/{deal_id}` | 200，状态为 `active` |
| 3 | 教练拒绝 Deal | `POST /escort/deals/{deal_id}/reject` | 200，deal 状态 → `cancelled` |

### TC-14 签到
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 教练签到 | `POST /escort/coaches/deals/{deal_id}/check-in` | 200，返回签到成功 |
| 2 | 教练签到（orders 路由） | `POST /escort/orders/{task_id}/check-in` | 200，任务状态更新 |

### TC-15 签退
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 教练签退 | `POST /escort/coaches/deals/{deal_id}/check-out` | 200，返回签退成功 |
| 2 | 教练签退（orders 路由） | `POST /escort/orders/{task_id}/check-out` | 200，任务状态更新 |

### TC-16 完成订单
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 完成 Deal | `POST /deals/{deal_id}/complete` | 200，deal 状态 → `completed` |
| 2 | 查询 Deal 确认 | `GET /deals/{deal_id}` | 200，状态为 `completed` |

---

## 五、评价（2 个场景）

### TC-17 学员评价教练
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 学员提交评价 | `POST /escort/orders/{task_id}/reviews` `{rating, comment}` | 200，返回评价记录 |
| 2 | 查询评价 | `GET /escort/orders/{task_id}/reviews` | 200，返回评价列表 |

### TC-18 重复评价
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 再次提交评价 | `POST /escort/orders/{task_id}/reviews` | 400/409 重复评价错误 |

---

## 六、争议与取消（3 个场景）

### TC-19 发起争议
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 发起争议 | `POST /deals/{deal_id}/dispute` | 200，deal 状态 → `disputed` |
| 2 | 解决争议 | `POST /deals/{deal_id}/resolve` | 200，deal 状态 → `completed` |

### TC-20 Deal 取消
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 取消 Deal | `POST /deals/{deal_id}/cancel` | 200，deal 状态 → `cancelled` |

### TC-21 预约单取消违约金
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 创建预约单（提前 >24h） | `POST /escort/orders` `{order_type: "SCHEDULED", scheduled_at: now+25h}` | 200 |
| 2 | 取消订单 | `POST /escort/orders/{task_id}/cancel` | 200，违约金 = deal.amount × 20% |

---

## 七、限流保护（2 个场景）

### TC-22 高频请求拦截
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 发送 150 并发请求 | `GET /deals/{deal_id}`（循环） | 前 100 个返回 200，后续 50 个返回 429 |
| 2 | 检查 429 响应 | 解析 429 响应 | body 含 `rate_limit_exceeded`，含 `Retry-After` 头 |
| 3 | 等待窗口重置 | 等待 60 秒 | 请求恢复正常（200） |

### TC-23 回调豁免
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 高频请求回调端点 | `POST /escort/payments/callback`（循环） | 全部返回（不限流） |

---

## 八、通知系统（2 个场景）

### TC-24 DEAL_CREATED 通知
| 步骤 | 操作 | 触发事件 | 预期结果 |
|------|------|----------|----------|
| 1 | 创建 Deal | `DEAL_CREATED` | 服务端日志输出 `[SMS][DEV]` 通知教练 |
| 2 | WS 推送 | - | 教练 WS 连接收到 `DEAL_CREATED` 事件 |

### TC-25 PAYMENT_PAID 通知
| 步骤 | 操作 | 触发事件 | 预期结果 |
|------|------|----------|----------|
| 1 | 确认支付 | `PAYMENT_PAID` | 服务端日志输出 `[SMS][DEV]` 通知学员 |
| 2 | WS 推送 | - | 学员 WS 连接收到 `PAYMENT_PAID` 事件 |

---

## 九、安全性（3 个场景）

### TC-26 角色越权
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 学员调用教练接口 | `POST /escort/deals/{deal_id}/confirm`（学员 token） | 403 `Forbidden` |
| 2 | 教练调用学员接口 | `POST /escort/orders`（教练 token） | 403 `Forbidden` |

### TC-27 资源隔离
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 用户 A 查询用户 B 的 Deal | `GET /deals/{deal_id}`（非参与者） | 404 `Not Found` |

### TC-28 支付回调签名验证
| 步骤 | 操作 | 请求 | 预期结果 |
|------|------|------|----------|
| 1 | 模拟非法回调 | `POST /escort/payments/callback` 无签名头 | 200，`code: "FAIL"` |
| 2 | 重放攻击 | 重放同一回调请求 | 因 nonce 校验失败被拒绝 |

---

## 测试执行日志

| 测试脚本 | 执行结果 | 时间 |
|----------|----------|------|
| `simulate_wechat_payment.py` | ✅ 已通过 | 2026-08-15 22:47 |
| `simulate_payment_timeout.py` | ✅ 已通过 | 2026-08-15 22:47 |
| `test_rate_limit.py` | ✅ 已通过（94成功/56拦截） | 2026-08-15 22:47 |
| `test_sms_notification.py` | ✅ 已通过（SMS 日志输出正常） | 2026-08-15 22:48 |
| `test_wechat_gateway.py` | ✅ 51/51 通过 | 2026-08-15 |
| `test_payment_flow.py` | ✅ 全部通过 | 2026-08-15 |
| `test_payment_edge_cases.py` | ✅ 全部通过 | 2026-08-15 |
| 全量测试套件 | ✅ 945/945 通过 | 2026-08-15 |

---

## 已知问题与注意事项

| # | 说明 | 影响 | 建议 |
|---|------|------|------|
| 1 | `datetime.utcnow()` 弃用警告（Python 3.14） | 仅日志警告，不影响业务 | 下个版本统一迁移到 `datetime.now(datetime.UTC)` |
| 2 | 测试中 JWT 密钥长度不足 32 字节 | 仅测试环境警告，生产环境已使用 32 字节密钥 | 测试配置无需变更 |
| 3 | 内存仓储重启后数据丢失 | 开发测试无影响 | 生产环境需配置 PostgreSQL |
| 4 | 短信为开发模式（控制台输出） | 生产环境需配置互亿无线 API | 参考 `.env.example` 配置 |
| 5 | 微信支付为 Mock 模式 | 测试支付流程需 Mock 模式 | 生产环境配置 WECHAT_* 参数后自动切换 |