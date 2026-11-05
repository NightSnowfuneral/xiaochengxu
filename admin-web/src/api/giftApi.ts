import type {
  GiftGrantPayload,
  GiftGrantResult,
  GiftLog,
  GiftLogFilters,
  PageResponse
} from '../types'
import { apiGet, apiPost, compactParams } from './request'

export interface GiftLogQueryParams extends GiftLogFilters {
  page: number
  page_size: number
}

/**
 * 赠课传 mobile + course_id + validity；幂等与日志留痕由后端事务保证。
 * 一年有效期从赠课操作时间（UTC）起算，永久有效两列均为 null。
 */
export function grantGiftApi(
  payload: GiftGrantPayload
): Promise<GiftGrantResult> {
  return apiPost<GiftGrantResult>('/admin/gifts', {
    mobile: payload.mobile.trim(),
    course_id: payload.course_id,
    validity: payload.validity
  })
}

export function listGiftLogsApi(
  params: GiftLogQueryParams
): Promise<PageResponse<GiftLog>> {
  return apiGet<PageResponse<GiftLog>>('/admin/gifts/logs', {
    params: compactParams({
      page: params.page,
      page_size: params.page_size,
      mobile: params.mobile?.trim(),
      course_id: params.course_id,
      admin_id: params.admin_id,
      created_from: params.created_from,
      created_to: params.created_to
    })
  })
}
