import Taro from '@tarojs/taro'

import { API_BASE_URL } from '../config'
import type {
  LogoutResponse,
  TokenCheckResponse,
  UserProfileResponse,
  WxLoginResponse
} from '../types'
import { ApiError, reportUnauthorized, request } from './request'
import { getAuthSession } from './session'

/**
 * 手机号快捷登录：同时提交 wx.login 的 loginCode 与 getPhoneNumber 的 phoneCode。
 * 手机号只由后端向微信换取，前端不接触明文手机号。
 */
export function wxLogin(
  loginCode: string,
  phoneCode: string
): Promise<WxLoginResponse> {
  return request<WxLoginResponse>({
    url: '/auth/wx-login',
    method: 'POST',
    data: { loginCode, phoneCode },
    skipAuthHandler: true
  })
}

/**
 * 退出登录：让后端把当前业务 Token 写入吊销名单。
 * 跳过全局 401 处理——登出流程自己负责清空本地状态。
 */
export function logoutRequest(token: string): Promise<LogoutResponse> {
  return request<LogoutResponse>({
    url: '/auth/logout',
    method: 'POST',
    data: { token },
    // 登出以本地清理为准，后端不可达时最多等待 3 秒。
    timeout: 3000,
    skipAuthHandler: true
  })
}

/**
 * 冷启动校验本地 Token 是否仍然有效。
 * 无效 / 已吊销时后端返回 valid=false（HTTP 200），由调用方清理本地登录态。
 */
export function tokenCheck(token: string): Promise<TokenCheckResponse> {
  return request<TokenCheckResponse>({
    url: '/auth/token-check',
    method: 'POST',
    data: { token },
    // 冷启动必须给出明确结果，网络异常时由调用方保留登录态，最多等待 5 秒。
    timeout: 5000,
    skipAuthHandler: true
  })
}

export function getProfile(): Promise<UserProfileResponse> {
  return request<UserProfileResponse>({
    url: '/client/user/profile',
    method: 'GET'
  })
}

export function updateProfile(
  nickname: string
): Promise<UserProfileResponse> {
  return request<UserProfileResponse>({
    url: '/client/user/profile',
    method: 'PUT',
    data: { nickname }
  })
}

interface UploadAvatarResult {
  statusCode: number
  data: string
}

/**
 * 头像经后端代理上传 COS：小程序只认 API 域名，COS 密钥不下发。
 * 这里不能手动设置 Content-Type，multipart boundary 由宿主生成。
 */
export async function uploadAvatar(
  filePath: string
): Promise<UserProfileResponse> {
  const { token } = getAuthSession()
  if (!token) {
    throw new ApiError('请先登录', 401, 'UNAUTHORIZED')
  }

  const result = (await Taro.uploadFile({
    url: `${API_BASE_URL}/client/user/avatar`,
    filePath,
    name: 'file',
    timeout: 60_000,
    header: { Authorization: `Bearer ${token}` }
  })) as UploadAvatarResult

  let body: unknown = null
  try {
    body = JSON.parse(result.data)
  } catch {
    body = null
  }

  if (result.statusCode < 200 || result.statusCode >= 300) {
    if (result.statusCode === 401) {
      // uploadFile 不走 axios 响应拦截器，这里补上统一的 401 登出处理。
      reportUnauthorized()
    }
    const errorBody = (body ?? {}) as {
      message?: unknown
      code?: unknown
    }
    throw new ApiError(
      typeof errorBody.message === 'string' && errorBody.message
        ? errorBody.message
        : '头像上传失败，请稍后重试',
      result.statusCode,
      typeof errorBody.code === 'string'
        ? errorBody.code
        : 'AVATAR_UPLOAD_FAILED'
    )
  }

  return body as UserProfileResponse
}
