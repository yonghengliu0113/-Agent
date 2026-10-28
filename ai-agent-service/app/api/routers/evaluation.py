"""评测路由：RAG 黄金集评测与线上采样质量报告的异步任务入口。"""
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Header

from app import deps
from app.api import helpers
from rag.evaluate import evaluate as evaluate_rag

router = APIRouter()


@router.get("/api/staff/rag/evaluation")
def rag_evaluation(
    mode: str = "baseline",
    authorization: str | None = Header(default=None),
) -> dict:
    """运行离线 RAG 质量评测，仅向内部坐席开放，避免客户读取内部评测与失败样本。"""
    helpers._require_staff_user(authorization)
    data_dir = Path(__file__).resolve().parent / "data"
    if mode != "baseline":
        raise HTTPException(status_code=400, detail="真实 Agent 全量评测请通过后台任务接口提交")
    # 基线报告用于页面首屏和快速回归，不会触发模型或业务工具调用。
    return evaluate_rag(
        eval_dir=str(data_dir / "rag_eval"),
        kb_dir=str(data_dir / "kb_sources"),
        generation_mode="baseline",
    )


@router.post("/api/staff/rag/evaluation/jobs")
def create_rag_evaluation_job(payload: dict[str, Any] | None = None, authorization: str | None = Header(default=None)) -> dict:
    """提交全量真实 Agent 评测任务，接口立即返回，前端通过状态接口轮询结果。"""
    helpers._require_staff_user(authorization)
    requested = (payload or {}).get("max_samples")
    try:
        max_samples = int(requested) if requested is not None else None
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="样本数必须是正整数") from exc
    if max_samples is not None and not 1 <= max_samples <= 500:
        raise HTTPException(status_code=400, detail="样本数必须在 1 到 500 之间")
    return deps.evaluation_repository.create_job("GOLDEN", {"max_samples": max_samples})


@router.get("/api/staff/rag/evaluation/jobs/{job_id}")
def get_rag_evaluation_job(job_id: str, authorization: str | None = Header(default=None)) -> dict:
    """查询评测后台任务状态与完成报告，仅允许内部坐席访问。"""
    helpers._require_staff_user(authorization)
    job = deps.evaluation_repository.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="评测任务不存在或已过期")
    return job


@router.get("/api/staff/evaluation/online/report")
def online_evaluation_report(days: int = 7, limit: int = 50, authorization: str | None = Header(default=None)) -> dict:
    """读取线上采样评测监控报告；该接口不触发任何模型调用。"""
    helpers._require_staff_user(authorization)
    return deps.evaluation_repository.online_report(days=days, limit=limit)


@router.get("/api/staff/evaluation/queue")
def online_evaluation_queue(authorization: str | None = Header(default=None)) -> dict:
    """查询评测队列积压与每日预算消耗，供坐席端监控 Worker 健康度。"""
    helpers._require_staff_user(authorization)
    return deps.evaluation_repository.queue_status()
