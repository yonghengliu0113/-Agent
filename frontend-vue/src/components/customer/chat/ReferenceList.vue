<script setup lang="ts">
import type { Reference } from '@/types/api'

/** 参考文献列表：论文式条目，点击条目打开右侧详情并高亮当前文献。 */
const props = defineProps<{
  references: Reference[]
  activeId?: string | null
}>()

const emit = defineEmits<{
  select: [reference: Reference]
}>()

defineOptions({ name: 'ReferenceList' })

function authorsText(reference: Reference) {
  const authors = reference.authors || []
  if (!authors.length) return ''
  return authors.join('、')
}
</script>

<template>
  <ol class="reference-list" role="listbox" aria-label="参考文献列表">
    <li
      v-for="reference in props.references"
      :key="reference.id"
      :class="['reference-list__item', { active: reference.id === props.activeId }]"
      :aria-selected="reference.id === props.activeId"
      role="option"
    >
      <button class="reference-list__link" type="button" @click="emit('select', reference)">
        <span class="reference-list__index">[{{ reference.index }}]</span>
        <span class="reference-list__body">
          <strong class="reference-list__title">{{ reference.title }}</strong>
          <span v-if="authorsText(reference)" class="reference-list__authors">{{ authorsText(reference) }}</span>
          <span class="reference-list__source">
            {{ reference.source || '知识库文档' }}<template v-if="reference.year"> · {{ reference.year }}</template>
          </span>
        </span>
      </button>
    </li>
  </ol>
</template>
