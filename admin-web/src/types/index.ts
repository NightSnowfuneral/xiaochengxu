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

/** 课程上下架状态：草稿 / 已上架 / 已下架。 */
export type CourseStatus = 'published' | 'draft' | 'offline'

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
  /** 购买 / 赠课附赠的专项指导预约次数。 */
  appointment_quota: number
  status: CourseStatus
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
  appointment_quota: number
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

/** 远程视频已入库时对应的本地媒资摘要。 */
export interface RemoteImportedRef {
  media_id: number
  video_name: string
  status: VodMediaStatus
  fail_reason: string | null
}

/** 腾讯云 VOD 视频库中的一条远程视频，以 FileId 与本地媒资对比。 */
export interface RemoteVodVideo {
  file_id: string
  video_name: string
  duration_seconds: number
  cover_url: string | null
  /** VOD 创建时间（ISO8601 UTC）。 */
  remote_created_at: string | null
  imported: RemoteImportedRef | null
}

export type RemoteVodImportFilter = 'all' | 'imported' | 'not_imported'

export interface RemoteVodListParams {
  page: number
  page_size: number
  keyword?: string
  imported?: RemoteVodImportFilter
}

export interface RemoteVodImportPayload {
  file_id: string
  video_name?: string
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

export type GiftDeliveryMode = 'direct' | 'pre_gift'
export type GiftDeliveryStatus =
  | 'delivered'
  | 'pending'
  | 'claimed'
  | 'duplicate'

export interface GiftGrantResult {
  mobile: string
  course_id: number
  user_id: number | null
  gifted: boolean
  gift_log_id: number | null
  pregift_id: number | null
  mode: GiftDeliveryMode
  status: GiftDeliveryStatus
  message: string
}

export interface GiftLog {
  id: number
  admin_id: number
  mobile: string
  user_id: number | null
  pregift_id: number | null
  course_id: number
  created_at: string
  admin_username: string | null
  course_title: string | null
}

export type AdminPregiftStatus = 'pending' | 'claimed'

export interface AdminPregift {
  id: number
  mobile: string
  course_id: number
  course_title: string | null
  admin_id: number
  admin_username: string | null
  valid_start_at: string | null
  valid_end_at: string | null
  appointment_quota_count: number
  claimed_user_id: number | null
  claimed_at: string | null
  claim_ip: string | null
  status: AdminPregiftStatus
  created_at: string
}

export interface AdminPregiftFilters {
  mobile?: string
  course_id?: number
  admin_id?: number
  status?: AdminPregiftStatus
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
  /** 订单详情展示的赠送预约次数快照。 */
  appointment_quota_count: number
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

/** 用户模糊搜索结果：用户信息 + 已拥有课程数。 */
export interface AdminUserListItem extends AdminUserSummary {
  owned_course_count: number
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

export interface AdminUserCourseLog {
  id: number
  admin_id: number
  admin_username: string | null
  user_id: number
  user_nickname: string | null
  user_mobile: string | null
  course_id: number
  course_title: string | null
  action: AdminUserCourseAction
  valid_days: number | null
  expire_time: string | null
  created_at: string
}

export interface AdminUserCourseLogQueryParams {
  page: number
  page_size: number
  user_id?: number
  course_id?: number
  admin_id?: number
  action?: AdminUserCourseAction
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

/** 专项指导预约状态：待完成 / 已完成 / 已过期；已取消记录不再展示。 */
export type AppointmentStatus = 'pending' | 'completed' | 'expired'

export type AppointmentQuotaSource =
  | 'purchase'
  | 'admin'
  | 'consume'
  | 'cancel'
  | 'reclaim'

/** 后台预约列表项。日期与时段为 Asia/Shanghai 墙上时间。 */
export interface AdminAppointment {
  id: number
  appointment_no: string
  user_id: number
  user_nickname: string | null
  user_mobile: string | null
  user_avatar_url: string | null
  appointment_date: string
  start_time: string
  end_time: string
  status: AppointmentStatus
  user_remark: string | null
  admin_remark: string | null
  created_at: string
  completed_at: string | null
  completed_by: number | null
  completed_by_name: string | null
  cancelled_at: string | null
}

export interface AdminAppointmentQueryParams {
  page: number
  page_size: number
  status?: AppointmentStatus | 'all'
  keyword?: string
  date_start?: string
  date_end?: string
}

/** 后台取消预约结果；记录软删除后不再展示。 */
export interface AdminAppointmentCancelResult {
  appointment_no: string
  message: string
}

/** 后台预约次数账户，按用户唯一。 */
export interface AdminAppointmentQuota {
  quota_id: number
  user_id: number
  user_nickname: string | null
  user_mobile: string | null
  user_avatar_url: string | null
  total_count: number
  used_count: number
  remaining: number
  latest_grant_at: string | null
  remark: string | null
}

export interface AdminAppointmentQuotaQueryParams {
  page: number
  page_size: number
  keyword?: string
  has_remaining?: boolean
}

export interface AdminQuotaGrantPayload {
  user_id?: number
  user_phone?: string
  count: number
  remark?: string
}

export interface AdminQuotaGrantResult {
  quota_id: number
  user_id: number
  total_count: number
  used_count: number
  remaining: number
  message: string
}

export interface AdminQuotaReclaimPayload {
  quota_id: number
  count: number
  remark?: string
}

/** 预约次数变动流水。 */
export interface AdminAppointmentQuotaLog {
  id: number
  quota_id: number
  user_id: number
  quantity: number
  source: AppointmentQuotaSource
  biz_no: string | null
  operator_id: number | null
  operator_name: string | null
  remark: string | null
  created_at: string
}

export interface AdminQuotaLogQueryParams {
  page: number
  page_size: number
  user_id?: number
  quota_id?: number
}

/** 预约时段配置（单行）。 */
export interface AppointmentSlotConfig {
  id: number
  weekdays: number[]
  work_start_time: string
  work_end_time: string
  slot_minutes: number
  slot_capacity: number
  advance_days: number
  min_advance_hours: number
  enabled: boolean
  updated_at: string
}

export type AppointmentSlotConfigPayload = Omit<
  AppointmentSlotConfig,
  'id' | 'updated_at'
>
