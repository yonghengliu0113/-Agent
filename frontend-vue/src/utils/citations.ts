import type { CitationLike, Reference } from '@/types/api'

/**
 * 把后端返回的引用数据(客户安全形态或原始 Citation)统一转换为 Reference。
 * 兼容两类来源：会话消息 extra_data.citations 与轮询结果 citations。
 */
export function normalizeReferences(citations: unknown): Reference[] {
  if (!Array.isArray(citations)) return []
  const references: Reference[] = []
  for (const item of citations) {
    const ref = coerceReference(item)
    if (ref) references.push(ref)
  }
  // 序号以出现顺序为准，正文 [n] 索引按该顺序渲染。
  return references.map((ref, index) => ({ ...ref, index: index + 1 }))
}

function coerceReference(item: unknown): Reference | null {
  if (!item || typeof item !== 'object') return null
  const raw = item as Record<string, unknown>

  // 客户安全形态(后端 customer_reference_payloads)
  if (typeof raw.id === 'string' && typeof raw.title === 'string') {
    return {
      id: raw.id,
      index: Number(raw.index) || 0,
      title: raw.title,
      authors: asStringArray(raw.authors),
      source: asString(raw.source),
      collection: asString(raw.collection),
      risk_level: asString(raw.risk_level),
      year: asString(raw.year),
      url: asString(raw.url),
      abstract: asString(raw.abstract),
      content: asString(raw.content) || asString(raw.snippet),
      snippet: asString(raw.snippet)
    }
  }

  // 原始 Citation 形态
  const id = asString(raw.citation_id)
  if (!id && !raw.doc_name) return null
  const heading = Array.isArray(raw.heading_path) ? raw.heading_path.map(String) : []
  const paragraph = asString(raw.paragraph)
  const metadata = (raw.metadata && typeof raw.metadata === 'object' ? raw.metadata : {}) as Record<string, unknown>
  return {
    id: id || `ref-${raw.doc_name}`,
    index: 0,
    title: heading.length ? heading.join(' / ') : (asString(raw.doc_name) || '知识库片段'),
    source: asString(raw.doc_name),
    collection: asString(raw.collection),
    risk_level: asString(raw.risk_level),
    authors: asStringArray(metadata.authors),
    year: asString(metadata.year),
    url: asString(metadata.url),
    abstract: asString(metadata.abstract),
    content: paragraph,
    snippet: paragraph
  }
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

function asStringArray(value: unknown): string[] | null {
  if (Array.isArray(value)) {
    const items = value.filter((item): item is string => typeof item === 'string' && Boolean(item.trim()))
    return items.length ? items : null
  }
  return null
}

export interface CitationSegment {
  type: 'text' | 'citation'
  text?: string
  refIndex?: number
}

/**
 * 解析正文中的【来源:kb-xxx】/【引用:kb-xxx】标记，映射为 [n] 可点击索引。
 * 正文索引按标记出现顺序编号；引用列表缺失或标记无法匹配时，标记按普通文本剔除。
 */
export function parseContentCitations(content: string, references: Reference[]): {
  segments: CitationSegment[]
  plainText: string
} {
  const markerPattern = /【(?:来源|引用)[:：]\s*kb-[0-9a-fA-F]+】/g
  const matches = [...String(content || '').matchAll(markerPattern)]
  if (!matches.length) {
    return { segments: [{ type: 'text', text: String(content || '') }], plainText: String(content || '') }
  }

  // 按出现顺序建立 citation_id → 正文序号 的映射
  const markerOrder: string[] = []
  for (const match of matches) {
    const id = match[0].replace(/^【(?:来源|引用)[:：]\s*/, '').replace(/】$/, '').trim().toLowerCase()
    if (!markerOrder.includes(id)) markerOrder.push(id)
  }
  const idToIndex = new Map<string, number>()
  for (const reference of references) {
    const matchedIndex = markerOrder.indexOf(reference.id.toLowerCase())
    if (matchedIndex >= 0) idToIndex.set(reference.id.toLowerCase(), matchedIndex + 1)
  }
  // 未在引用列表中出现的标记按出现顺序编号(找不到文献详情时仍可显示 [n] 文本)。
  const orphanIds = markerOrder.filter((id) => !idToIndex.has(id))

  const segments: CitationSegment[] = []
  let cursor = 0
  const raw = String(content || '')
  for (const match of matches) {
    const marker = match[0]
    const start = match.index ?? 0
    // 折叠索引两侧的空白与换行：LLM 常在标记前后断行，直接渲染会让 [n] 独占一行。
    // 段内(非标记相邻处)的换行不受影响，仍保留原段落结构。
    const before = raw.slice(cursor, start).replace(/^[\s\u00a0]+/u, '').replace(/[\s\u00a0]+$/u, '')
    if (before) segments.push({ type: 'text', text: before })
    const id = marker.replace(/^【(?:来源|引用)[:：]\s*/, '').replace(/】$/, '').trim().toLowerCase()
    let refIndex = idToIndex.get(id)
    if (!refIndex) {
      const orphanPosition = orphanIds.indexOf(id)
      refIndex = orphanPosition >= 0 ? references.length + orphanPosition + 1 : undefined
    }
    segments.push({ type: 'citation', refIndex })
    cursor = start + marker.length
  }
  // 尾段去除紧随索引后的换行，让 [n] 与所引用的句子保持同一行。
  const tail = raw.slice(cursor).replace(/^[\s\u00a0]+/u, '').replace(/[\s\u00a0]+$/u, '')
  if (tail) segments.push({ type: 'text', text: tail })

  const plainText = segments
    .map((segment) => (segment.type === 'citation' ? `[${segment.refIndex ?? '?'}]` : (segment.text || '')))
    .join('')
  return { segments, plainText }
}

/** 正文 [n] 点击后定位参考文献：找不到时返回 null 由调用方降级。 */
export function referenceByIndex(references: Reference[], index: number): Reference | null {
  return references.find((item) => item.index === index) ?? null
}
