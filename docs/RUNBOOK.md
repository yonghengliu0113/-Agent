# 运行手册

排障、监控、压测、迁移的操作手册。**启动只写一次**（第 1 节），其余文档不再重复。

- 想理解为什么：看 [ARCHITECTURE.md](ARCHITECTURE.md)
- 想查接口字段：看 [API.md](API.md)
- 想 5 分钟跑起来：看 [README.md](../README.md)

---

## 1. 启动与停止

### 1.1 进程与端口清单

| 进程 | 端口 | 启动命令（工作目录 `ai-agent-service/` 等见列） | 日志 |
| --- | --- | --- | --- |
| Redis | 6379 | `.tools/redis-7.2.9/src/redis-server --port 6379` | `.logs/redis.log` |
| Java `business-service` | 8081 | `business-service/` → `mvn spring-boot:run` | `.logs/java.log` |
| Agent API | 8000 | `ai-agent-service/` → `.venv/bin/uvicorn app:app --port 8000` | `.logs/agent-api.log` |
| Agent Worker | — | `ai-agent-service/` → `.venv/bin/python -m rag.agent_execution_worker` | `.logs/agent-worker.log` |
| 定时物流复核 Worker | — | `.venv/bin/python -m rag.scheduled_followup_worker` | 按需重定向 |
| 会话摘要 Worker | — | `.venv/bin/python -m rag.conversation_summary_worker`（需 `CONVERSATION_SUMMARY_ENABLED=true`） | 按需重定向 |
| DeepEval Worker | — | `.venv/bin/python -m rag.evaluation_worker --interval 60` | 按需重定向 |
| Vue 前端 | 5173 | `frontend-vue/` → `npm run dev` | `.logs/vue.log` |

### 1.2 启动顺序（顺序不能反）

1. **Redis** —— 队列、限流准入、SSE 事件都依赖它。未起会导致 API 能启动但请求全部降级。
2. **Java business-service** —— 必须等 `/actuator/health` 返回 UP（冷启动 10~30 秒）。Agent 的鉴权与所有业务工具都指向它。
3. **Agent API** —— 等 `/health` 返回 `{"status":"ok"}`。
4. **Agent Worker** —— 必须有活跃 Worker，否则队列请求只会 `queued` 不会 `completed`。
5. **Vue 前端** —— 最后起，避免页面持续 `ECONNREFUSED`。

macOS 无 Docker 一键启动（推荐，按上述顺序并自带等待）：

```bash
cd /Users/yongheng/Desktop/货运智能体/enterprise-customer-agent
./start-local.sh
```

脚本使用仓库内 `.tools/` 的 JDK 17、Maven 3.9.16、Redis 7.2.9，不依赖系统环境。Windows 下用 `start-all.bat`（转调 `start-all.ps1`，需要 Docker Desktop）。

启动验证（全部通过才算真正起来）：

```bash
curl -s http://127.0.0.1:8081/actuator/health      # Java UP
curl -s http://127.0.0.1:8000/health               # {"status":"ok"}
curl -s http://127.0.0.1:8000/api/agent/status     # queue.enabled 与 active_worker 都为 true
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5173   # 200
```

端到端冒烟（一条命令验证鉴权 + Agent + 建单链路）：

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8081/api/auth/login \
  -H 'Content-Type: application/json' -d '{"username":"demo","password":"123456"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -s -X POST http://127.0.0.1:8000/api/agent/reply \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"message":"货损索赔有什么时间限制","route_target":"ai"}'
```

### 1.3 停止

```bash
# 按进程名停（推荐，幂等）
pkill -f "uvicorn app:app"
pkill -f "agent_execution_worker"
pkill -f "scheduled_followup_worker"
pkill -f "conversation_summary_worker"
pkill -f "evaluation_worker"
pkill -f "spring-boot:run"
pkill -f "vite"
# Redis（会丢掉未持久化的队列状态）
.tools/redis-7.2.9/src/redis-cli -p 6379 shutdown nosave
```

注意：Agent API 启动时会注册失联坐席会话回收任务，强杀（`kill -9`）会残留 `HUMAN_ACTIVE` 会话；正常停止才会执行清理与就绪文件删除。

---

## 2. 常见故障处置

| 现象 | 优先排查 | 处置 |
| --- | --- | --- |
| 前端页面 `ECONNREFUSED` | 对应后端是否真的起来 | 按 1.2 顺序逐个 `curl` 健康检查，别先改前端 |
| `/api/agent/reply/stream` 一直 `queued` | 没有活跃 Worker | `curl /api/agent/status` 看 `active_worker`；起 `agent_execution_worker`；查 `agent_queue_depth` 与 `agent_dead_letter_depth` |
| 请求返回安全降级话术 | 队列等待 >30s、并发超限、LLM 超时/429/熔断 | 看 `agent_degraded_total{reason}`；上调 `AGENT_MAX_CONCURRENCY` 或扩 Worker；确认模型配额 |
| `/api/agent/status` 里 `llm.configured=false` | `.env` 缺 `DEEPSEEK_API_KEY`/`LLM_API_KEY` | 补密钥后重启 API；缺失时全部走规则兜底，表现是"能答但很笨" |
| 登录 401（`staff/123456`） | Java 未重启到最新代码，或 Token 过期 | 重启 `business-service`；重新 `POST /api/auth/login` |
| 访问会话/工单返回 403 | Token 与资源不属于同一客户 | 正常保护，不要试图放宽；用对应账号重新登录 |
| 客户看不到坐席回复 | 坐席只生成了草稿没点"确认发送" | 让坐席走 `/api/staff/tickets/{ticketNo}/reply/send`；客户侧再轮询会话详情 |
| 工单状态卡住不动 | 用了已废弃的 `/api/tickets/{ticketNo}/status` | 旧入口返回 410，改用 `/api/staff/tickets/**` |
| 工单与会话对不上 | 两库无跨库事务，`externalSessionNo` 缺失 | 用 `chat_message.extra_data.ticket_result.data.ticketNo` 反查；新工单应带 `externalSessionNo` |
| 附件上传 413 | 超过 `MAX_ATTACHMENT_BYTES`（默认 10MB） | 调大环境变量或压缩文件；确认 `data/uploads` 可写 |
| RAG 启动即失败 | `RAG_STRICT_STARTUP=true` 且索引/依赖不可用 | 先降为 `false` 定位，再修 pgvector/知识库；生产不建议长期关闭 |
| `/metrics` 无数据 | 抓取地址写错（注意 `/metrics` 不暴露在 OpenAPI） | 直接 `curl http://127.0.0.1:8000/metrics` 验证 |
| Docker 报 `permission denied ... npipe:////./pipe/docker_engine` | Windows 未启 Docker Desktop / 用户不在 `docker-users` 组 | 启动 Docker Desktop，加入组后重新登录 |

排障通用姿势：任何一次异常都先抓 `X-Request-ID` 与 `X-Trace-ID`，再用它们在 `.logs/agent-api.log`、`.logs/agent-worker.log`、`.logs/java.log` 三处对齐同一次请求。

---

## 3. 监控指标

Python 侧 `GET /metrics`（Prometheus 文本格式），Java 侧 `GET /actuator/prometheus`。两者**分别抓取**，再导入 `docs/observability/grafana-dashboard.json` 与 `docs/observability/agent-alerts.yml`。

关键指标：

| 指标 | 类型 | 含义 | 关注点 |
| --- | --- | --- | --- |
| `agent_http_requests_total{path,method,status}` | Counter | HTTP 请求总数 | 5xx 占比 > 2% 告警 |
| `agent_http_request_duration_seconds{path,method}` | Histogram | 请求延迟 | P95 > 2s 告警 |
| `agent_queue_depth` | Gauge | Stream 待消费数 | > 100 告警；持续增长说明 Worker 不足 |
| `agent_queue_pending` | Gauge | Pending（已投递未 ACK） | 长期不降说明消费者卡死 |
| `agent_queue_running` / `agent_queue_retrying` | Gauge | 执行中 / 重试中 | 重试飙升通常是下游抖动 |
| `agent_dead_letter_depth` | Gauge | 死信队列 | **非 0 立即处理** |
| `agent_worker_jobs_total{status}` / `agent_worker_duration_seconds` | Counter/Histogram | Worker 任务与耗时 | 指标停止增长 = Worker 挂了 |
| `agent_degraded_total{reason}` | Counter | 安全降级次数 | 降级率升高告警 |
| `agent_handoff_total{reason}` | Counter | 转人工次数 | 突增说明风险规则或检索异常 |
| `agent_downstream_requests_total{downstream,outcome}` / `..._duration_seconds` | Counter/Histogram | LLM/Java 调用结果与耗时 | `outcome=timeout/429/circuit_open` 升高告警 |
| `agent_sse_active_connections` / `agent_sse_events_total{event_type}` | Gauge/Counter | SSE 连接与事件 | 连接泄漏看 active 是否只增不减 |
| `agent_cache_operations_total{cache,outcome}` | Counter | 缓存命中/未命中 | 命中率骤降查 Redis |
| `agent_rag_query_rewrite_total{outcome}` / `..._duration_seconds` | Counter/Histogram | 查询重写 | 重写失败应有规则降级兜底 |
| `agent_execution_cancellations_total{outcome}` | Counter | 取消请求 | 取消耗时长查 `agent_execution_cancel_duration_seconds` |

建议告警阈值：API P95 > 2s、5xx > 2%、`agent_queue_depth` > 100、死信非 0、LLM 超时/429/熔断升高、降级率升高、数据库连接池接近上限、Redis 不可用、Worker 指标停止增长。

坐席端 `/staff/system-monitor` 是**轻量内部面板**（看队列深度、Pending、DLQ、降级、缓存），不替代生产 Grafana 大盘。

日志与 Trace 禁止出现 `Authorization`、手机号、邮箱、地址、完整订单号、Prompt、工具原始敏感返回；业务标识必须哈希或脱敏。

---

## 4. 压测方法

脚本：`load-tests/agent-reply.js`（k6），覆盖政策咨询、订单物流、工单、动作请求、高风险、越界问题、SSE 与幂等回放。

前置条件：Agent API、Java、Redis、PostgreSQL、**至少一个 Agent Worker** 全部就绪；使用已授权的测试客户 Token 与压测专用模型密钥（避免消耗生产配额）。

```bash
k6 run \
  -e AGENT_BASE_URL=http://localhost:8000 \
  -e CUSTOMER_TOKEN=<测试Token> \
  -e TARGET_QPS=10 \
  -e DURATION=10m \
  load-tests/agent-reply.js
```

阶梯推进规则：**只有当前阶段全部满足才允许进入下一阶段**——队列能回落到基线、DLQ 为 0、5xx < 1%、API P95 ≤ 1s。阶段为 10 → 20 → 50 → 100 QPS。

每阶段必须同时采集：`/metrics`、Java `/actuator/prometheus`、OTLP Trace，以及模型供应商、Java、数据库、Redis 的资源使用率。

现状：**10 QPS 尚未实测**，历史报告只记录了脚本与验收口径，没有任何真实 P50/P95/P99 结论。不得对外宣称已支持 100 QPS。

---

## 5. 数据迁移（SQLite → PostgreSQL）

默认运行模式是 SQLite（Python 与 Java 各一个 db 文件）。迁移必须在维护窗口执行，先停写入。

### 5.1 顺序

Java 侧：`customer → employee/product → order_info → logistics_info/logistics_trace → support_ticket/ticket_urge_log`

Python 侧：`chat_session → chat_message → agent_call_log → evaluation_trace → evaluation_result/evaluation_job`

### 5.2 步骤

```bash
cd ai-agent-service

# 1) 导出（自动生成同目录 .bak 备份）
.venv/bin/python scripts/migrate_sqlite_to_postgres.py data/customer_agent.db export.jsonl

# 2) 校验导出文件（记录行数与主键摘要）
.venv/bin/python scripts/validate_migration.py export.jsonl

# 3) 建表（先跑 DDL，V1~V5 按顺序）
psql "$PG_DSN" -f migrations/postgres/V1__agent_schema.sql
# V2__chat_session_pinning.sql / V3__handoff_status.sql /
# V4__conversation_state_followup_notification.sql / V5__staff_handoff_audit.sql

# 4) 导入（单事务，出错不提交部分结果）
.venv/bin/python scripts/import_postgres_export.py export.jsonl --dsn "$PG_DSN"
```

导入后用同样的行数与业务主键摘要与第 2 步比对。

### 5.3 回滚

- 导入必须在**独立事务或新库**中执行；校验失败就回滚事务或删掉目标 schema。
- **绝不覆盖 SQLite 的 `.bak`**，它是唯一回滚依据。
- 校验未完成前，应用继续指向 SQLite（不要提前切换 `DB_PROVIDER`）。

### 5.4 运行时 Profile 切换

| | SQLite（开发默认） | PostgreSQL（验证/生产） |
| --- | --- | --- |
| Python | 不设 `DB_PROVIDER` | `DB_PROVIDER=postgres` + `DATABASE_URL=postgresql://...` |
| Java | `application.yml`，`mvn spring-boot:run` | `SPRING_PROFILES_ACTIVE=postgres`，Flyway 执行 `db/migration/V1__business_postgres_schema.sql` |
| RAG | `RAG_STORE_BACKEND=memory` | `RAG_STORE_BACKEND=pgvector` + `RAG_DATABASE_URL=...` |

PostgreSQL profile 下 Java **不再**执行 SQLite 的 `CREATE TABLE`、`AUTOINCREMENT` 或 `PRAGMA` 兼容代码；结构只由 Flyway 管理。

雷区：`support_ticket.request_id` 与 `(customer_id, idempotency_key)` 有唯一约束，导入冲突必须人工确认，**不能用覆盖写入掩盖重复建单**。

---

## 6. 提交前必跑（与 AGENTS.md 一致）

```bash
cd ai-agent-service
.venv/bin/python -m pytest tests
.venv/bin/python -m compileall agents graphs rag schemas tools repositories services app

cd ../business-service && mvn -q -DskipTests compile && mvn test
cd ../frontend-vue && npm run typecheck
```

改了接口：额外跑 [API.md](API.md) 第 4 节的契约比对。改了状态机：先更新 [ARCHITECTURE.md](ARCHITECTURE.md) 第 4 节。
