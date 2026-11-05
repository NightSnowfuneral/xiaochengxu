export interface AuthUser {
  id: number
  nickname: string
  mobile: string | null
  avatar: string
  /** C 端 JWT；与 Admin Token 完全隔离，仅保存在本机。 */
  token?: string
}

export interface UserProfileResponse {
  id: number
  mobile: string | null
  nickname: string | null
  avatar_url: string | null
  created_at: string
  updated_at: string
}

export interface WxLoginResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  is_new_user: boolean
  user: UserProfileResponse
}

export interface PublicConfigResponse {
  configs: Record<string, string>
}

export interface PageResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface CourseListItem {
  id: number
  title: string
  lecturer: string
  price: number
  cover_small: string
  icon_url: string
  is_hot_topic: boolean
  /**
   * 浏览量为可选展示字段；后端当前不返回该字段时，前端展示“热门推荐”，
   * 不伪造浏览数据。
   */
  view_count?: number
}

export interface LessonBrief {
  id: number
  title: string
  /** 视频时长（秒）；0 表示后端尚未从 VOD 取得。 */
  duration_seconds?: number
  /** 当前用户是否已看完。 */
  is_finished?: boolean
}

export interface CourseDetail extends CourseListItem {
  description: string
  cover_big: string
  created_at: string
  updated_at: string
  lessons: LessonBrief[]
  /** 由后端基于 user_course 实时判定，前端不得自行推断。 */
  is_owned: boolean
}

// 播放相关类型集中定义在 types/vod.ts；这里保留转出以兼容现有导入路径。
export type {
  FinishLessonRequest,
  FinishLessonResponse,
  FinishLessonStatus,
  PlaybackAuthResponse,
  PlaybackRate,
  VodPlayerProps,
  VodVideoDetail,
  VodVideoEvent
} from './vod'

export interface WeChatPayParams {
  time_stamp: string
  nonce_str: string
  package: string
  sign_type: string
  pay_sign: string
}

export type OrderStatus = 'pending' | 'paid' | 'closed' | 'refunded'

export interface OrderCreateResponse {
  order_no: string
  course_id: number
  amount: number
  status: OrderStatus
  payment: WeChatPayParams
}

export interface OrderResponse {
  order_no: string
  course_id: number
  amount: number
  status: OrderStatus
  paid_at: string | null
  created_at: string
}

/** 统一支付查询结果；不包含任何课程有效期字段。 */
export interface PaymentOrderResponse extends OrderResponse {
  course_title: string | null
}

export interface ApiErrorBody {
  code: string
  message: string
  data: unknown
}
