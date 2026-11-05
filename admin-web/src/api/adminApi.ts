import type {
  AdminLoginResponse,
  AdminOrder,
  AdminProfile,
  AdminUserCourse,
  AdminUserCourseQueryParams,
  MessageResponse,
  OrderStatus,
  PageResponse
} from '../types'
import { apiGet, apiPost, compactParams } from './request'

export interface AdminLoginPayload {
  username: string
  password: string
}

export function adminLoginApi(
  payload: AdminLoginPayload
): Promise<AdminLoginResponse> {
  return apiPost<AdminLoginResponse>('/admin/auth/login', payload)
}

export function fetchAdminProfileApi(): Promise<AdminProfile> {
  return apiGet<AdminProfile>('/admin/auth/profile')
}

/**
 * JWT 无状态退出；后端只做确认，前端负责清空本地会话。
 * 显式传入 token，因为调用时本地会话可能已被先行清除。
 */
export function adminLogoutApi(token?: string): Promise<MessageResponse> {
  return apiPost<MessageResponse>(
    '/admin/auth/logout',
    undefined,
    token ? { headers: { Authorization: `Bearer ${token}` } } : undefined
  )
}

export interface AdminOrderQueryParams {
  page: number
  page_size: number
  order_no?: string
  user_id?: number
  course_id?: number
  mobile?: string
  status?: OrderStatus
  created_from?: string
  created_to?: string
}

/**
 * 后台订单查询为只读接口：没有下单、支付或改状态调用。
 * 订单查询放在 adminApi 中，与后台认证共用同一服务模块。
 */
export function fetchAdminOrders(
  params: AdminOrderQueryParams
): Promise<PageResponse<AdminOrder>> {
  return apiGet<PageResponse<AdminOrder>>('/admin/orders', {
    params: compactParams({
      page: params.page,
      page_size: params.page_size,
      order_no: params.order_no?.trim(),
      user_id: params.user_id,
      course_id: params.course_id,
      mobile: params.mobile?.trim(),
      status: params.status,
      created_from: params.created_from,
      created_to: params.created_to
    })
  })
}

/** 后台用户课程授权查询（只读）：购买与赠课记录统一展示有效期状态。 */
export function fetchAdminUserCourses(
  params: AdminUserCourseQueryParams
): Promise<PageResponse<AdminUserCourse>> {
  return apiGet<PageResponse<AdminUserCourse>>('/admin/user-courses', {
    params: compactParams({
      page: params.page,
      page_size: params.page_size,
      mobile: params.mobile?.trim(),
      course_id: params.course_id,
      status: params.status
    })
  })
}
