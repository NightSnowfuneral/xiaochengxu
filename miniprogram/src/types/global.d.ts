declare module '*.png' {
  const src: string
  export default src
}

/**
 * 小程序虚拟支付 API 的最小声明。
 *
 * 项目未引入 miniprogram-api-typings，这里只补充当前使用的
 * wx.requestVirtualPayment，避免在全局引入整套微信类型。
 */
interface WxRequestVirtualPaymentOptions {
  signData: string
  mode: 'short_series_goods' | 'short_series_coin'
  paySig: string
  signature: string
  success?: (res: { errMsg?: string }) => void
  fail?: (res: { errMsg?: string; errCode?: number; errno?: number }) => void
  complete?: (res: { errMsg?: string }) => void
}

interface WxVirtualPaymentApi {
  requestVirtualPayment?: (options: WxRequestVirtualPaymentOptions) => void
}

declare const wx: WxVirtualPaymentApi

declare namespace NodeJS {
  interface ProcessEnv {
    NODE_ENV: 'development' | 'production' | 'test'
    TARO_APP_API_BASE_URL?: string
  }
}
