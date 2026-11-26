import type {
  Course,
  CourseCreatePayload,
  CourseStatus,
  CourseUpdatePayload,
  ImagePresignResult,
  MessageResponse,
  PageResponse
} from '../types'
import { apiDelete, apiGet, apiPost, apiPut, compactParams } from './request'

export interface AdminCourseListParams {
  page?: number
  page_size?: number
  keyword?: string
  /** 传 true 只看热门；不传或 false 表示全部，因此调用方只在需要时传 true。 */
  is_hot_topic?: boolean
  /** 不传返回全部状态。 */
  status?: CourseStatus
}

export function listAdminCourses(
  params: AdminCourseListParams = {}
): Promise<PageResponse<Course>> {
  return apiGet<PageResponse<Course>>('/admin/courses', {
    params: compactParams({
      page: params.page,
      page_size: params.page_size,
      keyword: params.keyword?.trim(),
      is_hot_topic: params.is_hot_topic,
      status: params.status
    })
  })
}

export function getAdminCourse(courseId: number): Promise<Course> {
  return apiGet<Course>(`/admin/courses/${courseId}`)
}

export function createAdminCourse(
  payload: CourseCreatePayload
): Promise<Course> {
  return apiPost<Course>('/admin/courses', payload)
}

export function updateAdminCourse(
  courseId: number,
  payload: CourseUpdatePayload
): Promise<Course> {
  return apiPut<Course>(`/admin/courses/${courseId}`, payload)
}

export function deleteAdminCourse(courseId: number): Promise<MessageResponse> {
  return apiDelete<MessageResponse>(`/admin/courses/${courseId}`)
}

/** 上下架课程；接口使用需求指定的单数路径。 */
export function changeAdminCourseStatus(
  courseId: number,
  status: CourseStatus
): Promise<Course> {
  return apiPut<Course>(`/admin/course/${courseId}/change-status`, { status })
}

export interface ImagePresignParams {
  filename: string
  content_type: string
  expires_in?: number
}

/** 只签发短期 PUT 预签名，COS 密钥不会下发到浏览器。 */
export function getImageUploadPresign(
  params: ImagePresignParams
): Promise<ImagePresignResult> {
  // 后端使用 POST 路由，但 filename/content_type/expires_in 均从 query 读取。
  return apiPost<ImagePresignResult>(
    '/admin/courses/image-presign',
    undefined,
    {
      params: compactParams({
        filename: params.filename,
        content_type: params.content_type,
        expires_in: params.expires_in ?? 600
      })
    }
  )
}
