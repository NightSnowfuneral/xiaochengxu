import Taro from '@tarojs/taro'

import { API_BASE_URL } from '../config'
import type { UserProfileResponse, WxLoginResponse } from '../types'
import { ApiError, request } from './request'
import { getAuthSession } from './session'

export function wxLogin(code: string): Promise<WxLoginResponse> {
  return request<WxLoginResponse>({
    url: '/client/auth/wx-login',
    method: 'POST',
    data: { code }
  })
}

export function bindMobile(code: string): Promise<UserProfileResponse> {
  return request<UserProfileResponse>({
    url: '/client/auth/bind-mobile',
    method: 'POST',
    data: { code }
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
