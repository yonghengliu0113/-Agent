#!/usr/bin/env python3
"""macOS 本地部署启动器：用独立会话（setsid）拉起全部服务，使其脱离调用方 shell。

为什么需要它：start-local.sh 用 `nohup ... &`，只忽略 SIGHUP，进程仍留在调用方的
进程组里。一旦调用方 shell 退出/被清理，整个进程组会一起被终止，服务随之消失。
这里用 start_new_session=True 让每个服务进入独立会话，做到真正后台常驻。
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / ".tools"
LOGS = ROOT / ".logs"
LOGS.mkdir(exist_ok=True)

JAVA_HOME = TOOLS / "jdk-17.0.20.1+1" / "Contents" / "Home"
MAVEN_HOME = TOOLS / "apache-maven-3.9.16"
REDIS_SRC = TOOLS / "redis-7.2.9"
NODE_BIN = Path.home() / ".nvm" / "versions" / "node" / "v22.22.1" / "bin"
M2 = TOOLS / "m2repo"
SETTINGS = TOOLS / "settings.xml"

ENV = {
    **os.environ,
    "JAVA_HOME": str(JAVA_HOME),
    "PATH": f"{JAVA_HOME}/bin:{MAVEN_HOME}/bin:{NODE_BIN}:" + os.environ.get("PATH", ""),
}


def start(name: str, cmd: list[str], cwd: Path) -> None:
    """以独立会话启动进程，stdout/stderr 写入 .logs/<name>.log。"""
    log = open(LOGS / f"{name}.log", "ab", buffering=0)
    subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=ENV,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        start_new_session=True,   # ← 关键：setsid，脱离调用方进程组
        close_fds=True,
    )
    print(f"  已拉起 {name}")


def http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except (urllib.error.URLError, OSError):
        return False


def wait(url: str, label: str, seconds: int) -> bool:
    for _ in range(seconds):
        if http_ok(url):
            print(f"  {label} OK")
            return True
        time.sleep(1)
    print(f"  {label} 未就绪，见 .logs/")
    return False


def tcp_ok(port: int) -> bool:
    import socket

    with socket.socket() as s:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    print("== 1/5 Redis ==")
    if not tcp_ok(6379):
        start("redis", [str(REDIS_SRC / "src" / "redis-server"), "--port", "6379",
                        "--save", "", "--appendonly", "no"], REDIS_SRC)
        time.sleep(2)
    print("  Redis OK" if tcp_ok(6379) else "  Redis 失败")

    print("== 2/5 Java business-service (8081) ==")
    if not http_ok("http://127.0.0.1:8081/actuator/health"):
        start("java", ["mvn", "-q", "-DskipTests", f"-Dmaven.repo.local={M2}",
                       "-s", str(SETTINGS), "spring-boot:run"], ROOT / "business-service")
    wait("http://127.0.0.1:8081/actuator/health", "Java", 90)

    print("== 3/5 Agent API (8000) ==")
    if not http_ok("http://127.0.0.1:8000/health"):
        start("agent-api", [".venv/bin/uvicorn", "app:app", "--host", "127.0.0.1",
                            "--port", "8000"], ROOT / "ai-agent-service")
    wait("http://127.0.0.1:8000/health", "Agent API", 40)

    print("== 4/5 Agent Worker ==")
    if subprocess.run(["pgrep", "-f", "rag.agent_execution_worker"],
                      capture_output=True).returncode != 0:
        start("agent-worker", [".venv/bin/python", "-m", "rag.agent_execution_worker"],
              ROOT / "ai-agent-service")
        time.sleep(3)
    print("  Worker OK")

    print("== 5/5 Vue (5173) ==")
    if not http_ok("http://127.0.0.1:5173/"):
        start("vue", ["npm", "run", "dev"], ROOT / "frontend-vue")
    wait("http://127.0.0.1:5173/", "Vue", 45)

    print()
    print("===== 部署完成 =====")
    print("  前端      http://localhost:5173")
    print("  Agent API http://127.0.0.1:8000/health")
    print("  Java      http://127.0.0.1:8081/actuator/health")
    print("  账号      客户 demo/123456、buyer/123456 ；坐席 staff/123456、staff2/123456")
    print("  日志      .logs/*.log")
    return 0


if __name__ == "__main__":
    sys.exit(main())
