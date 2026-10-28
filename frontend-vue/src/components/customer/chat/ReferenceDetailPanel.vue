<script setup lang="ts">
import { Close, Link } from '@element-plus/icons-vue'
import { onBeforeUnmount, onMounted, watch } from 'vue'
import type { Reference } from '@/types/api'

/** 参考文献详情面板：桌面端右侧抽屉，移动端底部全屏抽屉；支持 ESC 与遮罩关闭。 */
const props = defineProps<{
  modelValue: boolean
  reference: Reference | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

defineOptions({ name: 'ReferenceDetailPanel' })

function close() {
  emit('update:modelValue', false)
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && props.modelValue) close()
}

onMounted(() => document.addEventListener('keydown', handleKeydown))
onBeforeUnmount(() => document.removeEventListener('keydown', handleKeydown))

// 打开面板时把焦点留给关闭按钮，保证键盘可达性。
watch(
  () => props.modelValue,
  (visible) => {
    if (visible) {
      requestAnimationFrame(() => {
        document.querySelector<HTMLButtonElement>('.reference-detail__close')?.focus()
      })
    }
  }
)

function authorsText(reference: Reference) {
  return (reference.authors || []).join('、')
}

function row(label: string, value?: string | null) {
  if (!value) return null
  return { label, value }
}
</script>

<template>
  <teleport to="body">
    <div v-if="props.modelValue" class="reference-detail-mask" aria-hidden="true" @click="close" />
    <transition name="reference-detail">
      <aside
        v-if="props.modelValue"
        class="reference-detail"
        role="dialog"
        aria-modal="true"
        aria-label="参考文献详情"
      >
        <header class="reference-detail__header">
          <div>
            <h3>参考文献</h3>
            <p v-if="props.reference">[{{ props.reference.index }}] {{ props.reference.title }}</p>
          </div>
          <el-button class="reference-detail__close" text circle :icon="Close" aria-label="关闭详情" @click="close" />
        </header>

        <div v-if="props.reference" class="reference-detail__body">
          <dl class="reference-detail__meta">
            <template v-for="item in [
              row('作者', authorsText(props.reference)),
              row('来源', props.reference.source),
              row('年份', props.reference.year),
            ]" :key="item?.label">
              <div v-if="item">
                <dt>{{ item.label }}</dt>
                <dd>{{ item.value }}</dd>
              </div>
            </template>
            <div v-if="props.reference.url">
              <dt>链接</dt>
              <dd><a class="reference-detail__url" :href="props.reference.url" target="_blank" rel="noopener noreferrer"><el-icon><Link /></el-icon>{{ props.reference.url }}</a></dd>
            </div>
          </dl>

          <section v-if="props.reference.abstract" class="reference-detail__section">
            <h4>摘要</h4>
            <p>{{ props.reference.abstract }}</p>
          </section>

          <section v-if="props.reference.snippet" class="reference-detail__section">
            <h4>相关片段</h4>
            <blockquote>{{ props.reference.snippet }}</blockquote>
          </section>

          <section v-if="props.reference.content" class="reference-detail__section">
            <h4>原文详情</h4>
            <p class="reference-detail__content">{{ props.reference.content }}</p>
          </section>
        </div>
        <el-empty v-else description="未找到对应文献" :image-size="72" />
      </aside>
    </transition>
  </teleport>
</template>
