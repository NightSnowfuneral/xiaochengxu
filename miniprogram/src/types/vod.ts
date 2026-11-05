/**
 * 视频播放相关类型定义。
 *
 * 与后端契约：
 * - 播放地址由 `GET /api/v1/client/lessons/{lessonId}/play-auth` 下发；
 * - 播放完成由 `POST /api/vod/finish-lesson` 标记，接口幂等；
 * - 前端不持有 VOD PlayKey / 腾讯云 API 密钥。
 */

/** 播放器支持的倍速；必须与页面上的倍速按钮一一对应。 */
export type PlaybackRate = 0.5 | 0.75 | 1 | 1.25 | 1.5 | 2

/** 播放鉴权响应；`play_url` 为 null 表示 VOD 暂无可用播放地址。 */
export interface PlaybackAuthResponse {
  lesson_id: number
  course_id: number
  file_id: string
  app_id: number
  expire_at: number
  signature: string
  /** 服务端解析并签名的播放地址。 */
  play_url: string | null
  /** 上次播放位置（秒）；看完后服务端会归零。 */
  last_position: number
  /** 视频时长（秒）；0 表示 VOD 尚未返回。 */
  duration_seconds?: number
}

/** 播放页常驻课时列表的条目，来自课程详情 `lessons` 字段。 */
export interface VodLesson {
  id: number
  title: string
  /** 视频时长（秒）；0 / 缺省时展示 --:--。 */
  duration_seconds?: number
  /** 当前用户是否已看完。 */
  is_finished?: boolean
}

/** 原生 video 事件 detail 中本组件会用到的字段（跨基础库保持宽松）。 */
export interface VodVideoDetail {
  currentTime?: number
  duration?: number
  errMsg?: string
  message?: string
  /** 原生 fullscreenchange 事件的字段名是 fullScreen（大写 S）。 */
  fullScreen?: boolean
}

/** 原生 video 事件的宽松结构，避免绑定到 Taro 内部事件类型。 */
export interface VodVideoEvent {
  type?: string
  detail?: VodVideoDetail
}

/** 原生 Slider 事件的宽松结构。 */
export interface VodSliderEvent {
  detail?: {
    value?: number
  }
}

/** 播放器组件对外暴露的属性。 */
export interface VodPlayerProps {
  /** 原生 video 的 id，VideoContext 依赖它，同一页面内必须唯一。 */
  videoId: string
  /** 服务端签发的播放地址。 */
  src: string
  /** 视频标题（传给原生 video，不在自定义控制层展示）。 */
  title?: string
  /** 当前课时导航标题；全屏时展示在左上角返回按钮右侧，与页面导航栏一致。 */
  navTitle?: string
  /** 续播位置（秒），仅首次加载生效。 */
  initialTime?: number
  /** 封面地址；原生 video 在 controls=false 时不展示 poster，这里保留扩展位。 */
  poster?: string
  /** 是否自动播放；小程序通常要求用户先交互。 */
  autoplay?: boolean
  /** 页面内全屏状态，由页面持有，切换课时重挂后保持不变。 */
  fullscreen?: boolean
  /** 自定义倍速列表；默认使用全局 PLAYBACK_RATES。 */
  rates?: readonly PlaybackRate[]
  /** 下一课；没有下一课时为 null。 */
  nextLesson?: VodLesson | null
  /** 自动连播开关，由页面持有，切换课时后仍保持。 */
  autoNext?: boolean
  /** 自动连播开关变更。 */
  onAutoNextChange?: (enabled: boolean) => void
  /** 选集 / 连播切换课时；由页面负责重新获取播放授权。 */
  onSelectLesson?: (lesson: VodLesson) => void
  /**
   * 页面内全屏状态变化。
   *
   * 播放器负责全屏覆盖层，横屏由页面通过 `<PageMeta pageOrientation>`
   * 同步设置，因此需要把状态回传给页面。
   */
  onFullscreenChange?: (fullscreen: boolean) => void
  /** 播放进度回调，单位：秒。 */
  onTimeUpdate?: (currentTime: number, duration: number) => void
  /** 倍速切换成功回调。 */
  onPlaybackRateChange?: (rate: PlaybackRate) => void
  /** 播放完成回调；由页面负责调用 finish-lesson。 */
  onEnded?: () => void
  /** 播放失败回调，message 可直接展示。 */
  onError?: (message: string) => void
}

/** 看完上报入参。 */
export interface FinishLessonRequest {
  lesson_id: number
}

/** 看完上报出参。 */
export interface FinishLessonResponse {
  lesson_id: number
  is_finished: boolean
  /** 首次看完时间（数据库服务器时间的 ISO 字符串）；重复调用不变。 */
  finished_at: string | null
  /** 看完后归零的续播位置。 */
  last_position: number
}

/** 页面里的完成上报状态，用于渲染提示与重试入口。 */
export type FinishLessonStatus = 'idle' | 'pending' | 'done' | 'error'
