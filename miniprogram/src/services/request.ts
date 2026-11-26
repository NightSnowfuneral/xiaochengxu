// 必须在 axios 之前执行：小程序运行时缺少 AbortController。
import '../utils/abortController'

import Taro from '@tarojs/taro'
import axios, {
  AxiosError,
  type AxiosAdapter,
  type AxiosRequestConfig,
  type AxiosResponse,
  type InternalAxiosRequestConfig
} from 'axios'

import { API_BASE_URL, IS_DEV, REQUEST_TIMEOUT_MS } from '../config'
import type { ApiErrorBody } from '../types'
import { getAuthSession } from './session'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly data: unknown

  constructor(
    message: string,
    status = 0,
    code = 'REQUEST_FAILED',
    data: unknown = null
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.data = data
    Object.setPrototypeOf(this, ApiError.prototype)
  }
}

/** 请求扩展配置：部分接口需要自行处理 401，不触发全局登出逻辑。 */
export interface ApiRequestConfig extends AxiosRequestConfig {
  /**
   * 为 true 时，401 不进入全局未授权处理（不清本地状态）。
   * 用于登录、登出与冷启动 Token 校验：它们由调用方自行完成清理。
   */
  skipAuthHandler?: boolean
  /** 为 true 时不附加 Authorization，用于公开只读接口。 */
  skipAuth?: boolean
}

type UnauthorizedHandler = () => void

let unauthorizedHandler: UnauthorizedHandler | null = null
let lastUnauthorizedAt = 0
let mockUnauthorizedToastShown = false

export function setUnauthorizedHandler(handler: UnauthorizedHandler): void {
  unauthorizedHandler = handler
}

function notifyUnauthorized(): void {
  const now = Date.now()
  if (now - lastUnauthorizedAt < 1500) {
    return
  }
  lastUnauthorizedAt = now
  unauthorizedHandler?.()
}

/**
 * 业务接口返回 401 时的统一入口。
 *
 * axios 请求由响应拦截器自动调用；Taro.uploadFile 等未走 axios 的请求
 * 需要在 401 分支手动调用，保证任何接口失效都会清理登录态并停留当前页。
 */
export function reportUnauthorized(): void {
  const { isMockLogin } = getAuthSession()
  if (isMockLogin) {
    // 模拟 Token 本来就不被后端接受，401 是预期结果，不能因此清掉测试会话。
    if (!mockUnauthorizedToastShown) {
      mockUnauthorizedToastShown = true
      void Taro.showToast({
        title: '测试模式：接口未授权（预期）',
        icon: 'none',
        duration: 2200
      })
    }
    return
  }
  notifyUnauthorized()
}

function stringifyParams(params: unknown): string {
  if (!params || typeof params !== 'object') {
    return ''
  }
  const pairs: string[] = []
  Object.entries(params as Record<string, unknown>).forEach(([key, value]) => {
    if (value === undefined || value === null) {
      return
    }
    const values = Array.isArray(value) ? value : [value]
    values.forEach((item) => {
      if (item === undefined || item === null) {
        return
      }
      pairs.push(
        `${encodeURIComponent(key)}=${encodeURIComponent(String(item))}`
      )
    })
  })
  return pairs.join('&')
}

function buildRequestUrl(config: InternalAxiosRequestConfig): string {
  const rawUrl = config.url || ''
  const baseURL = (config.baseURL || '').replace(/\/+$/, '')
  let url = rawUrl
  if (!/^https?:\/\//i.test(url) && baseURL) {
    url = `${baseURL}/${url.replace(/^\/+/, '')}`
  }
  const query = stringifyParams(config.params)
  if (!query) {
    return url
  }
  return `${url}${url.includes('?') ? '&' : '?'}${query}`
}

function buildHeaders(
  config: InternalAxiosRequestConfig
): Record<string, string> {
  const headers: Record<string, string> = {}
  const rawHeaders =
    typeof config.headers.toJSON === 'function'
      ? config.headers.toJSON()
      : config.headers
  Object.entries(rawHeaders || {}).forEach(([key, value]) => {
    if (value === undefined || value === null) {
      return
    }
    headers[key] = String(value)
  })
  return headers
}

/**
 * 小程序没有浏览器 XHR，使用 Taro.request 实现 axios adapter。
 * axios 的请求/响应拦截器、参数与 header 处理仍然可用。
 */
const taroAdapter: AxiosAdapter = (config) =>
  new Promise<AxiosResponse>((resolve, reject) => {
    const url = buildRequestUrl(config)
    let requestTask: any = null

    try {
      requestTask = Taro.request({
        url,
        method: (config.method || 'get').toUpperCase() as any,
        data: config.data,
        header: buildHeaders(config),
        timeout: config.timeout || REQUEST_TIMEOUT_MS,
        success: (result) => {
          const response: AxiosResponse = {
            data: result.data,
            status: result.statusCode,
            statusText: '',
            headers: (result.header || {}) as any,
            config,
            request: requestTask
          }
          const validateStatus =
            config.validateStatus ||
            ((status: number) => status >= 200 && status < 300)
          if (validateStatus(result.statusCode)) {
            resolve(response)
            return
          }
          reject(
            new AxiosError(
              `Request failed with status code ${result.statusCode}`,
              AxiosError.ERR_BAD_RESPONSE,
              config,
              requestTask,
              response
            )
          )
        },
        fail: (error) => {
          reject(
            new AxiosError(
              error?.errMsg || '网络请求失败',
              AxiosError.ERR_NETWORK,
              config,
              requestTask
            )
          )
        }
      })
    } catch (error) {
      reject(
        new AxiosError(
          getErrorMessage(error),
          AxiosError.ERR_NETWORK,
          config,
          requestTask
        )
      )
    }
  })

const http = axios.create({
  baseURL: API_BASE_URL,
  timeout: REQUEST_TIMEOUT_MS,
  adapter: taroAdapter,
  headers: {
    'Content-Type': 'application/json',
    Accept: 'application/json'
  }
})

http.interceptors.request.use((config) => {
  const { token } = getAuthSession()
  const isLoginEndpoint = (config.url || '').includes('/auth/wx-login')
  const skipAuth = Boolean((config as ApiRequestConfig).skipAuth)
  if (token && !isLoginEndpoint && !skipAuth) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  config.headers.set('Accept', 'application/json')
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    const normalized = normalizeError(error)
    const requestUrl = axios.isAxiosError(error)
      ? error.config?.url || ''
      : ''
    const isLoginEndpoint = requestUrl.includes('/auth/wx-login')
    const skipAuthHandler = Boolean(
      axios.isAxiosError(error)
        ? (error.config as ApiRequestConfig | undefined)?.skipAuthHandler
        : false
    )

    if (normalized.status === 401 && !isLoginEndpoint && !skipAuthHandler) {
      reportUnauthorized()
    }

    if (IS_DEV) {
      // 开发环境保留可诊断信息，生产环境不打印用户请求细节。
      console.warn('[request]', requestUrl || 'unknown', normalized.message)
    }
    return Promise.reject(normalized)
  }
)

function normalizeError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error
  }
  if (axios.isAxiosError(error)) {
    const status = error.response?.status ?? 0
    const body = error.response?.data as Partial<ApiErrorBody> | undefined
    const fallbackMessage =
      status === 0
        ? '网络连接失败，请检查网络或接口地址'
        : `请求失败（${status}）`
    return new ApiError(
      typeof body?.message === 'string' && body.message
        ? body.message
        : fallbackMessage,
      status,
      typeof body?.code === 'string' ? body.code : 'REQUEST_FAILED',
      body?.data ?? null
    )
  }
  return new ApiError(getErrorMessage(error), 0, 'REQUEST_FAILED')
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message
  }
  if (typeof error === 'string' && error.trim()) {
    return error
  }
  if (error && typeof error === 'object') {
    const record = error as Record<string, unknown>
    if (typeof record.message === 'string' && record.message.trim()) {
      return record.message
    }
    if (typeof record.errMsg === 'string' && record.errMsg.trim()) {
      return record.errMsg
    }
  }
  return '操作失败，请稍后重试'
}

export async function request<T>(
  config: ApiRequestConfig
): Promise<T> {
  const response = await http.request<T>(config)
  return response.data
}

export function isUnauthorizedError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401
}
