import type { PublicConfigResponse } from '../types'
import { request } from './request'

/** 公开配置，不要求 JWT；C 端每次 onShow 拉取。 */
export function getPublicConfigs(): Promise<PublicConfigResponse> {
  return request<PublicConfigResponse>({
    url: '/config',
    method: 'GET'
  })
}
