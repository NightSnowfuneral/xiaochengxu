import Taro from '@tarojs/taro'

import {
  ORDER_POLL_INTERVAL_MS,
  ORDER_POLL_MAX_ATTEMPTS
} from '../constants'
import type {
  OrderCreateResponse,
  PaymentOrderResponse,
  WeChatPayParams
} from '../types'
import { request } from './request'

export class OrderPollCancelledError extends Error {
  constructor() {
    super('订单轮询已取消')
    this.name = 'OrderPollCancelledError'
  }
}

export class OrderPollTimeoutError extends Error {
  readonly orderNo: string

  constructor(orderNo: string) {
    super(`订单 ${orderNo} 支付结果确认超时，请稍后在“我的课程”中查看`)
    this.name = 'OrderPollTimeoutError'
    this.orderNo = orderNo
  }
}

export class OrderClosedError extends Error {
  readonly orderNo: string

  constructor(orderNo: string) {
    super(`订单 ${orderNo} 已关闭，可返回课程重新购买`)
    this.name = 'OrderClosedError'
    this.orderNo = orderNo
  }
}

export function createOrder(courseId: number): Promise<OrderCreateResponse> {
  return request<OrderCreateResponse>({
    url: '/payments/create-order',
    method: 'POST',
    data: { course_id: courseId }
  })
}

/** pending 订单会由后端主动向微信查单并同步，回调丢失也能确认支付。 */
export function getOrderStatus(
  orderNo: string
): Promise<PaymentOrderResponse> {
  return request<PaymentOrderResponse>({
    url: `/payments/query-order/${encodeURIComponent(orderNo)}`,
    method: 'GET'
  })
}

function toRequestPaymentOptions(payment: WeChatPayParams) {
  return {
    timeStamp: payment.time_stamp,
    nonceStr: payment.nonce_str,
    package: payment.package,
    signType: payment.sign_type as 'MD5' | 'HMAC-SHA256' | 'RSA',
    paySign: payment.pay_sign
  }
}

/** 将后端 snake_case 支付参数映射为 wx.requestPayment 需要的驼峰字段。 */
export async function requestWeChatPayment(
  payment: WeChatPayParams
): Promise<void> {
  await Taro.requestPayment(toRequestPaymentOptions(payment))
}

export function isPaymentCancelled(error: unknown): boolean {
  if (!error || typeof error !== 'object') {
    return false
  }
  const errMsg = (error as Record<string, unknown>).errMsg
  return typeof errMsg === 'string' && /cancel/i.test(errMsg)
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds)
  })
}

export interface PollOrderOptions {
  intervalMs?: number
  maxAttempts?: number
  shouldContinue?: () => boolean
  onStatus?: (order: PaymentOrderResponse) => void
}

/**
 * 支付发起后每 2 秒轮询订单状态，直到 paid。
 * 网络短暂抖动最多连续容忍 4 次；超过 2 分钟未确认则提示稍后查看。
 */
export async function pollOrderUntilPaid(
  orderNo: string,
  options: PollOrderOptions = {}
): Promise<PaymentOrderResponse> {
  const intervalMs = options.intervalMs ?? ORDER_POLL_INTERVAL_MS
  const maxAttempts = options.maxAttempts ?? ORDER_POLL_MAX_ATTEMPTS
  let consecutiveErrors = 0

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (options.shouldContinue && !options.shouldContinue()) {
      throw new OrderPollCancelledError()
    }

    try {
      const order = await getOrderStatus(orderNo)
      consecutiveErrors = 0
      options.onStatus?.(order)
      if (order.status === 'paid') {
        return order
      }
      if (order.status === 'closed' || order.status === 'refunded') {
        throw new OrderClosedError(orderNo)
      }
    } catch (error) {
      consecutiveErrors += 1
      if (consecutiveErrors >= 4 || attempt === maxAttempts - 1) {
        throw error
      }
    }

    if (attempt < maxAttempts - 1) {
      await delay(intervalMs)
    }
  }

  throw new OrderPollTimeoutError(orderNo)
}
