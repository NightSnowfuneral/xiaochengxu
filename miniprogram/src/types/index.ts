export interface AuthUser {
  id: number
  nickname: string
  /** 展示用脱敏手机号（如 138****8000）；登录时由手机号授权写入。 */
  mobile: string | null
  avatar: string
  /** 本次登录的微信 openid；仅本机记录，不作为鉴权凭证。 */
  openid?: string
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

/** 手机号快捷登录返回的用户信息（camelCase，与后端契约一致）。 */
export interface LoginUserInfo {
  userId: number
  phoneMasked: string | null
  nickname: string | null
  avatar: string | null
  openid: string | null
  isNewUser: boolean
  isMerged: boolean
}

export interface WxLoginResponse {
  token: string
  userInfo: LoginUserInfo
}

/** 冷启动 Token 校验结果；无效 Token 返回 valid=false，不是 401。 */
export interface TokenCheckResponse {
  valid: boolean
  userInfo?: LoginUserInfo | null
}

/** 登出结果；无论 Token 是否已失效都返回成功。 */
export interface LogoutResponse {
  success: boolean
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
  /** 购买 / 赠课附赠的专项指导预约次数。 */
  appointment_quota: number
  /**
   * 可用的虚拟支付商品 ID；为空表示该课程未配置虚拟支付道具，
   * 前端不开放购买。仅作为下单入参，服务端会按课程与环境重新解析。
   */
  vpay_product_id?: string | null
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

/** 订单对外状态：待支付 / 已支付 / 已取消（closed）。 */
export type OrderStatus = 'pending' | 'paid' | 'closed'

/** 订单来源：wechat_pay=普通微信支付 v3；wx_vpay=小程序虚拟支付。 */
export type OrderSource = 'wechat_pay' | 'wx_vpay'

/** 下单结果公共字段：订单号、金额与状态。 */
export interface OrderCreatedBase {
  order_no: string
  course_id: number
  amount: number
  status: OrderStatus
}

/** 虚拟支付下单结果：订单 + wx.requestVirtualPayment 调起参数。 */
export interface VirtualPayCreateResponse extends OrderCreatedBase {
  out_trade_no: string
  /** 后端生成的 JSON 字符串，必须原样传给微信，不得重新序列化。 */
  sign_data: string
  pay_sig: string
  signature: string
  mode: 'short_series_goods'
  /** 0=正式，1=沙箱。 */
  env: 0 | 1
}

export interface OrderResponse {
  order_no: string
  course_id: number
  amount: number
  status: OrderStatus
  paid_at: string | null
  created_at: string
}

/** 订单中心单条记录：在订单状态上补充课程标题与封面。 */
export interface ClientOrderResponse extends OrderResponse {
  course_title: string | null
  course_cover: string | null
  /** 订单来源：历史 v3 订单可能为 wechat_pay，新订单均为 wx_vpay。 */
  source?: OrderSource
}

/** 统一支付查询结果；不包含任何课程有效期字段。 */
export interface PaymentOrderResponse extends OrderResponse {
  course_title: string | null
}

export type AppointmentStatus = 'pending' | 'completed' | 'expired'

export interface AppointmentOverview {
  remaining_total: number
  purchased_total: number
  used_total: number
  pending_count: number
  completed_count: number
  /** 当前配置的最少提前 / 取消时限（小时）。 */
  min_advance_hours: number
}

export interface AppointmentAvailableDate {
  /** YYYY-MM-DD（北京时间）。 */
  date: string
  /** ISO 星期：1=周一 … 7=周日。 */
  weekday: number
  has_available: boolean
}

export interface AppointmentSlot {
  /** HH:MM。 */
  start_time: string
  end_time: string
  capacity: number
  booked: number
  available: number
}

export interface AppointmentAvailableSlots {
  enabled: boolean
  date: string
  dates: AppointmentAvailableDate[]
  slots: AppointmentSlot[]
}

export interface AppointmentItem {
  appointment_no: string
  /** YYYY-MM-DD（北京时间）。 */
  appointment_date: string
  start_time: string
  end_time: string
  status: AppointmentStatus
  user_remark: string | null
  admin_remark: string | null
  created_at: string
  completed_at: string | null
  cancelled_at: string | null
}

export interface AppointmentCreatePayload {
  appointment_date: string
  /** HH:MM。 */
  start_time: string
  user_remark?: string
}

export interface AppointmentCreateResult {
  appointment: AppointmentItem
  remaining_count: number
  message: string
}

export interface AppointmentCancelResult {
  appointment_no: string
  remaining_count: number
  message: string
}

export interface ApiErrorBody {
  code: string
  message: string
  data: unknown
}
