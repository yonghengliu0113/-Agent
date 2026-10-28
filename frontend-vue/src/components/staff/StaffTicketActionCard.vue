<script setup lang="ts">
import { Check, Close, UserFilled } from '@element-plus/icons-vue'

/**
 * 工单处理操作卡：领取/开始/关闭工单、生成客户话术草稿并确认发送。
 * 模板生成状态会明确区分大模型草稿与安全兜底，避免座席误判。
 */
defineProps<{
  canOperate: boolean
  canClaim: boolean
  acting: boolean
  closeReason: string
  draftMessage: string
  draftGenerationMode: 'llm' | 'fallback' | null
  draftFallbackReason: string | null
  generatingDraft: boolean
}>()

const emit = defineEmits<{
  'update:closeReason': [value: string]
  'update:draftMessage': [value: string]
  claim: []
  start: []
  close: []
  'generate-draft': []
  'send-reply': []
}>()
</script>

<template>
  <el-card shadow="never">
    <template #header>处理操作</template>
    <el-form label-position="top">
      <el-alert
        v-if="!canOperate && !canClaim"
        title="该工单不在你名下，不能处理。"
        :closable="false"
        type="warning"
      />
      <el-alert
        v-else-if="canClaim"
        title="该工单待分派：请先点击“领取工单”，领取后才能开始处理或关闭工单。"
        :closable="false"
        type="info"
      />
      <div class="action-row">
        <el-button v-if="canClaim" :icon="UserFilled" :loading="acting" type="primary" @click="emit('claim')">
          领取工单
        </el-button>
        <el-button :disabled="!canOperate" :icon="Check" :loading="acting" @click="emit('start')">开始处理</el-button>
        <el-button :disabled="!canOperate" :icon="Close" :loading="acting" type="danger" @click="emit('close')">
          关闭工单
        </el-button>
      </div>

      <el-divider />
      <el-form-item label="处理结果">
        <el-input
          :model-value="closeReason"
          :disabled="!canOperate"
          :rows="3"
          type="textarea"
          @update:model-value="emit('update:closeReason', String($event))"
        />
      </el-form-item>
      <el-button :disabled="!canOperate || generatingDraft" :loading="generatingDraft" @click="emit('generate-draft')">
        {{ generatingDraft ? '正在基于工单事实生成…' : '生成客户话术草稿' }}
      </el-button>
      <p v-if="generatingDraft" class="draft-generating-hint">正在结合工单处理结果、客户诉求和最近会话生成草稿，通常几秒内完成。</p>
      <el-alert
        v-else-if="draftGenerationMode === 'llm'"
        class="draft-generation-status"
        :closable="false"
        show-icon
        title="已使用大模型结合工单事实与最近会话生成草稿，请在发送前确认具体处理边界。"
        type="success"
      />
      <el-alert
        v-else-if="draftGenerationMode === 'fallback'"
        class="draft-generation-status"
        :closable="false"
        show-icon
        :title="`本次模型草稿未生成（${draftFallbackReason || '暂时不可用'}），当前内容为安全兜底模板；可稍后重新生成或手动编辑。`"
        type="warning"
      />
      <el-form-item class="reply-editor" label="客户可见内容">
        <el-input
          :model-value="draftMessage"
          :disabled="!canOperate || generatingDraft"
          :rows="8"
          placeholder="请先生成草稿，或直接填写要发送给客户的处理说明。"
          type="textarea"
          @update:model-value="emit('update:draftMessage', String($event))"
        />
      </el-form-item>
      <el-button :disabled="!canOperate || generatingDraft" type="primary" @click="emit('send-reply')">确认发送给客户</el-button>
    </el-form>
  </el-card>
</template>
