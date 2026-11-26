import {
  ORDER_POLL_INTERVAL_MS,
  ORDER_POLL_MAX_ATTEMPTS
} from '../constants'
import type {
  ClientOrderResponse,
  OrderStatus,
  PageResponse,
  PaymentOrderResponse,
  VirtualPayCreateResponse
} from '../types'
import type { VirtualPayPlatform } from '../utils/platform'
import { ApiError, getErrorMessage, request } from './request'

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
    super(`订单 ${orderNo} 已取消，可返回课程重新购买`)
    this.name = 'OrderClosedError'
    this.orderNo = orderNo
  }
}

export interface MyOrderListParams {
  page?: number
  pageSize?: number
  status?: OrderStatus
}

/** 订单中心：只返回当前登录用户的订单，可按状态筛选。 */
export function getMyOrders(
  params: MyOrderListParams = {}
): Promise<PageResponse<ClientOrderResponse>> {
  return request<PageResponse<ClientOrderResponse>>({
    url: '/client/orders',
    method: 'GET',
    params: {
      page: params.page,
      page_size: params.pageSize,
      status: params.status
    }
  })
}

/** 订单详情：只允许访问当前登录用户自己的订单。 */
export function getOrderDetail(
  orderNo: string
): Promise<ClientOrderResponse> {
  return request<ClientOrderResponse>({
    url: `/client/orders/${encodeURIComponent(orderNo)}`,
    method: 'GET'
  })
}

/**
 * 查询本地订单状态。
 *
 * 虚拟支付订单只读取本地状态（由 xpay 推送发货维护），不会调用普通
 * 微信支付查单；支付成功页据此轮询确认。
 */
export function getOrderStatus(
  orderNo: string
): Promise<PaymentOrderResponse> {
  return request<PaymentOrderResponse>({
    url: `/payments/query-order/${encodeURIComponent(orderNo)}`,
    method: 'GET'
  })
}

/**
 * 虚拟支付下单：服务端按 product_id 解析课程与金额，返回订单号与
 * wx.requestVirtualPayment 参数。login_code 必须是本次购买前新取的
 * wx.login code，服务端用完即弃，不保存 session_key。
 */
export function createVirtualOrder(
  productId: string,
  platform: VirtualPayPlatform,
  loginCode: string
): Promise<VirtualPayCreateResponse> {
  return request<VirtualPayCreateResponse>({
    url: '/payments/virtual/create-order',
    method: 'POST',
    data: {
      product_id: productId,
      platform,
      login_code: loginCode
    }
  })
}

/** 当前基础库 / 微信版本是否支持虚拟支付。 */
export function isVirtualPaySupported(): boolean {
  return (
    typeof wx !== 'undefined' &&
    typeof wx.requestVirtualPayment === 'function'
  )
}

/**
 * 调起微信虚拟支付。
 *
 * signData 必须原样透传服务端字符串；成功回调只代表支付面板完成，
 * 课程权限一律以服务端订单状态（xpay 推送发货）为准。
 */
export async function requestWeChatVirtualPayment(
  order: VirtualPayCreateResponse
): Promise<void> {
  const api = typeof wx !== 'undefined' ? wx : undefined
  if (!api?.requestVirtualPayment) {
    throw new Error('当前微信版本不支持虚拟支付，请升级微信后重试')
  }
  await new Promise<void>((resolve, reject) => {
    api.requestVirtualPayment!({
      signData: order.sign_data,
      mode: order.mode,
      paySig: order.pay_sig,
      signature: order.signature,
      success: () => resolve(),
      fail: (error) => reject(error)
    })
  })
}

const VIRTUAL_PAY_API_MESSAGES: Record<string, string> = {
  PAYMENT_UNAVAILABLE: '支付服务暂不可用，请稍后重试',
  VPAY_PRODUCT_NOT_FOUND: '商品不存在或已下架',
  VPAY_PRODUCT_DISABLED: '该商品暂不可购买',
  VPAY_PRODUCT_ENV_MISMATCH: '当前环境暂不支持购买该课程',
  VPAY_PRICE_MISMATCH: '商品价格配置异常，请联系客服',
  COURSE_NOT_AVAILABLE: '课程暂不可购买',
  COURSE_ALREADY_OWNED: '您已拥有该课程，无需重复购买',
  COURSE_ACCESS_NOT_STARTED: '课程观看权限尚未生效',
  PAYMENT_OPENID_MISMATCH: '登录状态异常，请重新进入小程序',
  ORDER_CREATE_TOO_FREQUENT: '操作过于频繁，请稍后重试',
  WX_LOGIN_FAIL: '微信登录失效，请重新进入小程序'
}

const VIRTUAL_PAY_ERRCODE_MESSAGES: Record<number, string> = {
  [-2]: '支付已取消，可稍后重新发起',
  // iOS 未开启苹果 IAP 支付能力时，微信会返回 15001。
  [15001]: '当前设备暂不支持购买，请升级微信后重试或联系客服',
  [-15001]: '支付参数异常，请重新发起支付',
  [-15002]: '订单号已使用，请重新发起支付',
  [-15005]: '支付校验失败，请重新发起支付',
  [-15006]: '支付签名校验失败，请联系客服',
  [-15007]: '登录状态已过期，请重新发起支付',
  [-15010]: '商品尚未上架，请稍后重试',
  [-15011]: '当前环境不支持该支付方式',
  [-15013]: '商品价格配置异常，请联系客服',
  [-15014]: '商品尚未生效，请稍后重试',
  [-15016]: '支付参数格式异常，请重新发起支付'
}

function readVirtualPayErrCode(error: unknown): number {
  if (!error || typeof error !== 'object') {
    return Number.NaN
  }
  const record = error as Record<string, unknown>
  return Number(record.errCode ?? record.errno ?? record.err_code)
}

/** 用户主动关闭虚拟支付面板：微信返回 -2 或 errMsg 含 cancel。 */
export function isPaymentCancelled(error: unknown): boolean {
  if (readVirtualPayErrCode(error) === -2) {
    return true
  }
  if (!error || typeof error !== 'object') {
    return false
  }
  const message = (error as Record<string, unknown>).errMsg
  return typeof message === 'string' && /cancel/i.test(message)
}

/** 把虚拟支付 / 下单接口错误转换为可展示文案。 */
export function describeVirtualPayError(error: unknown): string {
  if (isPaymentCancelled(error)) {
    return '支付已取消，可稍后重新发起'
  }
  if (error instanceof ApiError) {
    const message = VIRTUAL_PAY_API_MESSAGES[error.code]
    if (message) {
      return message
    }
  }
  const code = readVirtualPayErrCode(error)
  if (Number.isFinite(code) && VIRTUAL_PAY_ERRCODE_MESSAGES[code]) {
    return VIRTUAL_PAY_ERRCODE_MESSAGES[code]
  }
  return getErrorMessage(error)
}

/**
 * 配置 / 环境类错误需要明确弹窗，避免用户误以为只是网络问题。
 * 这类错误重试通常无效，应由运营检查微信后台商品与 AppKey 配置。
 */
export function isVirtualPayConfigurationError(error: unknown): boolean {
  if (error instanceof ApiError) {
    return (
      error.code === 'PAYMENT_UNAVAILABLE' ||
      error.code === 'VPAY_PRICE_MISMATCH' ||
      error.code === 'VPAY_PRODUCT_ENV_MISMATCH'
    )
  }
  const code = readVirtualPayErrCode(error)
  return (
    code === 15001 ||
    code === -15006 ||
    code === -15011 ||
    code === -15013 ||
    code === -15016
  )
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
      if (order.status === 'closed') {
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
