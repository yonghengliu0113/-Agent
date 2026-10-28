<script setup lang="ts">
import type { StaffTicketContext } from '@/types/api'

/**
 * 工单 AI 决策依据卡。
 * 座席可查看本轮风险原因、知识库引用、工具调用与内部建议；
 * 该类信息仅用于内部处理，不进入客户侧展示。
 */
defineProps<{
  context: StaffTicketContext | null
  loading: boolean
}>()
</script>

<template>
  <el-card v-loading="loading" shadow="never">
    <template #header>
      <div class="card-header">
        <span>AI 决策依据</span>
        <el-tag v-if="!context || !context.ai_evidence.length" size="small" type="info">暂无 AI 记录</el-tag>
      </div>
    </template>
    <el-empty
      v-if="!context || !context.ai_evidence.length"
      :image-size="44"
      description="该工单暂无关联的 AI 决策记录"
    />
    <template v-else>
      <section v-for="evidence in context.ai_evidence" :key="evidence.message_id" class="ai-evidence">
        <div class="ai-evidence__meta">
          <el-tag size="small" :type="evidence.decision_type === 'auto_reply' ? 'success' : 'warning'">
            {{ evidence.decision_type || 'unknown' }}
          </el-tag>
          <span class="ai-evidence__time">{{ evidence.created_at || '' }}</span>
        </div>
        <p class="plain-text">{{ evidence.customer_message || '（本轮无客户可见回复）' }}</p>
        <template v-if="evidence.risk_reasons.length">
          <h4>风险原因</h4>
          <div class="ai-evidence__reasons">
            <el-tag v-for="reason in evidence.risk_reasons" :key="reason" size="small" type="danger">{{ reason }}</el-tag>
          </div>
        </template>
        <template v-if="evidence.citations.length">
          <h4>知识库引用</h4>
          <ul class="ai-evidence__citations">
            <li v-for="citation in evidence.citations" :key="citation.citation_id || citation.doc_name">
              <b>{{ citation.doc_name }}</b>
              <el-tag
                size="small"
                :type="citation.risk_level === 'high' || citation.risk_level === 'critical' ? 'danger' : 'info'"
              >{{ citation.risk_level }}</el-tag>
              <span>{{ citation.paragraph }}</span>
            </li>
          </ul>
        </template>
        <template v-if="evidence.tool_results.length">
          <h4>工具调用</h4>
          <div class="ai-evidence__tools">
            <el-tag
              v-for="tool in evidence.tool_results"
              :key="(tool.tool_name || tool.query_type || 'tool') + String(tool.status)"
              size="small"
              :type="tool.status === 'success' ? 'success' : tool.status === 'failed' ? 'danger' : 'info'"
            >{{ tool.tool_name || tool.query_type || 'tool' }} · {{ tool.status }}</el-tag>
          </div>
        </template>
        <template v-if="evidence.internal_suggestion">
          <h4>AI 内部建议</h4>
          <p class="plain-text">{{ evidence.internal_suggestion }}</p>
        </template>
      </section>
    </template>
  </el-card>
</template>
