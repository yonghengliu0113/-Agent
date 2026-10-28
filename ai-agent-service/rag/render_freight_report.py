"""把货运 RAG 评测明细渲染成 Markdown 评测报告与人工验收清单。

评测脚本只落 JSON，人工验收需要可读的逐题对照表：
「问题 / 目标片段 / 实际召回 / 是否命中 / 参考答案 / Agent 实际回答 / 必备事实 / 违规表述」。
"""

import argparse
import json
from pathlib import Path
from typing import Any


def _pct(value: Any) -> str:
    """把比例渲染成百分比，空值统一显示为 —。"""
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{value * 100:.1f}%"
    return str(value)


def _mark(value: Any) -> str:
    """把布尔结果渲染成便于人工扫读的标记。"""
    if value is None:
        return "—"
    return "✅" if value else "❌"


def _escape(text: Any) -> str:
    """转义 Markdown 表格中的竖线与换行，避免破坏表格结构。"""
    if text is None:
        return ""
    return str(text).replace("|", "\\|").replace("\n", "<br>")


def build_report(report: dict[str, Any], golden_path: Path) -> str:
    """生成评测报告 Markdown。"""
    baseline = report["modes"].get("baseline", {})
    agent = report["modes"].get("agent", {})
    bm = baseline.get("metrics", {})
    am = agent.get("metrics", {})

    lines: list[str] = []
    lines.append("# 货运知识库 RAG 评测报告")
    lines.append("")
    lines.append(f"- 黄金集：`{golden_path.name}`（{bm.get('total', am.get('total', '—'))} 题）")
    lines.append("- 知识库：`ai-agent-service/data/kb_sources`（6 个货运业务域 + 原有 8 个售后业务域）")
    lines.append("- 检索后端：内存 BM25 + 规则 rerank（`RAG_STORE_BACKEND=memory`）")
    lines.append("- 生成后端：真实 `CustomerServiceAgent` + DeepSeek（agent 模式）")
    lines.append("")

    lines.append("## 一、总览指标")
    lines.append("")
    lines.append("| 指标 | baseline（纯检索） | agent（端到端真实回答） | 说明 |")
    lines.append("| --- | --- | --- | --- |")
    rows = [
        ("题目数", "total", "total", "评测样本总数"),
        ("片段级 hit@1", "chunk_hit@1", "chunk_hit@1", "第 1 条引用就是讲该规则的那一小节"),
        ("片段级 hit@3", "chunk_hit@3", "chunk_hit@3", "前 3 条引用覆盖到该小节"),
        ("文档级 hit@1", "hit@1", "hit@1", "第 1 条引用来自目标文档（同域内恒真，仅作参考）"),
        ("必备关键词命中率", "must_contain_hit_rate", "must_contain_hit_rate", "前 3 条引用包含全部必备关键词"),
        ("上下文精确率", "context_precision", "context_precision", "引用中属于目标文档的比例"),
        ("上下文召回率", "context_recall", "context_recall", "目标文档是否被召回"),
        ("必备事实覆盖率", "required_fact_coverage", "required_fact_coverage", "回答是否覆盖全部必备事实"),
        ("答案有据性", "answer_groundedness", "answer_groundedness", "回答是否由引用支撑"),
        ("引用精确率", "citation_precision", "citation_precision", "回答引用中可被知识库支撑的比例"),
        ("引用召回率", "citation_recall", "citation_recall", "知识库事实被回答引用的比例"),
        ("幻觉样本数", "hallucination_count", "hallucination_count", "出现无引用支撑表述的样本数"),
        ("失败样本数", "failed_count", "failed_count", "命中任一失败判定的样本数"),
        ("平均生成耗时(ms)", "avg_generation_latency_ms", "avg_generation_latency_ms", "回答生成阶段耗时"),
    ]
    for label, bkey, akey, note in rows:
        lines.append(f"| {label} | {_fmt_metric(bm, bkey)} | {_fmt_metric(am, akey)} | {note} |")
    lines.append("")
    lines.append("> 说明：文档级、集合级、业务域级指标在同一业务域内天然为 100%，")
    lines.append("> 因为同一业务域下的片段必然同文档、同集合、同风险等级。")
    lines.append("> 判断检索质量应以**片段级 hit@1 / hit@3** 为准。")
    lines.append("")

    if agent:
        lines.append("## 二、端到端回答质量")
        lines.append("")
        total = am.get("total") or 0
        ok = int(round((am.get("required_fact_coverage") or 0) * total))
        lines.append(f"- 必备事实完整覆盖：{ok}/{total} 题")
        lines.append(f"- 答案有据性均值：{_fmt_metric(am, 'answer_groundedness')}")
        lines.append(f"- 被判为幻觉的样本：{am.get('hallucination_count')} 题")
        lines.append(f"- 失败样本：{am.get('failed_count')} 题")
        lines.append("")
        lines.append("失败原因分布：")
        lines.append("")
        lines.append("| 失败类型 | 题数 |")
        lines.append("| --- | --- |")
        for reason, count in _failure_histogram(agent).items():
            lines.append(f"| {reason} | {count} |")
        lines.append("")

    lines.append("## 三、分业务域结果")
    lines.append("")
    lines.append("| 业务域 | 题数 | 片段级 hit@1 | 片段级 hit@3 | 必备事实覆盖 | 有据性 | 幻觉题数 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for scope, rows in _group_by_scope(baseline, agent).items():
        total = len(rows)
        h1 = sum(1 for _, b, _ in rows if b.get("top1_heading_hit")) / total
        h3 = sum(1 for _, b, _ in rows if b.get("top3_heading_hit")) / total
        facts = [a.get("required_facts_complete") for _, _, a in rows if a]
        faith = [a.get("faithfulness") for _, _, a in rows if a and a.get("faithfulness") is not None]
        hall = sum(1 for _, _, a in rows if a and "unsupported_claim" in a.get("failures", []))
        lines.append(
            "| {} | {} | {} | {} | {} | {} | {} |".format(
                _escape(scope),
                total,
                _pct(h1),
                _pct(h3),
                _pct(sum(1 for item in facts if item) / len(facts)) if facts else "—",
                _pct(sum(faith) / len(faith)) if faith else "—",
                hall if facts else "—",
            )
        )
    lines.append("")

    lines.append("## 四、评测口径与已知局限")
    lines.append("")
    lines.append("**知识点来源**：知识库 6 份货运文档全部来自公开权威来源，")
    lines.append("包括海关总署令第 277 号/第 252 号、关税法、《超限运输车辆行驶公路管理规定》、")
    lines.append("GB 12268-2025、GB 6944-2025、GB 31605-2020、《疫苗储存和运输管理规范》、")
    lines.append("《药品经营质量管理规范》、SOLAS/IMDG、IATA 危险品规则第 67/68 版、")
    lines.append("蒙特利尔公约、CMR、CIM、海商法、民法典、快递暂行条例，")
    lines.append("以及顺丰、德邦、跨越速运、安能、马士基、中远海运、东方海外、赫伯罗特、达飞等企业官网。")
    lines.append("每条事实均在知识库正文中标注来源与版本日期，未取到权威来源的条目（如德邦/安能抛比系数、")
    lines.append("京东保价费率、部分司法解释原文）**刻意留空未写**。")
    lines.append("")
    lines.append("**指标口径局限**（阅读数据时请注意）：")
    lines.append("")
    lines.append("1. `chunk_hit@1/@3` 的「目标片段」由人工逐题标注（依据问题真正想问的规则小节），")
    lines.append("   并用脚本校验该片段确实包含本题的必备关键词，避免标注与事实脱节。")
    lines.append("2. `answer_groundedness` 与 `hallucination_count` 来自纯规则校验：")
    lines.append("   仅做中文二元词与数字的词面支持判断，**不理解语义**。")
    lines.append("   它能抓住伪造引用 ID 与凭空数字，但对「要求…／不再要求…」这类正反改写不敏感，")
    lines.append("   因此存在漏判（把错答判成有据）。如需语义级结论，应另跑 LLM 裁判（`--llm-judge`）。")
    lines.append("3. `required_fact_coverage` 按参考答案里的必备事实字符串匹配，")
    lines.append("   回答用同义改写时可能被判缺失，属于偏严口径。")
    lines.append("4. 检索指标在同域内与文档级指标重复，判断检索质量只需看片段级指标。")
    lines.append("")
    lines.append("**本次暴露并已修复的系统缺陷**：")
    lines.append("")
    lines.append("| # | 缺陷 | 影响 | 修复 |")
    lines.append("| --- | --- | --- | --- |")
    lines.append("| 1 | 在线 Agent 的内存知识库只加载 8 条内置示例，从不读 `data/kb_sources` | 新知识库对线上 Agent 完全不可见，只有离线评测能命中 | 抽出 `rag/kb_loader.py`，在线检索、离线评测、pgvector 入库共用同一加载逻辑 |")
    lines.append("| 2 | `infer_business_scope` 调用时未传原消息 | 货运问题一律落到通用物流域，只召回 1 条无关片段 | 检索节点传入原始消息，按货运术语细分到专业域 |")
    lines.append("| 3 | BM25 只对正文计分，不含小节标题 | 「XX 是什么版本」这类问题命中不到只写在标题里的关键词 | 标题路径按两倍权重计入 BM25 |")
    lines.append("| 4 | query rewrite 补充的业务域词与客户原话等权 | 通用词压过实词，正确片段被排到第 5 位 | 补充词按 0.25 权重折算 |")
    lines.append("| 5 | 意图识别把货运规则问题判成 `out_of_scope` | 直接跳过知识库，用模型记忆回答（出现错误系数 6000/8000） | 意图与业务范围关键词统一取自同一份货运术语表 |")
    lines.append("| 6 | 物流意图被无条件改成 `status_query` 并要求订单号 | 规则咨询被拒答为「请提供订单号」 | 仅在出现实时查单信号时才按查单处理 |")
    lines.append("| 7 | `how_to` 分支硬编码「如何查询物流」模板 | 「电放怎么申请」被答成查物流步骤 | 有知识库证据时优先基于证据回答 |")
    lines.append("| 8 | 引用校验把并列分句的引用标记误判为缺失 | 正确回答被计为幻觉，指标失真 | 支持判定改为以本轮召回证据为准；引用精确率改为按引用 ID 计算 |")
    lines.append("| 9 | 违规表述检查不识别否定语境 | 「不再需要核销单」被误判为违规 | 增加否定前缀判断 |")
    lines.append("")
    lines.append("## 五、逐题明细")
    lines.append("")
    lines.append("### 5.1 检索（baseline）")
    lines.append("| # | 问题 | 业务域 | 目标片段 | 实际 top1 | top1命中 | top3命中 | 失败原因 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for index, row in enumerate(baseline.get("rows", []), start=1):
        sample = row["sample"]
        actual = row["actual"][0]["heading_path"][-1] if row["actual"] and row["actual"][0]["heading_path"] else "—"
        lines.append(
            "| {} | {} | {} | {} | {} | {} | {} | {} |".format(
                index,
                _escape(sample["query"]),
                _escape(sample.get("business_scope")),
                _escape(sample.get("expected_heading") or sample.get("expected_doc")),
                _escape(actual),
                _mark(row.get("top1_heading_hit")),
                _mark(row.get("top3_heading_hit")),
                _escape("、".join(row.get("failures", [])) or "—"),
            )
        )
    lines.append("")

    if agent:
        lines.append("### 5.2 端到端回答（agent）")
        lines.append("")
        for index, row in enumerate(agent.get("rows", []), start=1):
            sample = row["sample"]
            lines.append(f"#### {index}. {sample['query']}")
            lines.append("")
            lines.append(f"- 业务域：`{sample.get('business_scope')}`　目标片段：`{sample.get('expected_heading') or '—'}`")
            lines.append(f"- 检索：top1 {'✅' if row.get('top1_heading_hit') else '❌'}　top3 {'✅' if row.get('top3_heading_hit') else '❌'}")
            lines.append(f"- 必备事实完整：{_mark(row.get('required_facts_complete'))}　有据性：{row.get('faithfulness')}")
            if row.get("missing_required_facts"):
                lines.append(f"- 缺失事实：{_escape('；'.join(row['missing_required_facts']))}")
            if row.get("forbidden_claims"):
                lines.append(f"- ⚠️ 违规表述：{_escape('；'.join(row['forbidden_claims']))}")
            lines.append(f"- 参考答案：{_escape(sample.get('reference_answer'))}")
            lines.append(f"- Agent 回答：{_escape(row.get('generated_answer'))}")
            lines.append("")
    return "\n".join(lines)


def _group_by_scope(baseline: dict[str, Any], agent: dict[str, Any]) -> dict[str, list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]]:
    """按业务域聚合 baseline 与 agent 的逐题结果，便于定位哪个知识域最弱。"""
    agent_rows = {row["sample"]["query"]: row for row in agent.get("rows", [])}
    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]] = {}
    for row in baseline.get("rows", []):
        scope = row["sample"].get("business_scope") or "other"
        grouped.setdefault(scope, []).append((row["sample"], row, agent_rows.get(row["sample"]["query"], {})))
    return grouped


def _fmt_metric(metrics: dict[str, Any], key: str) -> str:
    """按指标类型格式化：计数显示整数，耗时显示毫秒，其余比例显示百分比。"""
    if key not in metrics:
        return "—"
    value = metrics[key]
    if value is None:
        return "—"
    if key in {"total", "failed_count", "hallucination_count", "no_hit_count", "llm_judged_count"}:
        return str(value)
    if key.endswith("_ms"):
        return f"{float(value):.0f}"
    if isinstance(value, float):
        return _pct(value)
    return str(value)


def _failure_histogram(mode: dict[str, Any]) -> dict[str, int]:
    """统计失败原因分布，便于定位系统性问题。"""
    histogram: dict[str, int] = {}
    for row in mode.get("rows", []):
        for reason in row.get("failures", []):
            histogram[reason] = histogram.get(reason, 0) + 1
    return dict(sorted(histogram.items(), key=lambda item: -item[1]))


def build_checklist(report: dict[str, Any]) -> str:
    """生成人工验收清单，供逐题核对 Agent 回答是否满足业务口径。"""
    baseline = report["modes"].get("baseline", {})
    agent = report["modes"].get("agent", {})
    bm = baseline.get("metrics", {})
    am = agent.get("metrics", {})
    total = bm.get("total", am.get("total", 0))

    lines: list[str] = []
    lines.append("# 货运知识库 RAG 效果验收清单")
    lines.append("")
    lines.append(f"共 {total} 道题，按业务域分组。请逐题核对「Agent 回答」是否符合「参考答案」的业务口径。")
    lines.append("")
    lines.append("## 验收前必读")
    lines.append("")
    lines.append("1. 知识库内容全部来自公开权威来源（法规、国家标准、国际公约、承运商官网），每段末尾标注来源。")
    lines.append("2. 参考答案是知识库正文的忠实概括，不是凭常识补写；知识库未覆盖的内容不会出现。")
    lines.append("3. 标注「未找到权威来源」的条目（如德邦/安能抛比系数、京东保价费率）刻意未写入知识库。")
    lines.append("4. 危险品与理赔属于高风险域，Agent 不应自行承诺处罚金额或赔付结论。")
    lines.append("")

    lines.append("## 一、验收结论表")
    lines.append("")
    lines.append("| 验收项 | 结果 | 达标建议 |")
    lines.append("| --- | --- | --- |")
    lines.append(f"| 检索片段级 hit@1 | {_fmt_metric(bm, 'chunk_hit@1')} | ≥ 80% |")
    lines.append(f"| 检索片段级 hit@3 | {_fmt_metric(bm, 'chunk_hit@3')} | ≥ 90% |")
    lines.append(f"| 必备关键词命中率 | {_fmt_metric(bm, 'must_contain_hit_rate')} | ≥ 95% |")
    lines.append(f"| Agent 必备事实覆盖率 | {_fmt_metric(am, 'required_fact_coverage')} | ≥ 80% |")
    lines.append(f"| Agent 答案有据性 | {_fmt_metric(am, 'answer_groundedness')} | ≥ 0.8 |")
    lines.append(f"| 幻觉样本数 | {_fmt_metric(am, 'hallucination_count')} | 尽量为 0 |")
    lines.append("")

    lines.append("## 二、逐题验收")
    lines.append("")
    agent_rows = {row["sample"]["query"]: row for row in agent.get("rows", [])}
    base_rows = {row["sample"]["query"]: row for row in baseline.get("rows", [])}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in baseline.get("rows", []):
        grouped.setdefault(row["sample"].get("business_scope", "other"), []).append(row)

    index = 0
    for scope, rows in grouped.items():
        lines.append(f"### {scope}")
        lines.append("")
        for row in rows:
            index += 1
            sample = row["sample"]
            arow = agent_rows.get(sample["query"], {})
            lines.append(f"**{index}. {sample['query']}**")
            lines.append("")
            lines.append(f"- 目标片段：`{sample.get('expected_heading') or '—'}`")
            lines.append(f"- 检索 top1 命中：{_mark(row.get('top1_heading_hit'))}")
            lines.append(f"- 参考答案：{_escape(sample.get('reference_answer'))}")
            if arow:
                lines.append(f"- Agent 回答：{_escape(arow.get('generated_answer'))}")
                lines.append(f"- 必备事实完整：{_mark(arow.get('required_facts_complete'))}")
                if arow.get("missing_required_facts"):
                    lines.append(f"- 缺失事实：{_escape('；'.join(arow['missing_required_facts']))}")
                if arow.get("forbidden_claims"):
                    lines.append(f"- ⚠️ 违规表述：{_escape('；'.join(arow['forbidden_claims']))}")
            lines.append(f"- 人工验收结论：☐ 通过　☐ 部分通过　☐ 不通过　　备注：____________")
            lines.append("")
    return "\n".join(lines)


def main() -> None:
    """命令行入口：从评测 JSON 渲染报告与验收清单。"""
    parser = argparse.ArgumentParser(description="Render freight RAG evaluation report and acceptance checklist.")
    parser.add_argument("--report", default="data/rag_eval/report_freight.json")
    parser.add_argument("--golden", default="data/rag_eval/golden_freight_v1.jsonl")
    parser.add_argument("--out", default="../../docs/rag-eval")
    args = parser.parse_args()

    payload = json.loads(Path(args.report).read_text(encoding="utf-8"))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    report_md = build_report(payload, Path(args.golden))
    (out_dir / "货运RAG评测报告.md").write_text(report_md, encoding="utf-8")

    checklist_md = build_checklist(payload)
    (out_dir / "货运RAG验收清单.md").write_text(checklist_md, encoding="utf-8")
    print(f"已生成报告与验收清单到 {out_dir}")


if __name__ == "__main__":
    main()
