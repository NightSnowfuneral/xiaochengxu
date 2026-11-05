/** 后台与 FastAPI Admin 接口的 DTO。字段与后端保持 snake_case。 */

export type AdminRole = 'super' | 'normal'

export interface AdminProfile {
  id: number
  username: string
  role: AdminRole
  created_at: string
}

export interface AdminLoginResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  admin: AdminProfile
}

export interface MessageResponse {
  message: string
}

export interface PageResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Course {
  id: number
  title: string
  lecturer: string
  description: string
  price: number
  cover_big: string
  cover_small: string
  icon_url: string
  is_hot_topic: boolean
  created_at: string
  updated_at: string
}

export interface CourseCreatePayload {
  title: string
  lecturer: string
  description: string
  price: number
  cover_big: string
  cover_small: string
  icon_url: string
  is_hot_topic: boolean
}

export type CourseUpdatePayload = Partial<CourseCreatePayload>

export interface Lesson {
  id: number
  course_id: number
  title: string
  sort_order: number
  file_id: string
  vod_file_id: string
  video_name: string | null
  cover_url: string | null
  duration_seconds: number
  created_at: string
  updated_at: string
}

export interface LessonCreatePayload {
  course_id: number
  title: string
  file_id: string
  sort_order?: number
}

export interface LessonUpdatePayload {
  title?: string
  file_id?: string
  sort_order?: number
}

/** 媒资转码状态：0=转码中，1=正常可用，2=上传/转码失败。 */
export type VodMediaStatus = 0 | 1 | 2

export interface VodMedia {
  id: number
  file_id: string
  video_name: string
  duration_seconds: number
  cover_url: string | null
  uploader_id: number | null
  status: VodMediaStatus
  fail_reason: string | null
  created_at: string
  updated_at: string
}

export interface VodMediaUpdatePayload {
  video_name: string
}

export interface VodMediaListParams {
  page: number
  page_size: number
  keyword?: string
  file_id?: string
  status?: VodMediaStatus
}

export interface VodMediaSyncResponse {
  items: VodMedia[]
  message: string
}

export interface ImagePresignResult {
  object_key: string
  upload_url: string
  public_url: string
  headers: Record<string, string>
  expires_in: number
  method: string
}

/** 赠课有效期：一年（从赠课当天起算）或永久有效。 */
export type GiftValidity = 'one_year' | 'permanent'

export interface GiftGrantPayload {
  mobile: string
  course_id: number
  validity: GiftValidity
}

export interface GiftGrantResult {
  mobile: string
  course_id: number
  user_id: number
  gifted: boolean
  gift_log_id: number | null
  message: string
}

export interface GiftLog {
  id: number
  admin_id: number
  mobile: string
  course_id: number
  created_at: string
  admin_username: string | null
  course_title: string | null
}

export interface GiftLogFilters {
  mobile?: string
  course_id?: number
  admin_id?: number
  created_from?: string
  created_to?: string
}

export type OrderStatus = 'pending' | 'paid' | 'closed' | 'refunded'

export interface AdminOrder {
  id: number
  order_no: string
  user_id: number
  course_id: number
  amount: number
  status: OrderStatus
  paid_at: string | null
  created_at: string
  user_mobile: string | null
  course_title: string | null
}

export type UserCourseSource = 'buy' | 'gift'

/** 后台展示的授权状态：有效 / 已过期 / 永久有效。 */
export type UserCourseValidityStatus = 'valid' | 'expired' | 'permanent'

export interface AdminUserCourse {
  id: number
  user_id: number
  user_mobile: string | null
  course_id: number
  course_title: string | null
  source: UserCourseSource
  valid_start_at: string | null
  valid_end_at: string | null
  status: UserCourseValidityStatus
  created_at: string
}

export interface AdminUserCourseQueryParams {
  page: number
  page_size: number
  mobile?: string
  course_id?: number
  status?: UserCourseValidityStatus
}

/** 用户课程管理页按手机号或用户 ID 查到的用户。 */
export interface AdminUserSummary {
  user_id: number
  nickname: string | null
  mobile: string | null
  avatar_url: string | null
}

/** 用户课程管理页的来源：购买或后台赠课。 */
export type AdminUserCourseSource = 'purchase' | 'gift'

/** 用户课程管理操作类型：首次赠送 / 重置有效期 / 收回。 */
export type AdminUserCourseAction = 'gift' | 'reset' | 'revoke'

export interface AdminUserCourseItem {
  course_id: number
  course_title: string
  course_cover: string | null
  source: AdminUserCourseSource
  valid_start_at: string | null
  expire_time: string | null
  expired: boolean
  created_at: string
}

export interface AdminGrantCoursePayload {
  user_id: number
  course_id: number
  valid_days: number
}

export interface AdminGrantCourseResult {
  user_id: number
  course_id: number
  source: AdminUserCourseSource
  valid_start_at: string
  expire_time: string
  expired: boolean
  action: AdminUserCourseAction
  log_id: number
  message: string
}

export interface AdminRevokeCoursePayload {
  user_id: number
  course_id: number
}

export interface AdminRevokeCourseResult {
  user_id: number
  course_id: number
  revoked: boolean
  log_id: number
  message: string
}

export interface SystemConfig {
  id: number
  config_key: string
  config_value: string
  default_value: string
  description: string | null
  updated_at: string
}

export interface SystemConfigListResponse {
  items: SystemConfig[]
}
