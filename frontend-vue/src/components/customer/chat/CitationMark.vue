<script setup lang="ts">
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import { computed } from 'vue'
import type { Reference } from '@/types/api'
import { parseContentCitations } from '@/utils/citations'

/**
 * AI 正文渲染：Markdown 文本 + 可点击的 [n] 引用索引。
 * 通过事件委托处理索引点击，不依赖 v-html 内绑定。
 */
const props = defineProps<{
  content: string
  references: Reference[]
  activeId?: string | null
}>()

const emit = defineEmits<{
  'select-reference': [index: number]
}>()

defineOptions({ name: 'CitationMark' })

const markdown = new MarkdownIt({ breaks: true, html: false, linkify: true, typographer: false })

const parsed = computed(() => parseContentCitations(props.content, props.references))

/** 高亮的文献 id 对应的正文序号。 */
const activeIndexes = computed(() => new Set(props.references.filter((item) => item.id === props.activeId).map((item) => item.index)))

function renderMarkdown(text: string) {
  return DOMPurify.sanitize(markdown.render(text), {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'iframe', 'form']
  })
}

/**
 * 整条消息合成一篇 Markdown 文档一次性渲染(表格/列表/代码块走标准管线)，
 * 索引用占位符注入段落内部，渲染后替换为行内角标。
 * 分段渲染会产生多个 <p> 块级标签，夹在段落之间的索引会被浏览器强制换行。
 */
const html = computed(() => {
  let combined = ''
  for (const segment of parsed.value.segments) {
    if (segment.type === 'text') {
      combined += segment.text || ''
      continue
    }
    if (segment.refIndex && segment.refIndex > 0) {
      combined += `__CITATION_${segment.refIndex}__`
    }
  }
  let rendered = renderMarkdown(combined)
  const inject = (text: string) => text.replace(/__CITATION_(\d+)__/g, (_, index: string) => {
    const activeClass = activeIndexes.value.has(Number(index)) ? ' citation-mark--active' : ''
    return `<span class="citation-mark${activeClass}" role="button" tabindex="0" data-ref-index="${index}">[${index}]</span>`
  })
  // 代码块内只保留纯文本 [n]，不注入交互元素；其余位置注入可点击角标。
  const parts = rendered.split(/(<pre[\s\S]*?<\/pre>)/g)
  for (let index = 0; index < parts.length; index += 2) {
    parts[index] = inject(parts[index])
  }
  for (let index = 1; index < parts.length; index += 2) {
    parts[index] = parts[index].replace(/__CITATION_(\d+)__/g, '[$1]')
  }
  rendered = parts.join('')
  // 注入角标后再清洗一次，确保 v-html 输出的索引标签同样受净化约束。
  return DOMPurify.sanitize(rendered, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'iframe', 'form']
  })
})

function handleClick(event: MouseEvent) {
  const target = (event.target as HTMLElement).closest<HTMLElement>('.citation-mark')
  if (!target) return
  const index = Number(target.dataset.refIndex || 0)
  if (index > 0) emit('select-reference', index)
}

function handleKeydown(event: KeyboardEvent) {
  const target = (event.target as HTMLElement).closest<HTMLElement>('.citation-mark')
  if (!target) return
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    const index = Number(target.dataset.refIndex || 0)
    if (index > 0) emit('select-reference', index)
  }
}
</script>

<template>
  <div class="citation-markdown" @click="handleClick" @keydown="handleKeydown">
    <div class="message-markdown" v-html="html" />
  </div>
</template>
