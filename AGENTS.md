# 仓库贡献指南（给未来 agent 的活文档）

本文件是**写给 agent 的操作说明**，不是给人读的架构文档。它只回答：目录在哪、怎么启动、改完必须跑什么、哪里不许碰。

> 架构与边界看 `docs/ARCHITECTURE.md`；接口契约看 `docs/API.md`；排障/压测/迁移看 `docs/RUNBOOK.md`；启动验证看 `README.md`。
> 历史 PRD、调研、交付批次、验证证据在仓库外层的 `archive/产品与研究产物/`，**不是权威文档，不要从中提取事实**。

## 1. 目录结构（当前真实结构）

```
enterprise-customer-agent/
├── ai-agent-service/            # FastAPI Agent 服务
│   ├── app/                     # 装配层（历史上的单文件 app.py 已拆分）
│   │   ├── __init__.py          # 8 行，只导出 FastAPI 实例，uvicorn app:app 仍可用
│   │   ├── main.py              # 90 行，仅装配：中间件、生命周期、路由挂载
│   │   ├── deps.py              # 55 行，进程级单例集中构建
│   │   ├── core/config.py       # 13 行，app 层新增配置的入口（存量 os.getenv 尚未收口）
│   │   └── api/
│   │       ├── helpers.py       # 31 个跨路由共享辅助函数
│   │       └── routers/         # system/auth/agent/chat/evaluation/customer/internal/staff
│   ├── agents/                  # 意图、上下文、动作状态机、Agent 门面
│   ├── graphs/                  # LangGraph 工作流
│   ├── rag/                     # 检索、入库、引用、评测、四个 Worker
│   ├── tools/                   # 订单、工单、知识库受控工具
│   ├── schemas/                 # 意图 Schema
│   ├── repositories/            # 会话、日志、评测、会话状态持久化
│   ├── services/                # 执行服务、队列、缓存、韧性、可观测性
│   ├── scripts/                 # 迁移与数据集校验脚本
│   ├── tests/                   # pytest（37 个测试文件）
│   └── data/ datasets/ training/ prompts/   # 业务资产，勿动
├── business-service/            # Spring Boot 业务系统（唯一业务真相源）
├── frontend-vue/               # 唯一前端：/customer/**、/staff/**
├── deploy/                      # K8s 资源草案
├── load-tests/                  # k6 压测脚本
├── docs/                        # ARCHITECTURE / API / RUNBOOK / ADR / _baseline / observability
├── images/  .logs/  .tools/     # 素材、运行日志、本地 JDK/Maven/Redis
├── start-local.sh               # macOS 无 Docker 一键启动
└── start-all.bat / .ps1         # Windows 一键启动（需 Docker Desktop）
```

**已不存在的东西，别去找**：根目录的 `app.py`、`frontend-demo/`、`staff-console/`（Streamlit 演示端）、`docs/rag-eval/`、`docs/项目现状盘点.md`、`docs/API接口文档.md`、`docs/工单状态与角色动作流程图.md`。

## 2. 架构边界（改代码前先确认不越界）

- **Java 是唯一业务真相源**。Python 不直接写订单、物流、工单业务表，业务动作必须经 `tools/` 调用 Java。
- **身份只认 Java Token**。前端传的 `customer_id`/订单号不可信，用 `Authorization: Bearer <token>` 校验并覆盖。
- **队列中不保存客户原始 Authorization**；Worker 用短期内部执行凭证调 Java。
- **写操作必须幂等**，尤其是建工单。
- **AI 不自动执行**退款、赔付、删除、关闭投诉等高风险动作；也不自动发送坐席回复（只出草稿，坐席确认后才发）。
- **在线执行默认走 Redis Stream**，由独立 `agent-worker` 消费；不要让 API 进程绕过 `AgentExecutionQueue` 长时间同步执行。
- **`AgentExecutionService` 是唯一执行边界**。API 与 Worker 都通过它执行 Agent，**Worker 不要 import `app` 复用路由函数**。
- **评测必须异步**：在线请求只落脱敏 Trace，不同步调 LLM Judge。

### 装配层三条铁律（最容易违反）

1. 单例与 helper **按模块属性访问**：`deps.chat_messages`、`deps.agent_execution_queue`、`helpers._current_login_user(...)`。**禁止** `from app.deps import chat_messages` / `from app.api.helpers import xxx`——按值 import 会让测试 monkeypatch 失效，测试"通过但没测到"。
2. **新配置项只加在 `app/core/config.py`**，其它模块用 `config.XXX`。注意这是**目标约定**而非现状：全仓仍有约 146 处存量 `os.getenv`（`services/`、`rag/`、`agents/`、`graphs/` 及部分 routers），排查配置时不要只读 `config.py`。
3. `app/main.py` **不写业务逻辑**，只做中间件、生命周期、`include_router`。

### 依赖方向

`routers → helpers → deps → services → repositories`，业务侧 `tools / agents / graphs / rag`。反向 import 一律禁止；`services`/`repositories` 不得 import `app.api.*`。`core/config.py` 是唯一允许被任意层依赖的叶子模块。

### 路由基线

**54 个路由**，其中 `/metrics` 与 `/api/agent/reply/stream/legacy` 为 `include_in_schema=False`，OpenAPI 只有 **52 operations**。基线文件 `docs/_baseline/baseline-openapi.json`。改接口必须同步 `docs/API.md` 与基线 spec。

## 3. 启动

macOS（推荐，按 Redis → Java → Agent API → Worker → Vue 顺序并自带健康等待）：

```bash
./start-local.sh          # 日志在 .logs/
```

手动等价步骤：

```bash
# 1) Redis
.tools/redis-7.2.9/src/redis-server --port 6379 --save '' --appendonly no

# 2) Java → 等 /actuator/health 为 UP
cd business-service && mvn spring-boot:run

# 3) Agent API（注意入口是 app 包，不是 app.py）
cd ai-agent-service && .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000

# 4) Agent Worker（不起它，请求只会 queued）
cd ai-agent-service && .venv/bin/python -m rag.agent_execution_worker

# 5) Vue
cd frontend-vue && npm run dev
```

端口：Redis 6379、Java 8081、Agent API 8000、Vue 5173。按需附加：`rag.scheduled_followup_worker`、`rag.conversation_summary_worker`、`rag.evaluation_worker --interval 60`。

Windows 用 `start-all.bat`（需 Docker Desktop；报 `permission denied ... npipe:////./pipe/docker_engine` 时启动 Docker Desktop 并确认用户在 `docker-users` 组后重新登录）。

## 4. 提交前必须跑

```bash
# Python 测试
cd ai-agent-service && .venv/bin/python -m pytest tests

# Python 语法检查 —— 目标是 app 包（旧命令里的 app.py 已失效，会直接报错）
cd ai-agent-service && .venv/bin/python -m compileall agents graphs rag schemas tools repositories services app

# Java 编译与测试
cd business-service && mvn -q -DskipTests compile && mvn test

# 前端类型检查（改前端必跑）
cd frontend-vue && npm run typecheck
```

改动涉及接口时追加契约比对：

```bash
python3 -c "
import json
s=json.load(open('docs/_baseline/baseline-openapi.json'))
ops=[(m.upper(),p) for p,v in s['paths'].items() for m in v if m in ('get','post','put','patch','delete')]
print('paths',len(s['paths']),'operations',len(ops))
"
```

期望输出 `paths 51 operations 52`。不一致就说明契约变了，必须更新 `docs/API.md` 与基线文件。

## 5. 测试规范

Python 测试放 `ai-agent-service/tests/`，`pytest`，命名 `test_<模块>.py`；Java 测试放 `business-service/src/test/java`；前端改动至少 `npm run typecheck`。

必须覆盖的场景：

- 登录鉴权与会话隔离（含越权访问返回 403）；
- 意图识别、风险路由、人工接管判定，以及 `_apply_business_guardrails` 对 LLM 结果的改写；
- RAG 检索、引用、有据性、幻觉样本，以及"规则咨询不得误触发写操作"的分流；
- 工具调用成功/失败/超时/熔断/降级；
- Redis Stream 入队、ACK、Pending 恢复、重试、DLQ、幂等去重；
- `/api/agent/reply`、SSE、`/api/agent/replies/{id}` 三者结果一致性；
- 工单创建幂等、状态流转、人工降级；
- 系统监控指标与敏感信息过滤。

用 monkeypatch 替换单例时，必须 `monkeypatch.setattr(deps, "chat_messages", ...)`（属性方式），不要试图替换 import 进来的局部名字。

## 6. 编码与注释规范

UTF-8；Python 4 空格缩进、优先类型提示、`snake_case` 函数/模块、`PascalCase` 类与 Pydantic 模型；Java 遵循 Spring 约定，包统一在 `com.example.business` 下。

**注释必须中文**，不写英文注释。Python 用中文 docstring，Java 用 Javadoc 风格：

- 核心类/函数、Agent 节点、工具调用、RAG 链路、队列状态流转、降级逻辑必须说明**业务职责**；
- 关键条件判断、状态流转、权限校验、数据库查询、队列 ACK/重试/DLQ、幂等创建要有简洁行内注释，解释**为什么**这样做，禁止"处理数据""执行逻辑"这类空话。

放置约定：LangGraph 节点进 `graphs/`，LangChain 链路进 `agents/` 或 `rag/`，外部系统调用进 `tools/`，横切能力进 `services/`。

## 7. 文档纪律

权威文档只有 5 个位置：`README.md`、`docs/ARCHITECTURE.md`、`docs/API.md`、`docs/RUNBOOK.md`、`docs/ADR/`。

- **不要**新建 `docs/xxx说明.md`、`docs/xxx总结.md`、`docs/xxx报告.md` 这类平行文档；内容属于哪一类就并进对应权威文档。
- 一次性调研/评测/交付产物放 `archive/产品与研究产物/`，并在其中说明其非权威。
- 改状态机 → 先改 `ARCHITECTURE.md` 第 4 节；改接口 → 改 `API.md` + 基线 spec；改启动步骤 → 只改 `README.md` 与 `RUNBOOK.md`，不要在多处重复。
- 本节（AGENTS.md）与代码冲突时，**以代码为准**，并顺手修正本节。

## 8. 安全与配置

- 不提交 API Key、模型凭证、客户隐私数据、`.venv/`、`node_modules/`、Docker 私有登录配置。
- 模型、RAG、Redis、PostgreSQL、业务服务地址全部走环境变量；新增变量加在 `app/core/config.py`（存量变量仍分散在各模块，见第 2 节）。
- 日志、Trace、Redis 队列、Prometheus 指标、前端监控页**不得**出现 Authorization、手机号、邮箱、地址、完整订单号、Prompt、工具原始敏感返回；业务标识必须脱敏或哈希。
- 客户侧不得展示 `risk_reasons`、`decision_type`、AI 分析 JSON、工具原始结果、`internal_suggestion`、Trace 细节或审核按钮。
- 主管/管理员功能单独扩展，不要混进客户侧页面。

## 9. 提交与 PR

约定式提交：`feat: ...` / `fix: ...` / `docs: ...` / `refactor: ...`。

PR 必含：变更摘要、影响模块、**本地实际跑过的命令**、与需求/ADR 的对应关系。改前端附截图或说明；改业务规则、Agent 流程、队列、降级、风险控制的，必须说明验证方式。

> 当前仓库由主控方统一提交，agent 不要自行执行 `git add/commit/checkout/stash`。
