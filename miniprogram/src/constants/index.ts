import type { PlaybackRate } from '../types/vod'

/** 前端内置配置兜底；后端配置异常时仍然可以完整渲染。 */
export const DEFAULT_CONFIG_VALUES: Record<string, string> = {
  home_page_title: '禾下美学院',
  academy_page_title: '商学院课程广场',
  hot_topic_title: '热门课程',
  hot_topic_more_text: '查看更多',
  buy_btn_text: '立即购买',
  login_modal_title: '登录后继续学习',
  home_notice: '欢迎来到禾下美学院',
  search_placeholder: '搜索课程名称',
  tab_home_text: '首页',
  tab_course_text: '课程'
}

/** 后端现有配置键 → 前端业务使用的配置键。 */
export const CONFIG_KEY_ALIASES: Record<string, string[]> = {
  home_page_title: ['home_page_title', 'home_title'],
  academy_page_title: ['academy_page_title', 'course_square_title'],
  hot_topic_title: ['hot_topic_title', 'home_hot_title'],
  hot_topic_more_text: ['hot_topic_more_text'],
  buy_btn_text: ['buy_btn_text'],
  login_modal_title: ['login_modal_title'],
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

export const STORAGE_PERSIST_KEY = 'huahuo-spark-root'
