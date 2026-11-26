import type {
  AdminAppointment,
  AdminAppointmentCancelResult,
  AdminAppointmentQuota,
  AdminAppointmentQuotaLog,
  AdminAppointmentQueryParams,
  AdminAppointmentQuotaQueryParams,
  AdminQuotaGrantPayload,
  AdminQuotaGrantResult,
  AdminQuotaLogQueryParams,
  AdminQuotaReclaimPayload,
  AppointmentSlotConfig,
  AppointmentSlotConfigPayload,
  PageResponse
} from '../types'
import { apiGet, apiPost, apiPut, compactParams } from './request'

/** 后台预约分页查询。 */
export function fetchAdminAppointments(
  params: AdminAppointmentQueryParams
): Promise<PageResponse<AdminAppointment>> {
  return apiGet<PageResponse<AdminAppointment>>('/admin/appointments', {
    params: compactParams({
      page: params.page,
      page_size: params.page_size,
      status: params.status === 'all' ? undefined : params.status,
      keyword: params.keyword?.trim(),
      date_start: params.date_start,
      date_end: params.date_end
    })
  })
}

/** 确认预约完成：不退还次数。 */
export function completeAdminAppointment(
  appointmentNo: string,
  adminRemark?: string
): Promise<AdminAppointment> {
  return apiPost<AdminAppointment>(
    `/admin/appointments/${encodeURIComponent(appointmentNo)}/complete`,
    { admin_remark: adminRemark?.trim() || undefined }
  )
}

/** 管理员强制取消：软删除并退还 1 次。 */
export function cancelAdminAppointment(
  appointmentNo: string,
  adminRemark?: string
): Promise<AdminAppointmentCancelResult> {
  return apiPost<AdminAppointmentCancelResult>(
    `/admin/appointments/${encodeURIComponent(appointmentNo)}/cancel`,
    { admin_remark: adminRemark?.trim() || undefined }
  )
}

/** 次数账户分页查询。 */
export function fetchAdminAppointmentQuotas(
  params: AdminAppointmentQuotaQueryParams
): Promise<PageResponse<AdminAppointmentQuota>> {
  return apiGet<PageResponse<AdminAppointmentQuota>>(
    '/admin/appointment-quotas',
    {
      params: compactParams({
        page: params.page,
        page_size: params.page_size,
        keyword: params.keyword?.trim(),
        has_remaining: params.has_remaining ? true : undefined
      })
    }
  )
}

/** 手工分配次数；user_id 与 user_phone 二选一。 */
export function grantAdminAppointmentQuota(
  payload: AdminQuotaGrantPayload
): Promise<AdminQuotaGrantResult> {
  return apiPost<AdminQuotaGrantResult>(
    '/admin/appointment-quotas/grant',
    {
      user_id: payload.user_id,
      user_phone: payload.user_phone,
      count: payload.count,
      remark: payload.remark?.trim() || undefined
    }
  )
}

/** 回收次数：只能回收未使用的剩余次数。 */
export function reclaimAdminAppointmentQuota(
  payload: AdminQuotaReclaimPayload
): Promise<AdminQuotaGrantResult> {
  return apiPost<AdminQuotaGrantResult>(
    '/admin/appointment-quotas/reclaim',
    {
      quota_id: payload.quota_id,
      count: payload.count,
      remark: payload.remark?.trim() || undefined
    }
  )
}

/** 次数变动流水分页查询。 */
export function fetchAdminAppointmentQuotaLogs(
  params: AdminQuotaLogQueryParams
): Promise<PageResponse<AdminAppointmentQuotaLog>> {
  return apiGet<PageResponse<AdminAppointmentQuotaLog>>(
    '/admin/appointment-quotas/logs',
    {
      params: compactParams({
        page: params.page,
        page_size: params.page_size,
        user_id: params.user_id,
        quota_id: params.quota_id
      })
    }
  )
}

export function fetchAppointmentSlotConfig(): Promise<AppointmentSlotConfig> {
  return apiGet<AppointmentSlotConfig>('/admin/appointment-slot-config')
}

export function saveAppointmentSlotConfig(
  payload: AppointmentSlotConfigPayload
): Promise<AppointmentSlotConfig> {
  return apiPut<AppointmentSlotConfig>(
    '/admin/appointment-slot-config',
    payload
  )
}
