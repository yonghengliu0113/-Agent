<script setup lang="ts">
import { Clock, Plus, Refresh } from '@element-plus/icons-vue'

import type { AgentStatus } from '@/types/api'

/**
 * 智能客服页头部：标题、LLM 状态提示与刷新/新建/历史咨询操作。
 * 只负责展示与事件上抛，具体请求由父页面处理。
 */
defineProps<{
  agentStatus: AgentStatus | null
  loadingWorkspace: boolean
  creatingSession: boolean
}>()

const emit = defineEmits<{
  refresh: []
  create: []
  'open-history': []
}>()
</script>

<template>
  <header class="customer-hero customer-page-header">
    <div>
      <h1>客户自助服务</h1>
      <p>
        7×24 小时智能客服 · 订单、物流、售后随时问
        <span v-if="agentStatus?.llm?.enabled"> · LLM {{ agentStatus.llm.provider }}</span>
      </p>
    </div>
    <div class="hero-actions customer-page-header-actions">
      <el-button :icon="Refresh" :loading="loadingWorkspace" @click="emit('refresh')">刷新</el-button>
      <el-button :icon="Plus" :loading="creatingSession" type="primary" @click="emit('create')">新建咨询</el-button>
      <el-button :icon="Clock" @click="emit('open-history')">历史咨询</el-button>
    </div>
  </header>
</template>
