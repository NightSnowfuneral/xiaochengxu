import type { PlaybackRate } from '../types/vod'

/** 前端内置配置兜底；后端配置异常时仍然可以完整渲染。 */
export const DEFAULT_CONFIG_VALUES: Record<string, string> = {
  home_page_title: '禾下美学院',
  home_subtitle: '以系统课程，点亮每一次成长',
  academy_page_title: '商学院课程广场',
  hot_topic_title: '热门课程',
  hot_topic_more_text: '查看更多',
  buy_btn_text: '立即购买',
  home_notice: '欢迎来到禾下美学院',
  search_placeholder: '搜索课程名称',
  tab_home_text: '首页',
  tab_course_text: '课程'
}

/** 后端现有配置键 → 前端业务使用的配置键。 */
export const CONFIG_KEY_ALIASES: Record<string, string[]> = {
  home_page_title: ['home_page_title', 'home_title'],
  home_subtitle: ['home_subtitle'],
  academy_page_title: ['academy_page_title', 'course_square_title'],
  hot_topic_title: ['hot_topic_title', 'home_hot_title'],
  hot_topic_more_text: ['hot_topic_more_text'],
  buy_btn_text: ['buy_btn_text'],
  home_notice: ['home_notice'],
  search_placeholder: ['search_placeholder'],
  tab_home_text: ['tab_home_text'],
  tab_course_text: ['tab_course_text']
}

export const TAB_ROUTES = ['pages/home/index', 'pages/academy/index'] as const

export const PROGRESS_REPORT_INTERVAL_MS = 15_000

/**
 * 播放器倍速选项。
 * 切换通过 VideoContext.playbackRate(rate) 完成，要求基础库 >= 2.13.0；
 * 低版本基础库只会在设置时静默失败，不影响正常播放。
 */
export const PLAYBACK_RATES: readonly PlaybackRate[] = [
  0.5,
  0.75,
  1,
  1.25,
  1.5,
  2
]
export const ORDER_POLL_INTERVAL_MS = 2_000
export const ORDER_POLL_MAX_ATTEMPTS = 60

export const DEFAULT_PAGE_SIZE = 10
export const HOT_COURSE_PAGE_SIZE = 6

/** redux-persist 根 key；登出与冷启动校验失效时会整体清除。 */
export const STORAGE_PERSIST_KEY = 'huahuo-spark-root'

/**
 * redux-persist 实际写入 Storage 的 key。库默认给 config.key 加上
 * `persist:` 前缀，删除时必须使用这个完整键。
 */
export const STORAGE_PERSIST_STORAGE_KEY = `persist:${STORAGE_PERSIST_KEY}`

/** 历史版本写入的本机快照键，仅保留用于登出时清理残留。 */
export const LOGIN_TOKEN_KEY = 'token'
export const LOGIN_USER_INFO_KEY = 'userInfo'
/** openid 仅记录本次微信身份，不参与鉴权；登出后可保留。 */
export const LOGIN_OPENID_KEY = 'openid'

/**
 * 登录相关本地缓存键。登出时逐个删除，避免旧版本或历史代码留下的
 * 身份信息在冷启动时被重新读取。
 *
 * openid 不属于登录凭证，登出时不删除。
 *
 * 注意：微信 session_key 只存在于微信服务端，小程序本地从未保存，
 * 这里也不得添加或操作任何与 session_key 相关的键。
 */
export const LOGIN_STORAGE_KEYS: readonly string[] = [
  STORAGE_PERSIST_STORAGE_KEY,
  LOGIN_TOKEN_KEY,
  LOGIN_USER_INFO_KEY,
  'userId',
  'access_token',
  'auth'
]
