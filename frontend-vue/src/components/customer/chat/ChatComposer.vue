<script setup lang="ts">
import { Position, Refresh, UploadFilled, VideoPause } from '@element-plus/icons-vue'
import { computed, ref } from 'vue'

import type { ChatSession } from '@/types/api'

/**
 * 聊天输入区：负责多行输入、中文输入法组合态处理、附件选择与发送/停止生成按钮。
 * 只把用户动作以事件抛给父组件，不直接发起请求。
 */
const props = defineProps<{
  modelValue: string
  session: ChatSession | null
  submitting?: boolean
  /** 当前输入框的受控业务语境，仅用于引导客户补充信息。 */
  composerHint?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  submit: []
  cancel: []
  upload: [file: File]
}>()

const isComposing = ref(false)
const uploadInputRef = ref<HTMLInputElement | null>(null)

const inHumanHandoff = computed(() => ['PENDING', 'ACTIVE'].includes(String(props.session?.handoff_status || '')))
const inputPlaceholder = computed(() =>
  inHumanHandoff.value
    ? '请输入要补充给人工客服的信息...'
    : props.composerHint
      ? '请说明退货原因；可补充上门取件或方便取件的时间'
      : '请输入您的问题...'
)

/** Enter 发送、Shift+Enter 换行；输入法组合态下不拦截回车。 */
function handleInputKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || isComposing.value) return
  event.preventDefault()
  if (props.submitting || !props.modelValue.trim()) return
  emit('submit')
}

function pickAttachment() {
  uploadInputRef.value?.click()
}

/** 选择附件后立即抛出，允许连续选择同一文件时再次触发 change。 */
function onAttachmentPicked(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  emit('upload', file)
  input.value = ''
}
</script>

<template>
  <div class="chat-input-box">
    <div v-if="composerHint" class="composer-context-hint">
      <el-icon><Refresh /></el-icon>
      <span>{{ composerHint }}，请补充原因；不填写也可直接发送。</span>
    </div>
    <el-input
      :model-value="modelValue"
      :autosize="{ minRows: 1, maxRows: 5 }"
      :placeholder="inputPlaceholder"
      type="textarea"
      @compositionend="isComposing = false"
      @compositionstart="isComposing = true"
      @keydown="handleInputKeydown"
      @update:model-value="emit('update:modelValue', String($event))"
    />
    <div class="chat-input-footer">
      <div class="input-tools">
        <input ref="uploadInputRef" class="hidden-file-input" type="file" @change="onAttachmentPicked" />
        <el-tooltip content="上传附件" placement="top">
          <el-button class="input-tool-button" text circle :icon="UploadFilled" aria-label="上传附件" @click="pickAttachment" />
        </el-tooltip>
      </div>
      <el-tooltip v-if="submitting" content="停止本次生成，已显示的内容会保留" placement="top">
        <el-button class="generation-stop-button" :icon="VideoPause" aria-label="停止生成" @click="emit('cancel')">
          停止生成
        </el-button>
      </el-tooltip>
      <el-button v-else :icon="Position" circle type="primary" @click="emit('submit')" />
    </div>
  </div>
</template>
