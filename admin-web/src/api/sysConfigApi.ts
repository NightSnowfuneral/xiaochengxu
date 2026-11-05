import type { SystemConfig, SystemConfigListResponse } from '../types'
import { apiGet, apiPost, apiPut } from './request'

export function listAdminConfigs(): Promise<SystemConfigListResponse> {
  return apiGet<SystemConfigListResponse>('/admin/configs')
}

export function updateAdminConfig(
  configKey: string,
  configValue: string
): Promise<SystemConfig> {
  return apiPut<SystemConfig>(
    `/admin/configs/${encodeURIComponent(configKey)}`,
    { config_value: configValue }
  )
}

export function resetAdminConfig(configKey: string): Promise<SystemConfig> {
  return apiPost<SystemConfig>(
    `/admin/configs/${encodeURIComponent(configKey)}/reset`
  )
}

export function resetAllAdminConfigs(): Promise<SystemConfigListResponse> {
  return apiPost<SystemConfigListResponse>('/admin/configs/reset')
}
