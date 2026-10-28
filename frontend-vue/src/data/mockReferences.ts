import type { Reference } from '@/types/api'

/** 参考文献演示数据，用于本地开发、组件预览与测试。 */
export const mockReferences: Reference[] = [
  {
    id: 'kb-demo-refund',
    index: 1,
    title: '售后政策 / 退款到账',
    authors: ['客服制度组'],
    source: '退款到账管理办法 V1.0',
    year: '2026',
    url: 'https://example.com/policy/refund-arrival',
    abstract: '规定退款审核通过后的到账时效与客户核实路径。',
    content: '退款审核通过后通常 1-7 个工作日原路退回，具体到账时间以支付渠道处理为准。超过 7 个工作日仍未到账，可联系在线客服核实到账进度。',
    snippet: '退款审核通过后通常 1-7 个工作日原路退回…'
  },
  {
    id: 'kb-demo-return',
    index: 2,
    title: '售后政策 / 退货条件',
    authors: ['客服制度组'],
    source: '退货规则 V1.0',
    year: '2026',
    url: 'https://example.com/policy/return-goods',
    abstract: '退货申请的时间窗口与商品状态要求。',
    content: '签收后 7 天内且商品不影响二次销售时，可申请退货；是否通过以售后审核结果为准。申请退货时可选择上门取件或自行寄回。',
    snippet: '签收后 7 天内且商品不影响二次销售时可申请退货…'
  },
  {
    id: 'kb-demo-complaint',
    index: 3,
    title: '投诉处理 / 人工审核',
    authors: ['风控与客诉组'],
    source: '投诉处理规范 V1.0',
    year: '2026',
    url: 'https://example.com/policy/complaint',
    abstract: '投诉、举报与赔付场景必须转人工处理。',
    content: '投诉、举报、赔付和强烈不满场景必须转人工处理，并保留完整会话记录。赔偿金额、处罚商家或法律结论需由人工专员在权限范围内确认。',
    snippet: '投诉、举报、赔付和强烈不满场景必须转人工处理…'
  }
]
