# 0001 FastAPI 装配层拆分与单例访问约定

- 状态：已采纳
- 日期：2026-10

## 背景

`ai-agent-service/app.py` 曾经是 1657 行的单文件：路由、中间件、单例构建、业务辅助函数、生命周期全部混在一起。后果是：

- 任何路由改动都要在巨型文件里定位，review 成本高；
- 单例在模块顶层直接用 `from app import chat_messages` 按值导入，测试里 `monkeypatch` 打不进去，出现"测试通过但断言的是旧对象"的假阳性；
- 环境变量读取散落在各处，无法回答"这个服务到底依赖哪些配置"；
- Worker 进程想复用执行逻辑时被迫 import HTTP 层。

## 决策

按"装配 / 配置 / 路由 / 辅助"四层拆成 `app/` 包，且 `uvicorn app:app` 入口保持不变（`app/__init__.py` 只导出实例）：

- `app/main.py`（97 行）只做装配：中间件、生命周期、`include_router`；
- `app/deps.py`（54 行）集中构建进程级单例；
- `app/core/config.py`（13 行）是环境变量的唯一出口；
- `app/api/helpers.py`（468 行）收纳 31 个跨路由辅助函数；
- `app/api/routers/` 按职责分成 8 个模块，共 54 路由。

配套两条硬性约定：

1. **单例与 helper 一律按模块属性访问**（`deps.chat_messages`、`helpers._current_login_user`），禁止按值 import。
2. **环境变量只在 `config.py` 读取**，其它模块通过 `config.XXX` 访问。

## 后果

正面：

- 测试可以真正替换单例，`monkeypatch.setattr(deps, "chat_messages", ...)` 生效；
- `main.py` 稳定在百行内，新增路由只改 `routers/`；
- 配置项有了唯一清单，`grep os.getenv` 不会再散落；
- Worker 复用的是 `services/agent_execution_service.py`，不再依赖 HTTP 层。

代价与约束：

- 新人必须理解"属性访问"约定，写成按值 import 不会立刻报错，只会让测试悄悄失效——**这是本决策最大的隐性风险**，PR review 必须专门看 `from app.deps import` 和 `from app.api.helpers import`。
- 路由数从单文件时代起固定为 54（OpenAPI 52），拆分本身不改契约，但基线 spec 需要随每次改动比对。
- `helpers.py` 已经 468 行，继续膨胀就应再拆；当前拆分会牵动大量 monkeypatch 点，暂不做。
