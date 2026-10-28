# 架构说明

本文是货运智能体平台的**唯一架构权威文档**。它回答三件事：系统由哪些部分组成、一条客户消息如何流动、哪些边界不允许突破。

- 想跑起来：看 [README.md](../README.md)
- 想调接口：看 [API.md](API.md)
- 想排障/扩容/迁移：看 [RUNBOOK.md](RUNBOOK.md)
- 想了解某个设计为什么这样做：看 [ADR/](ADR/)

历史调研、PRD、交付批次、验证证据等非权威材料统一放在仓库外层的 `archive/产品与研究产物/`，不再维护。

---

## 1. 系统定位与边界

平台是"**LLM 语义理解 + 后端确定性编排**"的受控 Agent：LLM 只负责意图识别、槽位抽取和话术生成；订单归属、权限、风险、幂等、状态流转和工具执行全部由后端规则、状态机与 LangGraph 工作流决定。

系统由四个可独立部署的运行时组成：

| 运行时 | 技术栈 | 默认端口 | 职责 | 是否可公网 |
| --- | --- | --- | --- | --- |
| `frontend-vue` | Vue 3 + TS + Vite | 5173 | 客户自助端、坐席工作台、RAG 评测页、系统监控页 | 是（仅客户侧） |
| `ai-agent-service` | FastAPI + LangGraph + LangChain | 8000 | 鉴权代理、Agent 编排、RAG、工具调用、会话/Trace、队列、SSE | 是（经网关） |
| `business-service` | Spring Boot 3 + JdbcTemplate | 8081 | 登录认证、客户、商品、订单、物流、工单主数据与状态流转 | 否（仅内网） |
| Redis / PostgreSQL | Redis 7 / pgvector | 6379 / 5432 | 队列与限流状态 / 生产会话、Trace、评测、向量 | 否 |

消息队列消费者是三组**独立进程**（不是 API 进程内的线程）：`rag.agent_execution_worker`、`rag.scheduled_followup_worker`、`rag.conversation_summary_worker`、`rag.evaluation_worker`。

### 1.1 三条不可谈判的边界

1. **Java 是唯一业务真相源。** Python 不直接写订单、物流、工单业务表，所有业务动作必须经 `tools/` 里的受控工具调用 Java 接口完成。
2. **身份只认 Java 登录态。** 前端传入的 `customer_id`、姓名、订单号一律不可信；Agent 服务用 `Authorization: Bearer <token>` 向 Java 校验，并以返回值覆盖请求体中的身份字段。
3. **AI 不自动执行高风险动作。** 退款、赔付、删除、关闭投诉、真实退货申请等，只能建单 + 进人工，或生成草稿等坐席确认。

### 1.2 角色与可见范围

| 角色 | 入口 | 能做 | 不能做 |
| --- | --- | --- | --- |
| 客户 customer | `/customer/**` | 提问、查自己的订单/物流/工单/通知、催办、取消接管 | 看内部分析、派单、处理工单 |
| Agent（Python 内部） | 无页面 | 建单、配置开启且低风险时触发自动派单、生成话术草稿 | 直接写 Java 业务表、高风险自动派单、自动发送坐席回复、覆盖人工派单 |
| 坐席 staff | `/staff` | 领取/处理/关闭名下工单、接管会话、生成并**确认发送**客户回复 | 给别人派单、看全员统计 |
| 调度 dispatcher | **当前无页面**（能力仅有 Java 接口） | 智能派单、手动分派/改派、看坐席资源 | 直接处理工单、发送客户回复 |
| 主管/管理员 | 未实现 | — | — |

前端路由当前只有 `/customer/**` 与 `/staff/**`（外加 `/staff/rag-evaluation`、`/staff/system-monitor`），调度台与主管看板尚未落地。

---

## 2. 代码分层

### 2.1 Python 服务（已完成 `app.py` 拆分）

历史上的 1657 行单文件 `ai-agent-service/app.py` 已拆成 `app/` 包，**`uvicorn app:app` 入口保持不变**。当前结构：

```
ai-agent-service/
├── app/
│   ├── __init__.py        # 8 行，仅导出 FastAPI 实例（from app.main import app）
│   ├── main.py            # 97 行，仅装配：中间件、生命周期、路由挂载，无业务逻辑
│   ├── deps.py            # 54 行，进程级单例集中构建
│   ├── core/config.py     # 13 行，环境变量唯一出口
│   └── api/
│       ├── helpers.py     # 468 行，31 个跨路由共享辅助函数
│       └── routers/       # system/auth/agent/chat/evaluation/customer/internal/staff
├── agents/                # 意图、上下文、动作状态机、Agent 门面
├── graphs/                # LangGraph 工作流（ticket_process_graph.py）
├── rag/                   # 检索、入库、引用、评测、四个 Worker
├── tools/                 # 订单、工单、知识库受控工具
├── schemas/               # 意图 Schema
├── repositories/          # 会话、日志、评测、会话状态持久化
├── services/              # 执行服务、队列、缓存、韧性、可观测性
├── scripts/               # 迁移与数据集校验脚本
└── tests/                 # pytest 用例（37 个测试文件）
```

**路由总数 54**，其中 `/metrics` 与 `/api/agent/reply/stream/legacy` 标记 `include_in_schema=False`，因此 OpenAPI 只有 **52 个 operation**。基线契约文件为 `docs/_baseline/baseline-openapi.json`，修改接口后必须重新生成并比对。

各路由职责与路由数：

| 路由模块 | 路由数 | 职责 |
| --- | --- | --- |
| `routers/system.py` | 4 | `/health`、`/metrics`、`/api/agent/status`、坐席系统监控快照 |
| `routers/auth.py` | 2 | 登录代理、当前用户代理 |
| `routers/agent.py` | 9 | 意图识别、同步回复、SSE 流式回复、工具调用、队列结果查询/取消、Agent 日志、坐席代发 |
| `routers/chat.py` | 8 | 会话增删查、置顶、附件上传下载、客户取消接管 |
| `routers/evaluation.py` | 5 | 线上评测报告、评测队列、RAG 评测与评测任务 |
| `routers/customer.py` | 12 | 订单、物流、工单、催办、跟进任务、站内通知 |
| `routers/internal.py` | 1 | Java 回写工单状态到会话（密钥校验） |
| `routers/staff.py` | 13 | 接管会话队列/领取/详情/历史/回复/关闭/建单、坐席在线心跳、工单上下文与回复草稿 |

### 2.2 装配层三条铁律

1. **单例与 helper 一律按模块属性访问**：写 `deps.chat_messages`、`deps.agent_execution_queue`、`helpers._current_login_user(...)`，**不要** `from app.deps import chat_messages`。
   按值 import 会拿到启动时的旧对象引用，测试里的 `monkeypatch.setattr(deps, "chat_messages", ...)` 将完全失效，导致测试"通过但没测到"。
2. **新配置项只允许加在 `app/core/config.py`**，通过 `config.XXX` 访问，禁止再写新的散落 `os.getenv`。
   ⚠️ **已知偏差（截至当前代码）**：`app/core/config.py` 实际只覆盖 `BUSINESS_SERVICE_URL`、`AGENT_INTERNAL_SECRET`、`AGENT_STARTUP_READY_FILE`、`UPLOAD_ROOT`、`MAX_ATTACHMENT_BYTES` 五项；全仓仍有约 146 处 `os.getenv` 分布在 `services/`、`rag/`、`agents/`、`graphs/` 与部分 `routers/`（如 `AGENT_MAX_CONCURRENCY`、`CONVERSATION_SUMMARY_ENABLED`、RAG 相关开关）。**不要假设"环境变量只有 config.py 一处"**，排查配置时仍需全仓搜索。
3. **`app/main.py` 不写业务**。它只做三件事：注册 `observe_request` 中间件（注入 `X-Request-ID`/`X-Trace-ID` 并记录指标）、管理生命周期（RAG 启动检查、失联接管会话回收任务、就绪文件写入/清理）、按固定顺序 `include_router`。

`deps.py` 集中构建的单例：`agent`（CustomerServiceAgent）、`order_tools`、`ticket_tools`、`chat_sessions`、`chat_messages`、`evaluation_repository`、`staff_presence`、`staff_handoff_audit`、`staff_reply_draft_service`、`agent_execution_service`、`agent_execution_queue`、`stream_event_service`、`business_client`（受控 Java 调用）、`identity_cache`、`followup_notifications`。

### 2.3 依赖方向规则

```
app/api/routers  ──►  app/api/helpers  ──►  app/deps  ──►  services  ──►  repositories
      │                                                      │              │
      └──────────────────────────────────────────────►  tools / agents / graphs / rag
                                                                          │
app/core/config  ◄── 所有层（唯一允许被任意层依赖的叶子模块）──────────────┘
```

硬性规则：

- **单向**：`routers → helpers → deps → services → repositories`；反过来 import 一律禁止。
- `services/` 与 `repositories/` **不得** import `app.api.*`，否则形成环，且 Worker 进程会被迫加载 HTTP 层。
- `deps` 只做**装配**，不含分支逻辑；装配顺序即初始化顺序，新增单例放在依赖它的单例之前。
- `routes` 不直接 `requests/httpx` 调 Java，必须经 `tools/` 或 `deps.business_client`（统一超时、重试、熔断、舱壁、降级）。
- 跨路由复用的函数进 `helpers.py`；只被一个路由用的留在路由文件内。
- Worker 通过 `AgentExecutionService` 执行业务，**不要** import `app` 复用路由函数。

---

## 3. 一条客户消息的旅程

以客户输入"我买的鞋子质量不好，商家不给更换"为例，走完整链路：

1. **前端**（`customer/CustomerHome.vue`）调用 `POST /api/agent/reply/stream`，携带 `Authorization`、`Idempotency-Key` 和 `{message, session_id?, selected_order_no?}`。
2. **中间件**（`main.py:observe_request`）生成/透传 `X-Request-ID`、`X-Trace-ID`，开 OTel Span，记录 `agent_http_requests_total` 与延迟直方图。
3. **鉴权**（`routers/agent.py` + `helpers._current_login_user`）用 Token 向 Java `/api/auth/current-user` 换取可信身份，身份结果进 `deps.identity_cache`；请求体里的 `customer_id` 被覆盖。
4. **落库**：客户原始消息写入 `chat_message`（`sender_type=customer`）；会话不存在则先创建（`status=AI_ONLY`）。
5. **准入与并发保护**（`services/runtime_protection.py`）：全局并发 `AGENT_MAX_CONCURRENCY`（默认 20）、单主体并发 `AGENT_PER_SUBJECT_CONCURRENCY`（默认 2），多副本时用 Redis 做分布式准入（`AGENT_ADMISSION_TTL_SECONDS`，默认 90 秒）。超限直接安全降级，不排队硬扛。
6. **入队**：开启 `AGENT_EXECUTION_QUEUE_ENABLED` 时，请求写入 Redis Stream，API 立即返回 `accepted`，随后通过 SSE 推送 `queued → generating → completed`（或 `degraded`）。真实的 LLM/RAG/工具执行发生在独立 `agent-worker` 进程；队列等待超过 30 秒返回安全降级话术。
7. **Agent 执行**（`services/agent_execution_service.py`，API 与 Worker 共用的唯一执行边界）：
   - 构建会话上下文：最近若干轮消息 + 超 15 轮的异步滚动摘要（`conversation_summary_worker`）+ 未完成的 `pending_action_request`。
   - **LangGraph 固定顺序**：`analyze → query_order → retrieve_knowledge → risk_check → create_ticket → generate_reply`。
   - `analyze`：意图 `intent`（业务域）+ 用户目的 `user_goal` + 情绪 + 槽位抽取；LLM 失败自动回退规则识别。
   - `query_order`：有订单号或前端选中订单时调 Java 校验归属，不通过则不用于生成回复。
   - `retrieve_knowledge`：RAG 检索，只取已发布且未失效文档，返回引用 ID。
   - `risk_check`：售后争议、投诉、赔付、维权、低置信度、无知识库依据 → 强制 `need_human=True` / `need_ticket=True`。
   - `create_ticket`：携带幂等键调 Java 建单，`externalSessionNo` 写回 Python 会话号完成强关联。
   - `generate_reply`：生成 `customer_message`（客户安全话术）与内部建议。
8. **业务兜底**（`agents/customer_service_agent.py`）：即使 LLM 判定可自动回复，`_apply_business_guardrails` 仍会按规则改写为转人工/建单，防止提示词失效。
9. **结果收敛**：AI 回复落库（`sender_type=ai`），`extra_data` 里存 `citations`/`tool_results`/`ticket_result`/风险原因（**仅内部可见**）；SSE 推送 `completed`；会话状态更新为 `AI_ONLY` 或 `AI_REPLIED`。
10. **人工接管**：`need_human` 为真时会话转 `HUMAN_PENDING`，进入坐席接管队列；坐席 `accept` 后变 `HUMAN_ACTIVE`，坐席回复经 `/api/staff/handoff/sessions/{id}/reply` 落库，会话状态 `STAFF_REPLIED`／`HUMAN_CLOSED` 后回到 `AI_ONLY`。失联坐席由启动时注册的 `helpers._recover_stale_handoffs()` 后台任务周期性回收。
11. **客户看到结果**：客户轮询 `GET /api/chat/session/{id}` 或保持 SSE；工单进度走 `GET /api/customer/tickets/{ticket_no}`（代理 Java，按 Token 校验归属）。
12. **异步旁路**：脱敏后的 Trace 写入 `evaluation_trace`，由独立 `evaluation_worker` 消费跑 DeepEval；**在线请求绝不等待 LLM Judge**。

---

## 4. 状态机

### 4.1 工单状态（Java `TicketStatus`）

六个状态：`PENDING_ASSIGN`、`PENDING_PROCESS`、`PROCESSING`、`TRANSFERRED`、`CLOSED`、`REOPENED`。

```
            建单(Agent/客户)
                  │
                  ▼
           PENDING_ASSIGN ──智能派单/手动分派/坐席领取──► PENDING_PROCESS
                  │                                          │
                  │                              ┌───────────┴───────────┐
                  │                              │                       │
                  │                        开始处理▼                直接关闭▼
                  │                        PROCESSING ──关闭──►     CLOSED
                  │                              │                  │
                  │                        改派  ▼                  │ 客户反馈/复核重开
                  │                        TRANSFERRED ──再分派──► REOPENED
                  │                              │                  │
                  └──────────────────────────────┴──再分派──────────┘
                                          （回到 PENDING_PROCESS）
```

关键规则：

- 建单默认落在 `PENDING_ASSIGN`，SLA 默认 24 小时。
- **Agent 默认不自动派单**：未配置 `AGENT_AUTO_ASSIGN_TICKET` 时全部保持待分派。开启后也仅限低风险、规则明确、非真实业务动作的工单；投诉、争议、退款/退货申请、赔付、低置信度必须由调度确认。
- `assignedBy = MANUAL` 的工单，后续智能派单不得覆盖人工选择。
- 所有写动作只走受控入口：坐席/调度用 `/api/staff/tickets/**`，Agent 建单后自动派单用 `/api/internal/tickets/**`。客户侧旧写接口（`/api/tickets/{ticketNo}` 下的 assign/transfer/status/close/reopen）已废弃，统一返回 **HTTP 410**。
- 客户侧只展示工单号、客户安全话术、状态和坐席回复；不展示派单理由、AI 分析、风险原因、工具结果。

### 4.2 会话与人工接管状态

`chat_session.status`：`AI_ONLY`（纯 AI）→ `AI_REPLIED`（AI 已回复）→ `HUMAN_PENDING`（等待坐席领取）→ `HUMAN_ACTIVE`（坐席处理中）→ `STAFF_REPLIED`（坐席已回复）/ `HUMAN_CLOSED`（接管关闭，回落 `AI_ONLY`）。

`chat_session.handoff_status`：`NONE` / `PENDING` / `ACTIVE`，与上表联动；接管队列按 `ACTIVE` 优先、`PENDING` 次之排序，坐席只能看到自己名下 `ACTIVE` 的会话。

### 4.3 业务动作（槽位）状态机

真实业务动作（退货、换货、维修、发票、取消订单、投诉）统一用一套闭环：

`intent + user_goal + action_type + action_slots + missing_slots + pending_action_request + next_action`

- `next_action = collect_slots`：缺槽位，只追问，**不建单**；同一会话下一轮自动合并新信息。
- `next_action = create_ticket`：槽位齐全且订单归属校验通过，进入建单。
- `next_action = cancel_pending`：客户主动取消。

规则咨询（`user_goal=policy_consult`）在有知识库依据时可直接回答，**不得**因 `intent=refund` 就误触发退货动作——这是 RAG 与业务写操作的分流关键。

---

## 5. 数据与存储

| 存储 | 归属 | 内容 | 生产目标 |
| --- | --- | --- | --- |
| `ai-agent-service/data/*.db`（SQLite） | Python | `chat_session`、`chat_message`、`agent_call_log`、`evaluation_trace`、`evaluation_result`、`evaluation_job`、`conversation_state`、`followup_notification`、`staff_handoff_audit` | PostgreSQL（`DB_PROVIDER=postgres`） |
| `business-service/data/business-service.db`（SQLite） | Java | `user_account`、`customer`、`product`、`order_info`、`logistics_info`、`logistics_trace`、`support_ticket`、`ticket_urge_log`、`knowledge_document`、`agent_call_log` | PostgreSQL（Flyway `db/migration`） |
| 内存 BM25 / pgvector | Python | 知识库片段与向量 | pgvector（`RAG_STORE_BACKEND=pgvector`） |
| Redis Stream | Python | 在线执行队列、定时跟进队列、摘要队列、限流准入 | 必须 |

两侧 SQLite 是**两个独立文件，没有跨库事务**：Java 建单成功而 Python 写消息失败时，只能靠接口错误码与日志对账（见"已知限制"）。

### 5.1 核心表与关键字段（Java 侧）

| 表 | 关键字段（省略 `id/created_at/updated_at`） |
| --- | --- |
| `user_account` | `username`、`password_hash`、`real_name`、`role_code`、`team_id`、`status` |
| `customer` | `customer_name`、`phone`（展示必脱敏）、`level`、`register_time`、`status` |
| `product` | `product_name`、`category`、`warranty_days`、`returnable`、`status` |
| `order_info` | `order_no`、`customer_id`、`product_id`、`order_status`、`pay_time`、`ship_time`、`sign_time`、`amount`、`after_sale_status` |
| `logistics_info` | `order_no`、`carrier_name`、`tracking_no`、`logistics_status`、`latest_location`、`estimated_delivery_time` |
| `logistics_trace` | `logistics_id`、`trace_status`、`trace_desc`、`location`、`station_name`、`occurred_at` |
| `support_ticket` | `ticket_no`、`title`、`ticket_type`、`priority`、`customer_id`、`order_no`、`session_id`、`external_session_no`、`content`、`ai_summary`、`assigned_group`、`handler_id`、`status`、`sla_deadline`、`source`、`urge_count`、`last_urged_at`、`last_urge_reason`、建单幂等约束 `(customer_id, idempotency_key)` |
| `ticket_urge_log` | `ticket_no`、`customer_id`、`reason` |
| `knowledge_document` | `doc_name`、`doc_type`、`version`、`file_path`、`status`（草稿/处理中/待发布/已发布/已下线/解析失败）、`effective_time`、`expire_time`、`created_by` |
| `agent_call_log` | `session_id`、`ticket_id`、`tool_name`、`input_data`/`output_data`（**必须脱敏**）、`status`（成功/失败/超时）、`error_message` |

Python 侧 `chat_session` 的核心字段：`session_no`、`customer_id`、`status`、`handoff_status`、`human_assigned_staff_id`、`current_agent_id`、`intent`、`emotion`、`priority`、`ai_summary`、`pinned`、`deleted_at`（软删除）。`chat_message`：`session_id`、`sender_type`（customer/ai/staff）、`sender_id`、`content`、`message_type`、`extra_data`（`citations`/`tool_results`/`ticket_result`/风险原因，**仅内部可见**）。

必建索引（唯一/查询路径）：

- 唯一：`order_info(order_no)`、`logistics_info(order_no)`、`support_ticket(ticket_no)`、`chat_session(session_no)`。
- 查询：`logistics_trace(logistics_id, occurred_at)`、`support_ticket(status, priority, sla_deadline)`、`ticket_urge_log(ticket_no, created_at)`、`chat_message(session_id, created_at)`、`knowledge_document(status, doc_type, effective_time, expire_time)`、`agent_call_log(session_id, created_at)`。

---

## 6. 评测体系

评测链路与在线链路物理隔离：

```
客户请求 → evaluation_trace(脱敏) → evaluation_worker → DeepEval → evaluation_result
黄金集任务 → evaluation_job ────────┘                              → 任务报告
```

采样策略：高风险、转人工、工具失败、低置信度、无知识库命中、引用异常 **100% 采样**；普通成功会话稳定 **10%** 采样。每日 Judge 预算 `EVAL_DAILY_BUDGET=200`，单批 10 条串行执行；黄金集样本并发 `RAG_GOLDEN_EVAL_CONCURRENCY=3`。Trace 落库前脱敏，订单号、手机号、邮箱不进入评测库。

**货运知识库评测结论（55 题黄金集，2026-10 一次性评测，原始报告已归档）：**

1. 检索可用但不理想：片段级 hit@1 = **81.8%**、hit@3 = **92.7%**，达标线分别是 80% / 90%——刚过线，余量很小。
2. 文档级/集合级/业务域级指标恒为 100%（同域片段必然同文档），**判断检索质量只能看片段级指标**，别被 100% 误导。
3. 端到端回答有据性 96.4%，但必备事实覆盖率仅 **70.9%**（达标线 80%，**未达标**），幻觉 2 题，失败样本 22/55。
4. 失败集中在三类：高风险域事实缺失（货损理赔、危险品、报关时限）、检索错层（答成相邻小节）、答非所问（赔偿限额问成投诉受理）。
5. 结论：检索架构（BM25 + 规则 rerank + 内存后端）可继续用，**优先补知识库切片粒度与高风险域必备事实覆盖**，其次再考虑换检索器或加查询重写。

---

## 7. 已知限制

这些是**当前代码的事实**，不要假设已经解决：

1. **两个 SQLite 文件、没有跨库事务**。Java 建单与 Python 落消息可能不一致，靠 `externalSessionNo` 与日志排查，不保证强一致。
2. **Java 侧仍是 Demo 账号体系**：明文密码、硬编码 JWT/内部密钥（`demo|buyer|staff|staff2`，密码均为 `123456`）。上线前必须替换为正式身份系统与 Secret 管理。
3. **Python Repository 的 PostgreSQL 方言与连接池尚未在生产验证**；`migrations/postgres/V1~V5` 与迁移脚本齐备，但只做过离线导入校验。
4. **Redis Stream 缺消费后裁剪策略**：`XACK` 有，`XDEL`/`XTRIM` 与数据留存策略未落地，长期运行 Stream 会持续增长。
5. **容量结论缺失**：10/20/50/100 QPS 分阶段压测尚未执行，只有压测脚本（`load-tests/agent-reply.js`）与报告模板，不能对外宣称支持 100 QPS。
6. **坐席端上下文不完整**：`internal_suggestion`、`risk_reasons`、`tool_results` 已落库但坐席台未完整展示。
7. **调度端缺失**：`/dispatcher` 页面与 `DispatcherHome.vue` 在当前前端**并不存在**（路由只有 `/customer/**` 与 `/staff/**`）；分派能力目前只能通过 Java `/api/staff/tickets/{ticketNo}/assign` 接口调用。历史文档中提到的 `GET /api/staff/members`、`StaffMemberController`、`POST /api/staff/tickets/{ticketNo}/transfer` 同样**未实现**，不要按旧文档对接。
8. **客户侧无实时推送**：SSE 只用于 Agent 回复流；坐席回复后客户需轮询或手动刷新才能看到。
9. **坐席回复草稿是规则模板**（`services/staff_reply_draft_service.py`），不是 LLM 润色。
10. **领域绑定**：意图 Schema、售后状态机、工具 API、Java DTO 与前端文案仍绑定当前电商/货运业务；抽 `AgentKernel` / `DomainPack` / `BusinessConnector` / `KnowledgePack` 只是迁移方向，尚未实施。
11. **`/metrics` 与 legacy SSE 不在 OpenAPI 内**：客户端生成代码时看不到它们，改动时需手工同步 `docs/_baseline/baseline-openapi.json`。

---

## 8. 修改架构时的自检清单

- 新增路由：挂到对应 `routers/*.py`，统计总数（当前 54 / OpenAPI 52），更新 [API.md](API.md) 与基线 spec。
- 新增单例：加在 `deps.py`，使用方按**属性**访问。
- 新增环境变量：只加在 `core/config.py`，并在 [README.md](../README.md) 的配置表补一行。
- 新增状态：先改本文第 4 节，再改代码。
- 新增跨层依赖：先确认不违反第 2.3 节方向规则，否则先重构。
- 涉及边界（Java 真相源、身份、高风险动作）的改动：先写 ADR。
