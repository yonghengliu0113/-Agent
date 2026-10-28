"""集中式配置：环境变量只允许在本模块读取，其它模块通过 config.XXX 访问。"""
from pathlib import Path
import os

BUSINESS_SERVICE_URL = os.getenv("BUSINESS_SERVICE_URL", "http://localhost:8081")

AGENT_INTERNAL_SECRET = os.getenv("AGENT_INTERNAL_SECRET", "enterprise-customer-agent-demo-internal-secret")

startup_ready_file = os.getenv("AGENT_STARTUP_READY_FILE", "").strip()

UPLOAD_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "uploads"

MAX_ATTACHMENT_BYTES = int(os.getenv("MAX_ATTACHMENT_BYTES", str(10 * 1024 * 1024)))
