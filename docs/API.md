# API 契约

本文是 Agent API 与 Java Business API 的**唯一契约文档**。

- Agent 侧的权威来源是 `docs/_baseline/baseline-openapi.json`（**52 个 operation**）。本文按该基线整理，不得凭记忆增删接口。
- 代码里另有 2 个 `include_in_schema=False` 的路由（`GET /metrics`、`POST /api/agent/reply/stream/legacy`），**不在** OpenAPI 内，本文单列说明。
- 架构背景看 [ARCHITECTURE.md](ARCHITECTURE.md)，启动与排障看 [RUNBOOK.md](RUNBOOK.md)。

## 1. 统一约定

### 1.1 地址与端口

| 服务 | Base URL | OpenAPI / 文档 |
| --- | --- | --- |
| Agent API（Python） | `http://localhost:8000` | `/docs`、`/openapi.json` |
| Business API（Java） | `http://localhost:8081` | Actuator `/actuator/health`、`/actuator/prometheus` |

### 1.2 认证

- 除 `/health`、`/metrics`、`/api/agent/status` 外，Agent 侧接口都接受 `Authorization: Bearer <token>`。
- Token 只能由 `POST /api/auth/login` 获得（Agent 代理到 Java）。Agent 用该 Token 向 Java 换取可信身份，**请求体中的 `customer_id` 一律被覆盖**，不能作为授权依据。
- 内部服务间调用使用 `X-Agent-Internal-Secret`（值来自 `AGENT_INTERNAL_SECRET`），仅用于 `POST /api/internal/tickets/status-sync`。
- 写操作建议带 `Idempotency-Key` 请求头；工单创建在 Java 侧另有 `(customer_id, idempotency_key)` 唯一约束兜底。

### 1.3 通用请求头

| 头 | 方向 | 说明 |
| --- | --- | --- |
| `Authorization: Bearer <token>` | 入 | 客户/坐席身份 |
| `Idempotency-Key` | 入 | 幂等键，`/api/agent/reply` 与 `/stream` 支持 |
| `X-Request-ID` | 双向 | 未传则服务端生成，响应必定回写 |
| `X-Trace-ID` | 双向 | 与 OTel Span 关联，跨 API/Worker/Java 排障 |
| `X-Agent-Internal-Secret` | 入 | 内部回写接口密钥 |

### 1.4 错误格式

- 参数校验失败：HTTP **422**，FastAPI 标准 `HTTPValidationError`（`detail` 数组）。
- 业务错误（Java）：HTTP **400**，body 为 `{"status": "failed", "error_message": "..."}`。
- 已废弃接口：HTTP **410**，body 同上，`error_message` 提示改用哪个新入口。
- 越权访问他人工单/会话：HTTP **403** 或业务 400，取决于入口。
- 降级/超限：HTTP **429 / 503**，`/metrics` 的 `agent_degraded_total` 同步增长。

### 1.5 响应字段可见性

`analysis`、`risk_reasons`、`tool_results`、`internal_suggestion`、`citations` 原始结构、Trace 字段**只允许坐席侧/内部页面使用**。客户侧只能拿到 `customer_message`（安全话术）、`service_status`、工单号、工单状态、自己的会话与坐席确认后的回复。

---

## 2. Agent API（52 个 operation + 2 个隐藏路由）

### 2.1 系统与鉴权（routers/system.py + auth.py，6 路由 / 5 operations）

#### `GET /health`
存活检查，无鉴权。返回 `{"status": "ok"}`。

#### `GET /metrics` 🔒不在 OpenAPI
Prometheus 抓取端点，`include_in_schema=False`。返回 `text/plain`。关键指标见 [RUNBOOK.md](RUNBOOK.md) 第 3 节。

#### `GET /api/agent/status`
Agent 与 LLM 配置状态、队列开关、是否有活跃 Worker。用于排查"前端无输出"。

```json
{
  "status": "ok",
  "llm": {"configured": true, "provider": "deepseek", "model": "deepseek-chat"},
  "queue": {"enabled": true, "active_worker": true}
}
```

#### `GET /api/staff/system/monitor`
坐席端轻量监控快照，需坐席身份。返回 `agent_status`、`queue`（`stream_depth`/`pending`/`running`/`retrying`）、`worker.active`、`dlq.count`、`llm`、`cache`、`degraded`、`updated_at`。局部指标读取失败不影响整体返回。

#### `POST /api/auth/login`
代理 Java 登录。请求 `{"username": "demo", "password": "123456"}`。

```json
{
  "token": "jwt-token",
  "token_type": "Bearer",
  "user": {"user_id": 1, "customer_id": 1, "display_name": "Demo Customer", "role": "customer"}
}
```

Demo 账号：`demo/123456`（客户 1）、`buyer/123456`（客户 2）、`staff/123456`、`staff2/123456`。

#### `GET /api/auth/current-user`
代理 Java 当前用户。需 `Authorization`。Agent 不使用环境变量模拟登录人。

### 2.2 Agent 核心（routers/agent.py，9 路由）

#### `POST /api/agent/analyze`
只做意图识别与结构化抽取，不建单、不落消息。

```json
{"message": "我的订单 EC202606220001 想退款", "session_id": "S202606220001"}
```

返回字段：`intent`（业务域：咨询/物流/退款/换货/维修/投诉/发票/会员/其他）、`user_goal`（rules_consult/status_query/action_request/complaint/dispute/info_query/other）、`emotion`、`order_no`（数组）、`need_order_query`、`need_ticket`、`need_human`、`priority`、`confidence`、`action_type`、`action_slots`、`missing_slots`、`next_action`（`collect_slots`/`create_ticket`/`cancel_pending`）。

> `intent` 不等于风险级别。`intent=refund + user_goal=rules_consult` 是可自动回答的规则咨询；只有 `action_request`/`complaint`/`dispute` 才进人工或建单。

#### `POST /api/agent/reply`
客户提问的完整处理链（同步返回最终结果）。支持 `Idempotency-Key`。

请求（`AgentReplyRequest`，必填仅 `message`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `message` | string | **必填**，客户原文 |
| `session_id` | string | 续接会话；必须属于当前客户，否则 403 |
| `selected_order_no` | string | 前端选中的订单上下文，服务端会再用 Token 校验归属 |
| `selected_ticket_no` | string | 选中工单上下文 |
| `session_ticket_no` | string | 会话关联工单号 |
| `route_target` | string | 默认 `ai`；`human` 走人工通道 |
| `pending_action_request` | object | 上一轮未完成动作，通常由服务端自动合并 |
| `conversation_context` | object | 会话上下文快照 |
| `customer_id` | int | **不可信**，会被 Token 覆盖 |
| `login_user_context` | object | 登录用户上下文 |
| `auth_token` | string | 内部透传，前端不要使用 |

返回：`answer`、`customer_message`、`auto_send`、`need_human`、`service_status`、`analysis`、`citations`、`tool_results`、`ticket_result`、`risk_reasons`、`pending_action_request`、`request_id`。

#### `POST /api/agent/reply/stream`
SSE 流式回复，**生产默认入口**。请求体同 `/api/agent/reply`，同样支持 `Idempotency-Key`。事件序列：

`accepted` → `queued` → `generating` → `completed`；异常分支为 `degraded`（安全降级话术）。队列等待超 30 秒直接降级。

#### `POST /api/agent/reply/stream/legacy` 🔒不在 OpenAPI
旧版流式接口，`include_in_schema=False`，仅为兼容保留，新代码不要使用。

#### `GET /api/agent/replies/{request_id}`
查询队列任务结果。需 `Authorization`（校验归属）。

#### `POST /api/agent/replies/{request_id}/cancel`
取消排队中/生成中的任务。对应指标 `agent_execution_cancellations_total`。

#### `POST /api/agent/tool/call`
白名单受控工具调用。

```json
{"tool_name": "query_order", "arguments": {"order_no": "EC202606220001"}}
```

`tool_name` 必填；`arguments` 为对象。非法工具名或越权参数直接失败，不编造结果。

#### `GET /api/agent/logs?limit=N`
最近 Agent 调用日志（`agent_call_log`），`limit` 为整数、可选。

#### `POST /api/agent/handoff/messages`
坐席在接管会话中代发消息。可选 `Authorization`，body 为 `AgentReplyRequest`。

### 2.3 会话（routers/chat.py，8 路由）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/chat/session` | 显式新建会话，body 可选 `{"title": "新会话"}` |
| `GET` | `/api/chat/session/list?limit=N` | 当前客户会话列表，不含已删除 |
| `GET` | `/api/chat/session/{session_id}?after_message_id=X` | 会话详情 + 消息增量拉取 |
| `DELETE` | `/api/chat/session/{session_id}` | **软删除**：客户列表不再展示，库内保留用于工单追踪/审计 |
| `PATCH` | `/api/chat/session/{session_id}/pin` | 置顶会话，body 可选 |
| `POST` | `/api/chat/session/{session_id}/attachment` | 上传附件，`multipart/form-data`；上限 `MAX_ATTACHMENT_BYTES`（默认 10MB），落 `data/uploads` |
| `GET` | `/api/chat/session/{session_id}/attachment/{message_id}` | 下载附件，返回流 |
| `POST` | `/api/chat/session/{session_id}/handoff/cancel` | 客户主动取消人工接管 |

会话归属按 Token 中的客户 ID 强校验，读他人会话返回 403。

### 2.4 客户业务（routers/customer.py，12 路由）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/customer/orders` | 当前客户订单列表 |
| `GET` | `/api/customer/orders/{order_no}` | 订单详情 |
| `GET` | `/api/customer/orders/{order_no}/logistics` | 完整物流路线与轨迹节点 |
| `GET` | `/api/customer/tickets` | 当前客户工单列表 |
| `GET` | `/api/customer/tickets/{ticket_no}` | 工单详情（代理 Java，按 Token 校验） |
| `GET` | `/api/customer/tickets/{ticket_no}/change-requests` | 工单变更申请列表 |
| `POST` | `/api/customer/tickets/{ticket_no}/urge` | 催办，body `{"reason": "..."}`；写 `ticket_urge_log` 并更新 `urgeCount`/`lastUrgedAt`/`lastUrgeReason` |
| `GET` | `/api/customer/follow-ups?limit=N` | 客户跟进任务列表 |
| `POST` | `/api/customer/follow-ups/{followup_id}/cancel` | 取消跟进任务 |
| `GET` | `/api/customer/notifications?limit=N` | 站内通知列表 |
| `GET` | `/api/customer/notifications/unread-count` | 未读数 |
| `POST` | `/api/customer/notifications/{notification_id}/read` | 标记已读 |

### 2.5 坐席（routers/staff.py，13 路由）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/staff/handoff/sessions?limit=N` | 接管会话队列（自己名下 `ACTIVE` + 全局 `PENDING`） |
| `GET` | `/api/staff/handoff/sessions/{session_id}?after_message_id=X` | 会话详情 |
| `GET` | `/api/staff/handoff/sessions/{session_id}/history?before_message_id=X&limit=N` | 历史消息分页，`before_message_id` **必填** |
| `POST` | `/api/staff/handoff/sessions/{session_id}/accept` | 领取会话，`handoff_status` → `ACTIVE` |
| `POST` | `/api/staff/handoff/sessions/{session_id}/reply` | 坐席回复，写入客户可见消息 |
| `POST` | `/api/staff/handoff/sessions/{session_id}/close` | 关闭接管，会话回落 `AI_ONLY` |
| `POST` | `/api/staff/handoff/sessions/{session_id}/ticket` | 从接管会话创建工单 |
| `GET` | `/api/staff/handoff/sessions/{session_id}/attachment/{message_id}` | 下载会话附件 |
| `POST` | `/api/staff/presence/heartbeat` | 坐席在线心跳；离线坐席的会话由后台任务回收 |
| `DELETE` | `/api/staff/presence` | 坐席下线 |
| `GET` | `/api/staff/tickets/{ticket_no}/context` | 工单上下文聚合：工单详情 + 关联会话 + 消息 + AI 建议 + 风险原因 + 工具结果 |
| `POST` | `/api/staff/tickets/{ticket_no}/reply/draft` | 生成客户安全话术草稿（**规则模板，不调 LLM**） |
| `POST` | `/api/staff/tickets/{ticket_no}/reply/send` | 坐席确认发送；写入 `sender_type=staff` 消息，会话状态 `STAFF_REPLIED` |

> Agent 只生成草稿，**不自动发送**。发送必须由坐席显式确认。

### 2.6 评测（routers/evaluation.py，5 路由）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/staff/evaluation/online/report?days=N&limit=N` | 线上采样评测报告 |
| `GET` | `/api/staff/evaluation/queue` | 评测任务队列状态 |
| `GET` | `/api/staff/rag/evaluation?mode=...` | RAG 黄金集评测结果 |
| `POST` | `/api/staff/rag/evaluation/jobs` | 创建评测任务（异步，body 可选） |
| `GET` | `/api/staff/rag/evaluation/jobs/{job_id}` | 查询任务进度与报告 |

评测一律异步：客户请求只落脱敏 Trace，`evaluation_worker` 独立消费。

### 2.7 内部（routers/internal.py，1 路由）

#### `POST /api/internal/tickets/status-sync`
Java 把工单状态回写到 Python 会话。必须带 `X-Agent-Internal-Secret`，body 为自由 JSON（含工单号与目标状态）。缺密钥或密钥错误直接拒绝。

---

## 3. Java Business API

Base URL `http://localhost:8081`。除 `/api/products` 外全部需要 `Authorization`；客户侧接口一律按 Token 中的客户 ID 校验归属。

### 3.1 认证 `/api/auth`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/auth/login` | 登录签发 Token。body `{"username","password"}` |
| `GET` | `/api/auth/current-user` | 当前用户（含 `customer_id`、`role`） |

### 3.2 基础资料

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/customers/{id}` | 客户信息（手机号等已脱敏） |
| `GET` | `/api/products` | Demo 商品列表 |

### 3.3 订单 `/api/orders`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/orders` | 当前客户订单列表（`customerId` 参数仅为兼容，实际以 Token 为准） |
| `GET` | `/api/orders/{orderNo}` | 订单状态、支付/发货/签收时间、售后状态 |
| `GET` | `/api/orders/{orderNo}/detail` | 订单完整明细 |
| `GET` | `/api/orders/{orderNo}/logistics` | 物流主记录 + 轨迹节点 |

物流返回示例：

```json
{
  "orderNo": "EC202606220002",
  "carrierName": "顺丰速运",
  "trackingNo": "SF202606230002",
  "logisticsStatus": "IN_TRANSIT",
  "latestLocation": "上海转运中心",
  "estimatedDeliveryTime": "2026-06-25T18:00:00",
  "routeSummary": "杭州仓库 -> 杭州集散中心 -> 上海转运中心",
  "traces": [
    {"status": "SHIPPED", "description": "商家已发货，快件已完成揽收。",
     "location": "杭州", "stationName": "杭州仓库", "occurredAt": "2026-06-23T10:00:00"}
  ]
}
```

### 3.4 客户工单 `/api/tickets`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/tickets` | 当前客户工单列表 |
| `POST` | `/api/tickets` | 创建工单；`customerId` 以 Token 为准，服务端生成 `ticket_no`、默认 `PENDING_ASSIGN`、24h SLA |
| `GET` | `/api/tickets/{ticketNo}` | 工单详情，访问他人工单报业务错误 |
| `GET` | `/api/tickets/{ticketNo}/change-requests` | 变更申请列表 |
| `POST` | `/api/tickets/{ticketNo}/urge` | 催办，body `{"reason": "..."}` |
| `POST` | `/api/tickets/{ticketNo}/supplements` | 补充材料 |

建单请求关键字段：`title`、`ticketType`、`priority`、`orderNo`、`externalSessionNo`（Python 会话号，用于强关联）、`content`、`aiSummary`、`assignedGroup`、`source`、`idempotencyKey`。

#### 已废弃（统一返回 410）

`POST /api/tickets/{ticketNo}/assign`、`/transfer`、`/status`、`/close`、`/reopen` —— 不再允许直接写状态。

```json
{"status": "failed", "error_message": "该工单写接口已废弃，请使用 /api/staff/tickets 或 /api/internal/tickets"}
```

### 3.5 坐席工单 `/api/staff/tickets`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/staff/tickets?status=A,B` | 工单队列，按状态筛选 |
| `GET` | `/api/staff/tickets/{ticketNo}` | 坐席视角工单详情 |
| `POST` | `/api/staff/tickets/{ticketNo}/assign` | 领取/分派 → `PENDING_PROCESS` |
| `POST` | `/api/staff/tickets/{ticketNo}/status` | 状态更新，body `{"status": "PROCESSING"}` |
| `POST` | `/api/staff/tickets/{ticketNo}/close` | 关闭 → `CLOSED` |
| `GET` | `/api/staff/tickets/{ticketNo}/change-requests` | 变更申请列表 |
| `POST` | `/api/staff/tickets/{ticketNo}/change-requests/{requestNo}/decision` | 变更申请审批 |

### 3.6 内部工单 `/api/internal/tickets`（Agent → Java）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/internal/tickets/{ticketNo}/auto-assign` | 低风险自动派单；需配置开启且风控通过，`assignedBy=MANUAL` 时不得覆盖 |
| `POST` | `/api/internal/tickets/handoff` | 转人工 |
| `POST` | `/api/internal/tickets/{ticketNo}/resolve-ai` | AI 结案回写 |

### 3.7 内部坐席 `/api/internal/staff`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/internal/staff/availability` | 坐席可用性，供派单决策 |

---

## 4. 契约一致性检查

改了任何一个接口，按下面顺序同步，否则文档会立刻失真：

1. 启动服务，`curl -s http://localhost:8000/openapi.json > /tmp/now.json`。
2. 与 `docs/_baseline/baseline-openapi.json` 比对 path 与 operation 数量（应为 **52**；路由总数 **54**）。
3. 数量变化时：更新本文件对应小节 + 更新基线 spec。
4. 涉及可见性变化的字段（新增客户可见/不可见字段），同步 [ARCHITECTURE.md](ARCHITECTURE.md) 第 1.1 节的边界条目。

快速自检命令：

```bash
python3 -c "
import json
s=json.load(open('docs/_baseline/baseline-openapi.json'))
ops=[(m.upper(),p) for p,v in s['paths'].items() for m in v if m in ('get','post','put','patch','delete')]
print('paths',len(s['paths']),'operations',len(ops))
"
```
