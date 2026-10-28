#!/bin/bash
# enterprise-customer-agent macOS 本地启动脚本（无 Docker）
# 依赖：.tools 下的 JDK17/Maven/Redis、ai-agent-service/.venv、frontend-vue/node_modules
# 用法：./start-local.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$ROOT/.tools"
JAVA_HOME_DIR="$TOOLS/jdk-17.0.20.1+1/Contents/Home"
MAVEN_HOME="$TOOLS/apache-maven-3.9.16"
REDIS_SRC="$TOOLS/redis-7.2.9"
export JAVA_HOME="$JAVA_HOME_DIR"
export PATH="$JAVA_HOME/bin:$MAVEN_HOME/bin:$HOME/.nvm/versions/node/v22.22.1/bin:$PATH"

LOGDIR="$ROOT/.logs"
mkdir -p "$LOGDIR"

echo "== 1/5 启动 Redis =="
if ! "$REDIS_SRC/src/redis-cli" -p 6379 ping >/dev/null 2>&1; then
  nohup "$REDIS_SRC/src/redis-server" --port 6379 --save '' --appendonly no >"$LOGDIR/redis.log" 2>&1 &
  sleep 1
fi
"$REDIS_SRC/src/redis-cli" -p 6379 ping

echo "== 2/5 启动 Java business-service (8081) =="
if ! curl -sf http://127.0.0.1:8081/actuator/health >/dev/null 2>&1; then
  (cd "$ROOT/business-service" && nohup mvn -q -DskipTests -Dmaven.repo.local="$TOOLS/m2repo" -s "$TOOLS/settings.xml" spring-boot:run >"$LOGDIR/java.log" 2>&1 &)
fi
echo "  （Java 服务冷启动约 10-30 秒，等待中……）"
for i in $(seq 1 60); do
  curl -sf http://127.0.0.1:8081/actuator/health >/dev/null 2>&1 && break
  sleep 1
done
curl -sf http://127.0.0.1:8081/actuator/health >/dev/null && echo "  Java OK" || echo "  Java 未就绪，请查看 $LOGDIR/java.log"

echo "== 3/5 启动 Agent API (8000) =="
if ! curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
  (cd "$ROOT/ai-agent-service" && nohup .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 >"$LOGDIR/agent-api.log" 2>&1 &)
  sleep 4
fi
curl -sf http://127.0.0.1:8000/health && echo " Agent API OK" || echo " Agent API 未就绪，请查看 $LOGDIR/agent-api.log"

echo "== 4/5 启动 Agent Worker =="
if ! pgrep -f "agent_execution_worker" >/dev/null 2>&1; then
  (cd "$ROOT/ai-agent-service" && nohup .venv/bin/python -m rag.agent_execution_worker >"$LOGDIR/agent-worker.log" 2>&1 &)
  sleep 3
fi
pgrep -f "agent_execution_worker" >/dev/null && echo " Worker 已启动" || echo " Worker 启动失败，请查看 $LOGDIR/agent-worker.log"

echo "== 5/5 启动 Vue 前端 (5173) =="
if ! curl -sf http://127.0.0.1:5173 >/dev/null 2>&1; then
  (cd "$ROOT/frontend-vue" && nohup npm run dev >"$LOGDIR/vue.log" 2>&1 &)
  sleep 5
fi
curl -sf http://127.0.0.1:5173 >/dev/null && echo " Vue OK" || echo " Vue 未就绪，请查看 $LOGDIR/vue.log"

echo ""
echo "===== 全部就绪 ====="
echo "前端:   http://localhost:5173"
echo "Agent:  http://localhost:8000/health"
echo "Java:   http://localhost:8081/actuator/health"
echo "账号:   客户 demo/123456、buyer/123456；坐席 staff/123456、staff2/123456"
