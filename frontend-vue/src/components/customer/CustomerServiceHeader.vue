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
  <header class="cx-pagehead">
    <h1 class="cx-pagehead__title">智能客服</h1>
    <span v-if="agentStatus?.llm?.enabled" class="ws-tag ws-tag--ok">AI 已就绪</span>
    <div class="cx-pagehead__actions">
      <el-button :icon="Refresh" :loading="loadingWorkspace" @click="emit('refresh')">刷新</el-button>
      <el-button :icon="Plus" :loading="creatingSession" type="primary" @click="emit('create')">新建咨询</el-button>
      <el-button :icon="Clock" @click="emit('open-history')">历史咨询</el-button>
    </div>
  </header>
</template>
