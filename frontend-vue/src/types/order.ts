/**
 * 订单域类型：客户订单、订单详情与物流轨迹。
 * 手机号、地址等敏感字段仅在订单详情中按后端脱敏结果展示。
 */

/** 客户订单列表项。 */
export interface CustomerOrder {
  id: number
  orderNo: string
  customerId: number
  productId: number
  productName?: string | null
  productCategory?: string | null
  quantity: number
  warrantyDays?: number | null
  returnable?: boolean | null
  orderStatus: string
  payTime?: string | null
  shipTime?: string | null
  signTime?: string | null
  amount?: number | string | null
  afterSaleStatus?: string | null
}

/** 订单详情页使用的客户安全字段，手机号由业务服务脱敏后返回。 */
export interface CustomerOrderDetail extends CustomerOrder {
  receiverName?: string | null
  receiverPhoneMasked?: string | null
  shippingAddress?: string | null
  paymentMethod?: string | null
  deliveryMethod?: string | null
  freightAmount?: number | string | null
}

/** 单条物流轨迹节点。 */
export interface LogisticsTrace {
  status: string
  description: string
  location?: string | null
  stationName?: string | null
  occurredAt?: string | null
}

/** 订单物流概览，包含承运商与最新轨迹列表。 */
export interface CustomerOrderLogistics {
  orderNo: string
  carrierName?: string | null
  trackingNo?: string | null
  logisticsStatus?: string | null
  latestLocation?: string | null
  estimatedDeliveryTime?: string | null
  routeSummary?: string | null
  traces: LogisticsTrace[]
}
