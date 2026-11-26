import type {
  AppointmentAvailableSlots,
  AppointmentCancelResult,
  AppointmentCreatePayload,
  AppointmentCreateResult,
  AppointmentItem,
  AppointmentOverview,
  AppointmentStatus,
  PageResponse
} from '../types'
import { request } from './request'

export interface MyAppointmentListParams {
  status?: AppointmentStatus
  page?: number
  pageSize?: number
}

/** 顶部次数概览：剩余、累计、已用与分课程次数账户。 */
export function getAppointmentOverview(): Promise<AppointmentOverview> {
  return request<AppointmentOverview>({
    url: '/client/appointments/overview',
    method: 'GET'
  })
}

/**
 * 可预约日期与指定日期的时段。
 * 不传日期时后端返回今天与未来 advance_days 天，并附带今天的时段。
 */
export function getAvailableSlots(
  date?: string
): Promise<AppointmentAvailableSlots> {
  return request<AppointmentAvailableSlots>({
    url: '/client/appointments/available-slots',
    method: 'GET',
    params: date ? { date } : undefined
  })
}

export function getMyAppointments(
  params: MyAppointmentListParams = {}
): Promise<PageResponse<AppointmentItem>> {
  return request<PageResponse<AppointmentItem>>({
    url: '/client/appointments/my-list',
    method: 'GET',
    params: {
      status: params.status,
      page: params.page,
      page_size: params.pageSize
    }
  })
}

export function createAppointment(
  payload: AppointmentCreatePayload
): Promise<AppointmentCreateResult> {
  return request<AppointmentCreateResult>({
    url: '/client/appointments/create',
    method: 'POST',
    data: payload
  })
}

/** 取消预约；仅 pending 状态且距开始超过配置的最少提前时间时可取消。 */
export function cancelAppointment(
  appointmentNo: string
): Promise<AppointmentCancelResult> {
  return request<AppointmentCancelResult>({
    url: `/client/appointments/${encodeURIComponent(appointmentNo)}/cancel`,
    method: 'POST'
  })
}
