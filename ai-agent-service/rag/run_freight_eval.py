"""货运知识库 RAG 评测脚本：分模式跑检索与真实 Agent，输出逐题明细。

项目内置的 rag.evaluate 只输出聚合指标和失败样本，人工验收需要逐题看到
「问题 / 期望文档 / 实际召回 / 实际回答 / 缺失事实 / 是否通过」，
因此这里复用同一套评测函数，额外落盘逐题明细供报告与验收清单使用。
"""

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from rag.evaluate import evaluate


def run(
    *,
    eval_dir: str,
    kb_dir: str,
    golden_file: str,
    output: str,
    modes: list[str],
    top_k: int = 5,
    max_workers: int = 3,
    llm_judge: bool = False,
) -> dict[str, Any]:
    """按模式运行评测并写出逐题明细 JSON。

    真实 Agent 模式会调用线上 Agent（含模型与工具），因此单独隔离目录，
    避免与基线报告互相覆盖。
    """
    eval_root = Path(eval_dir)
    golden_path = eval_root / golden_file
    if not golden_path.is_file():
        raise FileNotFoundError(f"黄金集不存在: {golden_path}")

    # 评测只需要本次黄金集，用系统临时目录暂存，避免把中间文件留在 data/rag_eval 下
    # 被在线评测接口当成正式黄金集重复统计。
    staging = Path(tempfile.mkdtemp(prefix="freight_eval_"))
    (staging / golden_file).write_text(golden_path.read_text(encoding="utf-8"), encoding="utf-8")

    judge = None
    if llm_judge:
        from rag.quality import build_llm_judge_from_env

        judge = build_llm_judge_from_env()

    report: dict[str, Any] = {"golden_file": golden_file, "top_k": top_k, "modes": {}}
    for mode in modes:
        result = evaluate(
            eval_dir=str(staging),
            kb_dir=kb_dir,
            top_k=top_k,
            backend="memory",
            judge=judge,
            generation_mode=mode,
            max_workers=max_workers if mode == "agent" else 1,
        )
        report["modes"][mode] = result
        print(f"[{mode}] 完成：total={result['metrics']['total']} failed={result['metrics']['failed_count']}")

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(staging, ignore_errors=True)
    print(f"逐题明细已写入: {output_path}")
    return report


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="Run freight KB RAG evaluation with per-question detail.")
    parser.add_argument("--eval-dir", default="data/rag_eval")
    parser.add_argument("--kb-dir", default="data/kb_sources")
    parser.add_argument("--golden-file", default="golden_freight_v1.jsonl")
    parser.add_argument("--output", default="data/rag_eval/report_freight.json")
    parser.add_argument("--modes", default="baseline,agent", help="逗号分隔：baseline / agent")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--llm-judge", action="store_true")
    args = parser.parse_args()
    run(
        eval_dir=args.eval_dir,
        kb_dir=args.kb_dir,
        golden_file=args.golden_file,
        output=args.output,
        modes=[item.strip() for item in args.modes.split(",") if item.strip()],
        top_k=args.top_k,
        max_workers=args.workers,
        llm_judge=args.llm_judge,
    )


if __name__ == "__main__":
    main()
