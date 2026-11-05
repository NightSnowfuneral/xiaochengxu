import axios, { type AxiosError, type AxiosRequestConfig } from 'axios'

import { getAdminToken, notifyAdminSessionExpired } from '../utils/session'

interface BackendErrorBody {
  code?: string
  message?: string
  data?: unknown
}

export class ApiError extends Error {
  readonly code: string
  readonly status: number | null
  readonly details: unknown

  constructor(
    message: string,
    status: number | null,
    code: string,
    details: unknown
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

const rawBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'
const baseURL = rawBaseUrl.replace(/\/+$/, '')

const apiClient = axios.create({
  baseURL,
  timeout: 20000
})

apiClient.interceptors.request.use((config) => {
  const token = getAdminToken()
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  config.headers.set('Accept', 'application/json')
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (!axios.isAxiosError(error)) {
      return Promise.reject(
        new ApiError('请求失败，请稍后重试', null, 'UNKNOWN_ERROR', null)
      )
    }

    const axiosError = error as AxiosError<BackendErrorBody>
    const requestUrl = axiosError.config?.url ?? ''
    const isLoginRequest = requestUrl.includes('/admin/auth/login')
    const status = axiosError.response?.status ?? null
    const body = axiosError.response?.data
    const backendMessage =
      body && typeof body === 'object' && typeof body.message === 'string'
        ? body.message.trim()
        : ''

    // 登录接口的 401 表示账号或密码错误，不能触发会话过期跳转。
    if (status === 401 && !isLoginRequest) {
      notifyAdminSessionExpired('登录状态已过期，请重新登录')
    }

    let message = backendMessage
    if (!message) {
      if (!axiosError.response) {
        message =
          axiosError.code === 'ECONNABORTED'
            ? '请求超时，请稍后重试'
            : '无法连接服务器，请检查网络或 API 地址'
      } else {
        message = `请求失败（HTTP ${status ?? '未知'}）`
      }
    }

    const code =
      body && typeof body.code === 'string' ? body.code : 'HTTP_ERROR'
    return Promise.reject(
      new ApiError(message, status, code, body?.data ?? null)
    )
  }
)

export async function apiGet<T>(
  url: string,
  config?: AxiosRequestConfig
): Promise<T> {
  const response = await apiClient.get<T>(url, config)
  return response.data
}

export async function apiPost<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig
): Promise<T> {
  const response = await apiClient.post<T>(url, data, config)
  return response.data
}

export async function apiPut<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig
): Promise<T> {
  const response = await apiClient.put<T>(url, data, config)
  return response.data
}

export async function apiDelete<T>(
  url: string,
  config?: AxiosRequestConfig
): Promise<T> {
  const response = await apiClient.delete<T>(url, config)
  return response.data
}

export interface UploadProgressOptions {
  /** 0-100；浏览器拿不到总大小时回调 -1。 */
  onProgress?: (percent: number) => void
  signal?: AbortSignal
}

/**
 * 文件上传：不设置 Content-Type，交给浏览器生成 multipart boundary；
 * 上传大文件耗时较长，单独关闭 axios 的 20s 超时。
 */
export async function apiUpload<T>(
  url: string,
  formData: FormData,
  options: UploadProgressOptions = {}
): Promise<T> {
  const response = await apiClient.post<T>(url, formData, {
    timeout: 0,
    signal: options.signal,
    onUploadProgress: (event) => {
      if (!options.onProgress) {
        return
      }
      if (typeof event.total === 'number' && event.total > 0) {
        const percent = Math.min(
          100,
          Math.max(0, Math.round((event.loaded * 100) / event.total))
        )
        options.onProgress(percent)
      } else {
        options.onProgress(-1)
      }
    }
  })
  return response.data
}

/** 过滤空查询参数，避免把空字符串当作筛选条件发给后端。 */
export function compactParams(
  params: Record<string, unknown>
): Record<string, unknown> {
  const result: Record<string, unknown> = {}
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      result[key] = value
    }
  })
  return result
}

export function getErrorMessage(error: unknown): string {
  if (typeof error === 'string' && error.trim()) {
    return error
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return '操作失败，请稍后重试'
}
