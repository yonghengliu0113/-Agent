/**
 * RAG 质量评测域类型：引用校验、单样本评测行、评测报告与异步任务。
 * 仅在 /staff/rag-evaluation 内部页面使用。
 */

/** 引用校验指标，用于判断回答是否有据、引用是否准确。 */
export interface RagCitationValidation {
  groundedness: number
  citation_precision: number
  citation_recall: number
  hallucination_detected: boolean
  unsupported_claims: Array<{ claim: string; reason: string }>
}

/** 单条评测样本结果。 */
export interface RagEvaluationRow {
  sample: { query: string; expected_doc: string; business_scope: string }
  failures: string[]
  generated_answer: string
  citation_validation: RagCitationValidation
  missing_required_facts: string[]
}

/** 评测报告：指标汇总与失败样本。 */
export interface RagEvaluationReport {
  evaluation_mode?: 'baseline' | 'agent' | string
  metrics: Record<string, number | null>
  failures: RagEvaluationRow[]
}

/** 异步评测任务状态与结果。 */
export interface RagEvaluationJob {
  job_id: string
  status: 'PENDING' | 'PROCESSING' | 'SUCCEEDED' | 'FAILED'
  created_at: string
  started_at: string | null
  finished_at: string | null
  report: RagEvaluationReport | null
  error: string | null
  payload?: { max_samples?: number | null }
}

/** 线上采样评测报告：预算、指标与采样明细。 */
export interface OnlineEvaluationReport {
  queue: { counts: Record<string, number>; daily_budget: number; budget_used: number }
  metrics: Record<string, number | null>
  items: Array<{ trace_id: string; status: string; sampling_reason: string; created_at: string; result: { failures?: string[]; reasons?: Record<string, string> } }>
  failures: Array<{ trace_id: string; status: string; sampling_reason: string; created_at: string; result: { failures?: string[]; reasons?: Record<string, string> } }>
}
