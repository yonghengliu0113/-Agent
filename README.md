# 货运智能体（Enterprise Customer Agent）

企业智能客服受控 Agent 平台：客户自助端 + 坐席工作台 + FastAPI Agent 服务 + Spring Boot 业务系统。

本文只讲**怎么用起来**。设计与原因看 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，接口看 [docs/API.md](docs/API.md)，排障/压测/迁移看 [docs/RUNBOOK.md](docs/RUNBOOK.md)。

---

## 1. 前置依赖

| 依赖 | 版本要求 | 说明 |
| --- | --- | --- |
| JDK | 17 | Java 业务服务 |
| Maven | 3.9+ | 构建 Java |
| Python | 3.12 / 3.13 | Agent 服务 |
| Node.js | 20+（开发机为 22） | Vue 前端 |
| Redis | 7.x | 队列、限流准入、SSE 事件 |
| PostgreSQL + pgvector | 15+（可选） | 生产存储；本地默认用 SQLite + 内存检索，**不需要**装 |

macOS 开发机上 JDK 17、Maven 3.9.16、Redis 7.2.9 已随仓库放在 `.tools/` 下，`start-local.sh` 会直接用它们，不必另装。

## 2. 首次安装依赖

```bash
# Python
cd ai-agent-service
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 前端
cd ../frontend-vue
npm install
```

`ai-agent-service/.env` 已包含本地所需变量（模型密钥、`REDIS_URL`、`DB_PROVIDER`、`RAG_STORE_BACKEND`、`BUSINESS_SERVICE_URL` 等）。**不要提交真实密钥**。

## 3. 启动

### 一键（macOS，推荐）

```bash
cd /Users/yongheng/Desktop/货运智能体/enterprise-customer-agent
./start-local.sh
```

脚本按固定顺序拉起 Redis → Java(8081) → Agent API(8000) → Agent Worker → Vue(5173)，每一步都做健康等待。日志在 `.logs/`。

**需要服务在当前终端关掉后继续常驻时，改用 `start-local.py`：**

```bash
python3 start-local.py
```

两者的区别是实质性的：`start-local.sh` 用 `nohup ... &`，只忽略 SIGHUP，进程仍在调用方的
进程组里——终端被关闭或被清理时，整个进程组会一起收到终止信号，服务随之消失。
`start-local.py` 用 `start_new_session=True`（等价 setsid）把每个服务放进独立会话，
真正做到脱离父 shell 常驻。CI/远程会话/自动化脚本里启动时，请用 `start-local.py`。

Windows 用 `start-all.bat`（需要 Docker Desktop）。

### 手动（等价，五个终端）

严格按此顺序，**前一个就绪再起下一个**：

```bash
# 1) Redis
.tools/redis-7.2.9/src/redis-server --port 6379 --save '' --appendonly no

# 2) Java 业务服务 → 等 /actuator/health 为 UP（冷启动 10~30 秒）
cd business-service && mvn spring-boot:run

# 3) Agent API
cd ai-agent-service
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000

# 4) Agent Worker（不起它，请求只会排队不会返回）
cd ai-agent-service
.venv/bin/python -m rag.agent_execution_worker

# 5) Vue 前端
cd frontend-vue && npm run dev
```

> 生产/多副本部署必须设置 `REDIS_URL` 与 `AGENT_EXECUTION_QUEUE_ENABLED=true`，并把 Worker 拆成独立进程（`agent-worker`），不要把 LLM 执行压进 API 进程。

## 4. 端口与入口

| 服务 | 地址 |
| --- | --- |
| 前端（客户侧） | http://localhost:5173/customer |
| 前端（坐席） | http://localhost:5173/staff |
| RAG 评测页 | http://localhost:5173/staff/rag-evaluation |
| 系统监控页 | http://localhost:5173/staff/system-monitor |
| Agent 健康检查 | http://localhost:8000/health |
| Agent 指标 | http://localhost:8000/metrics |
| Agent 接口文档 | http://localhost:8000/docs |
| Java 健康检查 | http://localhost:8081/actuator/health |
| Java 指标 | http://localhost:8081/actuator/prometheus |

## 5. 验证"真的起来了"

三步，全过才算成功：

```bash
# ① 三个健康检查
curl -s http://127.0.0.1:8081/actuator/health        # UP
curl -s http://127.0.0.1:8000/health                 # {"status":"ok"}
curl -s http://127.0.0.1:8000/api/agent/status       # queue.enabled / active_worker 均为 true

# ② 页面能打开
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5173    # 200

# ③ 端到端一条真实提问（鉴权 → Agent → 返回）
TOKEN=$(curl -s -X POST http://127.0.0.1:8081/api/auth/login \
  -H 'Content-Type: application/json' -d '{"username":"demo","password":"123456"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -s -X POST http://127.0.0.1:8000/api/agent/reply \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"message":"货损索赔有什么时间限制","route_target":"ai"}'
```

第 ③ 步返回带 `answer` 的 JSON 即为通链路。若 `llm.configured=false`，说明 `.env` 缺模型密钥，此时走规则兜底——能答但质量差。

## 6. 登录账号（Demo）

| 角色 | 账号 | 密码 | 入口 |
| --- | --- | --- | --- |
| 客户 | `demo` | `123456` | `/customer/login` |
| 客户 | `buyer` | `123456` | `/customer/login` |
| 坐席 | `staff` | `123456` | `/staff/login` |
| 坐席 | `staff2` | `123456` | `/staff/login` |

这些是演示账号，明文密码与内置 JWT/内部密钥**必须在真实上线前替换**。

## 7. 关键配置

| 环境变量 | 作用 | 默认 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` / `LLM_API_KEY` | 在线 LLM 凭证，不配则全程规则兜底 | 空 |
| `LLM_BASE_URL` / `LLM_MODEL` / `LLM_PROVIDER` | OpenAI 兼容模型地址、模型名、供应商 | 见 `.env` |
| `REDIS_URL` | 队列、事件流、缓存、跨副本限流 | `redis://127.0.0.1:6379/0` |
| `AGENT_EXECUTION_QUEUE_ENABLED` | 启用 Redis Stream 在线队列（生产必须 `true`） | 未设置时同步执行 |
| `AGENT_MAX_CONCURRENCY` / `AGENT_PER_SUBJECT_CONCURRENCY` | 全局 / 单主体并发上限 | 20 / 2 |
| `BUSINESS_SERVICE_URL` | Java 业务服务地址 | `http://localhost:8081` |
| `DB_PROVIDER` / `DATABASE_URL` | Python 仓储数据库 | `sqlite` / 空 |
| `RAG_STORE_BACKEND` / `RAG_DATABASE_URL` | RAG 后端 | `memory` / 空 |
| `RAG_STRICT_STARTUP` | RAG 初始化失败是否禁止静默回退（生产建议 `true`） | `false` |
| `RAG_LLM_QUERY_REWRITE_ENABLED` | 启用 LLM 查询重写（关闭时用规则） | `false` |
| `CONVERSATION_SUMMARY_ENABLED` | 超 15 轮历史异步滚动摘要（需同时运行 `conversation_summary_worker`） | 代码默认按 `true` 处理；`start-all.ps1` 显式设为 `true` |
| `AGENT_INTERNAL_SECRET` / `AGENT_EXECUTION_SECRET` | 内部接口密钥 / Worker 执行凭证签名密钥 | 生产必须注入强随机值 |
| `AGENT_AUTO_ASSIGN_TICKET` | 是否允许 Agent 低风险自动派单 | 关闭 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP Collector 地址 | 空（只建本地 Span） |

`app/core/config.py` 只覆盖其中一部分，其余变量由各模块直接读取（存量未收口）；改配置前建议 `grep -rn "os.getenv" ai-agent-service --include=*.py` 全量确认。新增变量加在 `config.py`。

## 8. 目录速览

```text
enterprise-customer-agent/
├── ai-agent-service/
│   ├── app/            # FastAPI 装配层：main.py / deps.py / core/config.py / api/
│   ├── agents/ graphs/ rag/ tools/ schemas/ repositories/ services/ tests/
│   └── data/ datasets/ training/ prompts/   # 业务资产，勿随意改动
├── business-service/   # Spring Boot 业务系统
├── frontend-vue/       # 唯一前端
├── deploy/             # K8s 资源草案
├── load-tests/         # k6 压测脚本
└── docs/               # ARCHITECTURE / API / RUNBOOK / ADR / _baseline / observability
```

## 9. 提交前必跑

```bash
cd ai-agent-service
.venv/bin/python -m pytest tests
.venv/bin/python -m compileall agents graphs rag schemas tools repositories services app

cd ../business-service && mvn -q -DskipTests compile
cd ../frontend-vue && npm run typecheck
```

语法检查的对象是 **`app` 包**，不是已删除的 `app.py`。

## 10. 能力现状（一句话版）

已打通：客户登录 → 提交问题 → 意图识别与槽位编排 → RAG 引用回答 / 建工单 → 坐席接管处理 → 客户看到回复与进度；另有异步 DeepEval 评测、Prometheus 指标、Redis Stream 可靠队列。

**尚未完成生产验收**：容量压测（10/20/50/100 QPS）未执行、PostgreSQL 方言未在生产验证、Demo 账号与硬编码密钥待替换。详见 [ARCHITECTURE.md 第 7 节](docs/ARCHITECTURE.md)。

## 11. 文档地图

| 文档 | 用途 |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 分层边界、模块职责、一条消息的旅程、状态机、评测结论、已知限制 |
| [docs/API.md](docs/API.md) | Agent API + Java Business API 完整契约 |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | 启动停止、排障、监控指标、压测、数据迁移 |
| [docs/ADR/](docs/ADR/) | 架构决策记录 |
| [docs/observability/](docs/observability/) | Grafana 看板与告警规则 |
| [AGENTS.md](AGENTS.md) | 给未来 agent 的贡献指南 |
| `archive/产品与研究产物/` | 历史 PRD、调研、交付批次、验证证据（**非权威**） |

## 12. License

[MIT](LICENSE)
