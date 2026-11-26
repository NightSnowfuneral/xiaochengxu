import type {
  AdminGrantCoursePayload,
  AdminGrantCourseResult,
  AdminRevokeCoursePayload,
  AdminRevokeCourseResult,
  AdminUserCourseItem,
  AdminUserCourseLog,
  AdminUserCourseLogQueryParams,
  AdminUserListItem,
  AdminUserSummary,
  PageResponse
} from '../types'
import { apiGet, apiPost, compactParams } from './request'

/** 按 11 位手机号或用户 ID 精确查找用户。 */
export function lookupAdminUser(keyword: string): Promise<AdminUserSummary> {
  return apiGet<AdminUserSummary>('/admin/users/lookup', {
    params: compactParams({ keyword: keyword.trim() })
  })
}

/** 手机号片段 / 昵称片段 / 用户 ID 模糊搜索用户，返回已拥有课程数。 */
export function searchAdminUsers(
  keyword: string,
  page: number,
  pageSize: number
): Promise<PageResponse<AdminUserListItem>> {
  return apiGet<PageResponse<AdminUserListItem>>('/admin/users/search', {
    params: compactParams({
      keyword: keyword.trim(),
      page,
      page_size: pageSize
    })
  })
}

/** 分页查询用户已拥有课程（购买 + 赠课）。 */
export function fetchAdminUserCoursesByUser(
  userId: number,
  page: number,
  pageSize: number
): Promise<PageResponse<AdminUserCourseItem>> {
  return apiGet<PageResponse<AdminUserCourseItem>>(
    `/admin/users/${userId}/courses`,
    {
      params: compactParams({ page, page_size: pageSize })
    }
  )
}

/**
 * 赠课 / 重置有效期：后端对同一 user + course 只保留一条授权，
 * 已拥有时更新有效期并把来源置为 gift。
 */
export function grantAdminUserCourse(
  payload: AdminGrantCoursePayload
): Promise<AdminGrantCourseResult> {
  return apiPost<AdminGrantCourseResult>('/admin/users/grant-course', {
    user_id: payload.user_id,
    course_id: payload.course_id,
    valid_days: payload.valid_days
  })
}

/** 收回课程授权：删除授权记录并写入操作日志。 */
export function revokeAdminUserCourse(
  payload: AdminRevokeCoursePayload
): Promise<AdminRevokeCourseResult> {
  return apiPost<AdminRevokeCourseResult>('/admin/users/revoke-course', {
    user_id: payload.user_id,
    course_id: payload.course_id
  })
}

/** 分页查询用户课程操作日志（赠课 / 重置有效期 / 收回）。 */
export function fetchAdminUserCourseLogs(
  params: AdminUserCourseLogQueryParams
): Promise<PageResponse<AdminUserCourseLog>> {
  return apiGet<PageResponse<AdminUserCourseLog>>(
    '/admin/user-courses/logs',
    {
      params: compactParams({
        page: params.page,
        page_size: params.page_size,
        user_id: params.user_id,
        course_id: params.course_id,
        admin_id: params.admin_id,
        action: params.action
      })
    }
  )
}
