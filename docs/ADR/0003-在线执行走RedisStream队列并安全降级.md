# 0003 在线执行走 Redis Stream 队列并默认安全降级

- 状态：已采纳
- 日期：2026-10

## 背景

一次 Agent 回复要串行做：LLM 意图识别 → 订单查询 → RAG 检索 → 风险校验 → 可能建单 → LLM 生成话术，实测平均生成耗时约 2 秒，尾部被模型限流拉长到十几秒。

如果把这一切放在 FastAPI 请求线程里同步跑，后果是：任何一个模型 429 都会把 API worker 占满，一两个慢请求就能拖垮整个副本，且无法优雅兜底。

## 决策

- **API 进程只做轻活**：鉴权、限流、参数校验、入队、SSE 编排、结果查询。真实 LLM/RAG/工具执行由独立的 `agent-worker` 进程消费 Redis Stream 完成。
- `AGENT_EXECUTION_QUEUE_ENABLED=true` 时 `/api/agent/reply/stream` 立即返回 `accepted`，随后 SSE 推进 `queued → generating → completed`，异常分支为 `degraded`。
- 队列本身承担可靠性：ACK、Pending 恢复、失败重试、死信队列、幂等去重。
- **两层并发保护**（`services/runtime_protection.py`）：全局 `AGENT_MAX_CONCURRENCY`（默认 20）、单主体 `AGENT_PER_SUBJECT_CONCURRENCY`（默认 2）；多副本用 Redis 准入（TTL 默认 90 秒）。
- **超时即降级**：队列等待超过 30 秒、并发超限、模型超时/429/熔断，一律返回安全降级话术，而不是继续排队硬扛。
- 评测（DeepEval）必须独立 Worker，绝不部署在 API Pod 内。

## 后果

正面：

- API 副本可以按 HTTP 并发扩容，Worker 按模型配额单独扩容，两者解耦；
- 单个慢模型不会占满 API 线程；
- 降级是**有指标的一次决策**（`agent_degraded_total{reason}`），而不是静默超时；
- 取消请求有明确语义（`/api/agent/replies/{id}/cancel` + 取消耗时指标）。

代价与未完成项：

- 架构复杂度上升：多了一个必须监控的组件（Worker）和一个必须运维的依赖（Redis）。Worker 挂了表现为"请求一直 `queued`"，是当前最常见的故障。
- **Redis Stream 目前只有 XACK，没有消费后 `XDEL`/`XTRIM` 与留存策略**，长期运行 Stream 会持续增长；这是已知限制，上生产前必须补。
- 队列等待期间的状态机（`accepted/queued/generating/completed/degraded`）是前端必须严格遵守的契约，改动会影响所有客户端。
- 未设置 `AGENT_EXECUTION_QUEUE_ENABLED` 时会退化为同步执行——便于本地开发，但**不能**用于生产。

## 备选方案与放弃原因

- 纯同步 + 线程池：429 时无法隔离，慢请求拖垮副本，放弃。
- 只做限流不做队列：无法表达"排队中"给用户，也无法在队列层做重试与死信，放弃。
