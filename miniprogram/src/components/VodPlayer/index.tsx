import { useCallback, useEffect, useRef, useState } from 'react'
import { Slider, Text, Video, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import LoadingSpin from '../LoadingSpin'
import { PLAYBACK_RATES } from '../../constants'
import { formatPlayTime } from '../../utils/format'
import type {
  PlaybackRate,
  VodLesson,
  VodPlayerProps,
  VodSliderEvent,
  VodVideoEvent
} from '../../types/vod'

import './index.scss'

type VideoContext = ReturnType<typeof Taro.createVideoContext>

/** 控制栏自动隐藏时间。 */
const AUTO_HIDE_DELAY_MS = 3500
/** 自动连播倒计时秒数。 */
const AUTO_NEXT_SECONDS = 5
/** 横竖屏切换期间先抑制 loading 浮层，避免旋转瞬间闪黑 / 闪加载。 */
const FULLSCREEN_SETTLE_MS = 900
/** 旋转开始后稍等布局稳定，再恢复播放。 */
const FULLSCREEN_RESUME_DELAY_MS = 250
/** 捕获到旋转引起的 pause 后，再等布局稳定后重试播放。 */
const FULLSCREEN_PAUSE_RESUME_DELAY_MS = 300
/** 恢复播放后确认是否真正开始播放；没有则继续重试。 */
const FULLSCREEN_RESUME_VERIFY_DELAY_MS = 800
/**
 * 真机首次横屏时，原生 video 可能进入横屏 2 秒后才补发 pause（后续横屏
 * 有缓存会快很多）。这里保留一段续播意图窗口：窗口内收到的任何 pause 都
 * 视为旋转引起并自动恢复；用户主动暂停会立即清除该意图。
 */
const FULLSCREEN_AUTO_RESUME_MAX_MS = 6000
/**
 * 横竖屏切换后原生 video 会重新初始化，并把进度重置为 `initial-time`
 * （服务端续播点，可能比用户当前进度更晚）。在这段时间内监控进度跳变，
 * 发现后拉回切屏前的真实进度。
 */
const FULLSCREEN_POSITION_GUARD_MS = 6000
/** 播放中进度会正常前进，超过该秒数的跳变才视为旋转导致的重置。 */
const FULLSCREEN_POSITION_TOLERANCE_SECONDS = 3
/** 旋转结束后的二次位置校验，覆盖暂停态下不派发 timeupdate 的机型。 */
const FULLSCREEN_POSITION_CHECK_DELAY_MS = 2000
/**
 * 旋转把进度重置后需要主动 seek 回切屏前的位置。执行该补偿 seek 期间必须
 * 盖住原生播放器，否则用户会先看到 initial-time 处的旧画面，几秒后才跳回。
 * 这里给加载层一个兜底时长，避免 seek 异常时一直转圈。
 */
const FULLSCREEN_RESTORE_LOADING_MAX_MS = 3000
/**
 * 补偿 seek 可能被刚重绑的原生播放器忽略（尤其是连续横竖屏切换时），
 * 加载层期间按该间隔重发 seek，直到进度真正回到目标点。
 */
const FULLSCREEN_RESTORE_SEEK_RETRY_MS = 500
/**
 * 倍速切换：真机在播放中直接调用 playbackRate 时，部分机型会出现
 * 声音变速但画面定格。先暂停让原生播放器稳定，再设置倍速，随后恢复播放。
 */
const RATE_CHANGE_PAUSE_DELAY_MS = 80
const RATE_CHANGE_RESUME_DELAY_MS = 140
/**
 * iOS 在 seek / 重新起播 / 全屏重绑后会把倍速重置为 1.0，需要延迟重设；
 * 设置两次覆盖元数据尚未就绪时首次调用被静默忽略的机型。
 */
const RATE_REAPPLY_DELAYS_MS = [200, 700] as const
/**
 * 拖动定位：高倍速下直接 seek 会同时触发「重新缓冲 + playbackRate 重设」，
 * 部分机型画面定格但声音继续。这里先技术性暂停，等 onSeekComplete 后再
 * 恢复倍速，并留一小段缓冲窗口才开始播放。
 */
const SEEK_RESUME_DELAY_MS = 350
/** onSeekComplete 未按预期触发时的兜底恢复时间，避免一直停在加载态。 */
const SEEK_FALLBACK_RESUME_MS = 1800

function readNumber(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

/** 倍速文案固定为 0.5X / 0.75X / 1.0X / 1.25X / 1.5X / 2.0X。 */
function formatRate(rate: PlaybackRate): string {
  return `${Number.isInteger(rate) ? rate.toFixed(1) : rate}X`
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

function stopPropagation(event: { stopPropagation: () => void }): void {
  event.stopPropagation()
}

/**
 * 课程视频播放器（B 站移动端布局）。
 *
 * 平台约束（务必先看）：
 * 1. 本项目使用微信原生 `<video>`，不是 H5 的 TCPlayer。原生 controls 的
 *    内部元素（播放键、时间、进度条、全屏键）由微信客户端绘制，既不能
 *    重排，也不能把自定义按钮塞进原生控制栏；
 * 2. 因此要还原「左：播放/时间，中：进度，右：倍速/自动/全屏」的悬浮
 *    控制栏，只能在非全屏状态关闭原生 controls，自绘控制层；
 * 3. 进度条使用原生 `<Slider>`（不是用 View 手绘的进度条），拖动结束后
 *    通过 `VideoContext.seek()` 定位；
 * 4. 全屏采用「页面内全屏」：播放器 fixed 覆盖整个视口，页面通过
 *    `<PageMeta pageOrientation='landscape'>` 切到横屏。微信原生全屏会接管
 *    控制栏，倍速 / 自动连播等自定义按钮无法显示；页面内全屏才能保证
 *    播放、倍速、自动等全部控件在横屏下仍然可用；
 * 5. 所有播放地址由后端 play-auth 签发，前端不接触 VOD 密钥。
 */
export default function VodPlayer({
  videoId,
  src,
  title,
  navTitle,
  initialTime = 0,
  poster,
  autoplay = false,
  fullscreen = false,
  rates = PLAYBACK_RATES,
  nextLesson = null,
  autoNext = false,
  onAutoNextChange,
  onSelectLesson,
  onFullscreenChange,
  onTimeUpdate,
  onPlaybackRateChange,
  onEnded,
  onError
}: VodPlayerProps) {
  /**
   * 只有自动播放（切换课时 / 连播）才在挂载时展示 loading。
   * 普通进入是暂停态：iOS 微信在 autoplay=false 时可能延迟到用户点击
   * 播放才触发 loadedmetadata/timeupdate，先显示 loading 会一直转圈。
   */
  const [loading, setLoading] = useState(autoplay)
  const [rate, setRate] = useState<PlaybackRate>(1)
  const [playing, setPlaying] = useState(false)
  const [ended, setEnded] = useState(false)
  const [currentTime, setCurrentTime] = useState(
    Math.max(0, Math.floor(initialTime))
  )
  const [duration, setDuration] = useState(0)
  /** 拖动进度条时的临时位置；非 null 时优先展示，避免被 timeupdate 抢回。 */
  const [dragTime, setDragTime] = useState<number | null>(null)
  const [controlsVisible, setControlsVisible] = useState(true)
  const [speedOpen, setSpeedOpen] = useState(false)
  const [countdown, setCountdown] = useState<number | null>(null)

  const contextRef = useRef<VideoContext | null>(null)
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  /** 锁定挂载时的 autoplay，避免父组件中途复位影响元数据加载后的主动播放。 */
  const autoplayRef = useRef(autoplay)
  /**
   * 是否处于「用户 / 连播已经请求播放」的阶段。
   * 暂停态下的原生 waiting（预加载、initial-time 定位）不是真正的播放缓冲，
   * 不能因此显示转圈浮层。
   */
  const playRequestedRef = useRef(autoplay)
  /** 实时播放位置 / 状态：全屏切换时用于恢复，不依赖 React 状态更新时序。 */
  const currentTimeRef = useRef(currentTime)
  const playingRef = useRef(playing)
  /** 全屏切换窗口内抑制 loading 浮层，避免横竖屏旋转时闪黑。 */
  const fullscreenSwitchingRef = useRef(false)
  /**
   * 全屏旋转后的续播意图：切屏前在播放则为真。窗口内收到的 pause 一律视为
   * 旋转引起并自动恢复，只有用户主动暂停 / 播放结束 / 出错才会清除。
   */
  const autoResumeRef = useRef(false)
  /** 续播意图的强制失效定时器，避免用户之后的正常暂停被误判为旋转。 */
  const autoResumeDeadlineTimerRef = useRef<ReturnType<
    typeof setTimeout
  > | null>(null)
  /** 切换窗口内用户是否手动拖动过进度；有则不做位置回补。 */
  const manualSeekRef = useRef(false)
  /** 全屏切换后的进度锚点；旋转重置进度时以它为准。 */
  const positionGuardRef = useRef<{ time: number; until: number } | null>(null)
  /** 是否正在执行「旋转重置进度 → seek 回原位置」的补偿。 */
  const restoreLoadingRef = useRef(false)
  /** 补偿 seek 的目标位置，用于确认进度已恢复后撤掉加载层。 */
  const restoreTargetRef = useRef<number | null>(null)
  /** 上次重发补偿 seek 的时间，用于节流重试。 */
  const restoreSeekIssuedAtRef = useRef(0)
  /** 补偿 seek 完成后的短暂静默期：忽略 seek 过程中间位置，避免重复触发。 */
  const restoreSettleUntilRef = useRef(0)
  const restoreLoadingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  )
  /**
   * 原生播放器最近一次上报的位置（含被守卫忽略的跳变值）。
   * `currentTimeRef` 只在进度被确认后更新，旋转重绑后它可能仍停在旧值，
   * 无法判断原生播放器当前实际停在哪里；二次校验必须用这个值。
   */
  const lastNativeTimeRef = useRef(Math.max(0, Math.floor(initialTime)))
  const fullscreenResumeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  )
  const fullscreenSettleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  )
  const fullscreenPositionTimerRef = useRef<ReturnType<
    typeof setTimeout
  > | null>(null)
  const fullscreenPauseResumeTimerRef = useRef<ReturnType<
    typeof setTimeout
  > | null>(null)
  /** 用户选择的倍速；原生播放器会在 seek / 重绑后丢失，需要按它恢复。 */
  const desiredRateRef = useRef<PlaybackRate>(1)
  /** 倍速切换期间的技术性暂停，不应被当成用户主动暂停。 */
  const rateChangingRef = useRef(false)
  const rateChangeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const rateResumeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const rateReapplyTimersRef = useRef<Array<ReturnType<typeof setTimeout>>>(
    []
  )
  /** 拖动定位期间的技术性暂停，不应被当成用户主动暂停。 */
  const seekChangingRef = useRef(false)
  /** 用户拖动时若正在播放，定位完成后需要自动续播。 */
  const seekResumeRef = useRef(false)
  const seekResumeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  )
  const seekFallbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  )

  useEffect(() => {
    currentTimeRef.current = currentTime
  }, [currentTime])

  useEffect(() => {
    playingRef.current = playing
  }, [playing])

  const clearFullscreenTimers = useCallback(() => {
    if (fullscreenResumeTimerRef.current) {
      clearTimeout(fullscreenResumeTimerRef.current)
      fullscreenResumeTimerRef.current = null
    }
    if (fullscreenSettleTimerRef.current) {
      clearTimeout(fullscreenSettleTimerRef.current)
      fullscreenSettleTimerRef.current = null
    }
    if (autoResumeDeadlineTimerRef.current) {
      clearTimeout(autoResumeDeadlineTimerRef.current)
      autoResumeDeadlineTimerRef.current = null
    }
    if (fullscreenPositionTimerRef.current) {
      clearTimeout(fullscreenPositionTimerRef.current)
      fullscreenPositionTimerRef.current = null
    }
    if (fullscreenPauseResumeTimerRef.current) {
      clearTimeout(fullscreenPauseResumeTimerRef.current)
      fullscreenPauseResumeTimerRef.current = null
    }
    fullscreenSwitchingRef.current = false
    autoResumeRef.current = false
    positionGuardRef.current = null
  }, [])

  useEffect(() => clearFullscreenTimers, [clearFullscreenTimers])

  const clearRestoreLoading = useCallback(() => {
    if (restoreLoadingTimerRef.current) {
      clearTimeout(restoreLoadingTimerRef.current)
      restoreLoadingTimerRef.current = null
    }
    restoreLoadingRef.current = false
    restoreTargetRef.current = null
  }, [])

  /**
   * 开始补偿 seek 时展示加载层，遮住旋转重置后原生播放器显示的旧画面。
   * 正常情况下 onSeekComplete / 进度回到目标点会提前撤掉；兜底超时防卡死。
   */
  const beginRestoreLoading = useCallback((target: number) => {
    restoreLoadingRef.current = true
    restoreTargetRef.current = target
    restoreSeekIssuedAtRef.current = 0
    setLoading(true)
    if (restoreLoadingTimerRef.current) {
      clearTimeout(restoreLoadingTimerRef.current)
    }
    restoreLoadingTimerRef.current = setTimeout(() => {
      restoreLoadingTimerRef.current = null
      restoreLoadingRef.current = false
      restoreTargetRef.current = null
      setLoading(false)
    }, FULLSCREEN_RESTORE_LOADING_MAX_MS)
  }, [])

  /** 懒创建 VideoContext；第二个参数传当前页面实例，真机才能取到组件内 video。 */
  const getVideoContext = useCallback((): VideoContext | null => {
    if (contextRef.current) {
      return contextRef.current
    }
    try {
      const page = Taro.getCurrentInstance().page
      contextRef.current = Taro.createVideoContext(videoId, page ?? undefined)
    } catch {
      // 页面尚未挂载时拿不到实例，下一次操作会重试。
      contextRef.current = null
    }
    return contextRef.current
  }, [videoId])

  /** 发出补偿 seek；记录时间用于节流重试。 */
  const issueRestoreSeek = useCallback(
    (target: number) => {
      restoreSeekIssuedAtRef.current = Date.now()
      try {
        getVideoContext()?.seek(target)
      } catch {
        // 上下文失效：清掉缓存，下一次重试重新绑定原生 video。
        contextRef.current = null
      }
    },
    [getVideoContext]
  )

  const clearRateReapplyTimers = useCallback(() => {
    for (const timer of rateReapplyTimersRef.current) {
      clearTimeout(timer)
    }
    rateReapplyTimersRef.current = []
  }, [])

  /** 按用户选择恢复倍速；1.0 倍是原生默认值，不用重复设置。 */
  const applyDesiredRate = useCallback(() => {
    if (desiredRateRef.current === 1) {
      return
    }
    try {
      getVideoContext()?.playbackRate(desiredRateRef.current)
    } catch {
      // 上下文暂不可用时保留选择，下一次起播 / 拖动后再设。
    }
  }, [getVideoContext])

  const scheduleRateReapply = useCallback(() => {
    clearRateReapplyTimers()
    if (desiredRateRef.current === 1) {
      return
    }
    for (const delay of RATE_REAPPLY_DELAYS_MS) {
      rateReapplyTimersRef.current.push(
        setTimeout(applyDesiredRate, delay)
      )
    }
  }, [applyDesiredRate, clearRateReapplyTimers])

  const clearRateChangeTimers = useCallback(() => {
    if (rateChangeTimerRef.current) {
      clearTimeout(rateChangeTimerRef.current)
      rateChangeTimerRef.current = null
    }
    if (rateResumeTimerRef.current) {
      clearTimeout(rateResumeTimerRef.current)
      rateResumeTimerRef.current = null
    }
    rateChangingRef.current = false
  }, [])

  const clearSeekTimers = useCallback(() => {
    if (seekResumeTimerRef.current) {
      clearTimeout(seekResumeTimerRef.current)
      seekResumeTimerRef.current = null
    }
    if (seekFallbackTimerRef.current) {
      clearTimeout(seekFallbackTimerRef.current)
      seekFallbackTimerRef.current = null
    }
  }, [])

  /** 原生定位完成后再恢复倍速：此时播放器仍处于暂停态，不会出现画面定格。 */
  const resumePlaybackAfterSeek = useCallback(() => {
    applyDesiredRate()
    if (playRequestedRef.current) {
      try {
        getVideoContext()?.play()
      } catch {
        // 上下文不可用时由用户再次点击播放恢复。
      }
    }
  }, [applyDesiredRate, getVideoContext])

  useEffect(
    () => () => {
      clearRateChangeTimers()
      clearRateReapplyTimers()
      clearSeekTimers()
      clearRestoreLoading()
    },
    [
      clearRateChangeTimers,
      clearRateReapplyTimers,
      clearRestoreLoading,
      clearSeekTimers
    ]
  )

  /**
   * 横竖屏切换期间恢复播放；仅当续播意图仍有效时才执行。
   * 真机首次横屏会在切换后较晚补发 pause，因此该方法可被多次调用。
   */
  const resumePlaybackAfterFullscreen = () => {
    if (!autoResumeRef.current) {
      return
    }
    playRequestedRef.current = true
    try {
      getVideoContext()?.play()
      // 全屏旋转后原生 video 重绑，倍速会被重置为 1.0。
      scheduleRateReapply()
    } catch {
      // 上下文不可用时丢弃缓存，下一次重试重新绑定原生 video 节点。
      contextRef.current = null
    }
    // 首次横屏时 play() 可能先返回、随后才被原生 pause 打断，或旋转尚未结束
    // 导致调用空转；这里定时确认，真正开始播放前持续重试。
    if (fullscreenPauseResumeTimerRef.current) {
      clearTimeout(fullscreenPauseResumeTimerRef.current)
    }
    fullscreenPauseResumeTimerRef.current = setTimeout(() => {
      fullscreenPauseResumeTimerRef.current = null
      if (autoResumeRef.current && !playingRef.current) {
        resumePlaybackAfterFullscreen()
      }
    }, FULLSCREEN_RESUME_VERIFY_DELAY_MS)
  }

  /**
   * 旋转重置常见的一种落点是把进度打回组件 `initial-time`（进入播放页时的
   * 续播点，也可能比当前进度更晚）。用它辅助判断跳变是否由旋转引起；进度
   * 后退则由守卫直接判定，两者都只在切换窗口内生效。
   */
  const looksLikeInitialTimeReset = (seconds: number) =>
    Math.abs(seconds - Math.max(0, Math.floor(initialTime))) <= 2

  /** 把进度拉回切屏前的位置；用户手动拖动过进度时不干预。 */
  const restoreFullscreenPosition = (target: number) => {
    if (manualSeekRef.current) {
      return
    }
    // 必须用原生上报的位置判断：currentTimeRef 是被守卫筛选过的「已确认」
    // 进度，旋转重置上报被忽略时它仍停在切屏前，会误判为无需补偿。
    const native = lastNativeTimeRef.current
    if (
      Math.abs(native - target) <=
      FULLSCREEN_POSITION_TOLERANCE_SECONDS
    ) {
      return
    }
    // 进度落在切屏点之前，或跳到了 initial-time（可能比切屏点更晚），
    // 都视为旋转重置；正常播放只会让进度前移，不干预。
    if (
      native > target + FULLSCREEN_POSITION_TOLERANCE_SECONDS &&
      !looksLikeInitialTimeReset(native)
    ) {
      return
    }
    // 旋转重置后的旧画面会停留在错误位置；seek 补偿期间用加载层盖住。
    beginRestoreLoading(target)
    issueRestoreSeek(target)
  }

  /** 取消续播意图：用户主动暂停、播放结束或出错时调用。 */
  const cancelAutoResume = useCallback(() => {
    autoResumeRef.current = false
    positionGuardRef.current = null
    if (autoResumeDeadlineTimerRef.current) {
      clearTimeout(autoResumeDeadlineTimerRef.current)
      autoResumeDeadlineTimerRef.current = null
    }
    if (fullscreenPauseResumeTimerRef.current) {
      clearTimeout(fullscreenPauseResumeTimerRef.current)
      fullscreenPauseResumeTimerRef.current = null
    }
  }, [])

  const clearHideTimer = useCallback(() => {
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current)
      hideTimerRef.current = null
    }
  }, [])

  /** 播放中且没有弹层时，3.5 秒后自动隐藏控制栏（全屏下同样隐藏）。 */
  const armHideTimer = useCallback(() => {
    clearHideTimer()
    if (!playing || speedOpen || countdown !== null) {
      return
    }
    hideTimerRef.current = setTimeout(() => {
      hideTimerRef.current = null
      setControlsVisible(false)
    }, AUTO_HIDE_DELAY_MS)
  }, [clearHideTimer, countdown, playing, speedOpen])

  const showControls = useCallback(() => {
    setControlsVisible(true)
    armHideTimer()
  }, [armHideTimer])

  useEffect(() => {
    if (!playing || speedOpen || countdown !== null) {
      setControlsVisible(true)
    }
    armHideTimer()
    return clearHideTimer
  }, [armHideTimer, clearHideTimer, countdown, playing, speedOpen])

  useEffect(
    () => () => {
      clearHideTimer()
    },
    [clearHideTimer]
  )

  /** 自动连播：每秒递减，到 0 后切换下一课。 */
  useEffect(() => {
    if (countdown === null) {
      return
    }
    if (countdown <= 0) {
      setCountdown(null)
      if (nextLesson) {
        onSelectLesson?.(nextLesson)
      }
      return
    }
    const timer = setTimeout(() => {
      setCountdown((previous) =>
        previous === null ? null : Math.max(previous - 1, 0)
      )
    }, 1000)
    return () => {
      clearTimeout(timer)
    }
  }, [countdown, nextLesson, onSelectLesson])

  /** 关闭自动连播时立即取消倒计时。 */
  useEffect(() => {
    if (!autoNext) {
      setCountdown(null)
    }
  }, [autoNext])

  const handleLoadedMetaData = (event: VodVideoEvent) => {
    const detail = event.detail || {}
    const totalDuration = readNumber(detail.duration)
    if (totalDuration > 0) {
      setDuration(totalDuration)
    }
    // 旋转重绑后也会触发 loadedmetadata；补偿 seek 未完成时不能提前撤掉
    // 加载层，否则会露出 initial-time 处的旧画面。
    if (!restoreLoadingRef.current) {
      setLoading(false)
    }
    // 元数据就绪后才能可靠设置倍速；部分机型在之前调用会被静默忽略。
    scheduleRateReapply()
    // 原生 autoplay 对异步挂载的 video 不一定生效（切换课时后尤其明显），
    // 这里用挂载时锁定的开关主动播放一次，保证切换后立即续播。
    if (autoplayRef.current) {
      autoplayRef.current = false
      playRequestedRef.current = true
      try {
        getVideoContext()?.play()
      } catch {
        // 上下文尚未就绪时保留原生 autoplay 行为。
      }
    }
  }

  const handleTimeUpdate = (event: VodVideoEvent) => {
    const detail = event.detail || {}
    const time = readNumber(detail.currentTime)
    const totalDuration = readNumber(detail.duration)
    // 记录原生真实位置（包括下面会被忽略的跳变值），供延迟位置校验使用。
    lastNativeTimeRef.current = time
    // 补偿 seek 进行中：旧位置可能还会上报几次，忽略这些值；
    // 若进度迟迟回不到目标点（seek 被刚重绑的播放器吞掉），按间隔重发 seek。
    if (restoreLoadingRef.current) {
      const target = restoreTargetRef.current
      if (target === null) {
        clearRestoreLoading()
        setLoading(false)
      } else if (
        Math.abs(time - target) <= FULLSCREEN_POSITION_TOLERANCE_SECONDS
      ) {
        clearRestoreLoading()
        setLoading(false)
      } else {
        if (
          Date.now() - restoreSeekIssuedAtRef.current >
          FULLSCREEN_RESTORE_SEEK_RETRY_MS
        ) {
          issueRestoreSeek(target)
        }
        return
      }
    }
    // 全屏切换窗口内若进度突然跳变（原生 video 重新初始化时会把进度重置为
    // initial-time 或 0，initial-time 也可能比切屏点更晚），拉回切屏前的真实
    // 进度，并且不把跳变后的时间回传给页面，避免污染进度上报。
    const guard = positionGuardRef.current
    if (guard) {
      if (Date.now() > guard.until) {
        positionGuardRef.current = null
      } else if (!manualSeekRef.current) {
        // 补偿 seek 刚完成时，原生可能还会上报几个 seek 过程中的中间位置；
        // 这段时间不做跳变判断，也不更新锚点，等位置稳定后再继续。
        if (Date.now() < restoreSettleUntilRef.current) {
          return
        }
        const drift = time - guard.time
        // 进度后退，或跳到 initial-time（可能在前也可能在后），都视为旋转
        // 重置；正常播放只会让进度前移，用户拖动会清空守卫。
        const jumpedBackward =
          drift < -FULLSCREEN_POSITION_TOLERANCE_SECONDS
        const jumpedToResumePoint =
          Math.abs(drift) > FULLSCREEN_POSITION_TOLERANCE_SECONDS &&
          looksLikeInitialTimeReset(time)
        if (jumpedBackward || jumpedToResumePoint) {
          beginRestoreLoading(guard.time)
          issueRestoreSeek(guard.time)
          return
        }
        guard.time = time
      }
    }
    if (totalDuration > 0) {
      setDuration(totalDuration)
      // 拖动定位期间 timeupdate 可能停在目标点，等定位完成再撤掉加载层。
      if (!seekChangingRef.current && !seekResumeRef.current) {
        setLoading(false)
      }
    }
    if (ended && totalDuration > 0 && time < totalDuration - 0.5) {
      setEnded(false)
    }
    setCurrentTime(time)
    onTimeUpdate?.(time, totalDuration)
  }

  /**
   * 原生 seek 完成（手势拖动 / initial-time 定位）后 iOS 会重置倍速。
   * 用户拖动时先保持暂停，等这里定位完成再恢复倍速和播放，避免在
   * 「正在缓冲 + playbackRate 重设」的窗口里出现声音继续、画面定格。
   */
  const handleSeekComplete = () => {
    if (seekFallbackTimerRef.current) {
      clearTimeout(seekFallbackTimerRef.current)
      seekFallbackTimerRef.current = null
    }

    // 旋转重置后的补偿 seek 完成：此时画面已回到目标进度，可以撤掉加载层。
    // 之后短暂忽略跳变判断，避免 seek 过程中间位置触发重复补偿。
    if (restoreLoadingRef.current) {
      clearRestoreLoading()
      setLoading(false)
      restoreSettleUntilRef.current = Date.now() + 600
    }

    if (seekChangingRef.current) {
      // 定位完成时播放器仍是暂停态，此时设置倍速是安全的。
      applyDesiredRate()
      if (seekResumeTimerRef.current) {
        clearTimeout(seekResumeTimerRef.current)
      }
      seekResumeTimerRef.current = setTimeout(() => {
        seekResumeTimerRef.current = null
        resumePlaybackAfterSeek()
      }, SEEK_RESUME_DELAY_MS)
      return
    }

    if (seekResumeRef.current) {
      // 用户本来处于暂停态：只定位，不自动播放。
      seekResumeRef.current = false
      applyDesiredRate()
      setLoading(false)
      return
    }

    scheduleRateReapply()
  }

  /** 缓冲 / 卡顿时展示 loading，播放恢复后由 onPlay 或 timeupdate 关闭。 */
  const handleWaiting = () => {
    // 横竖屏切换会让原生 video 重新布局，此时 onWaiting 不代表真正缓冲；
    // 900ms 内继续显示正常画面，避免出现黑屏 / 转圈。
    if (fullscreenSwitchingRef.current) {
      return
    }
    // 倍速切换时的技术性暂停 / 起播不展示加载浮层，避免闪一下转圈。
    if (rateChangingRef.current) {
      return
    }
    // 暂停态下的预加载 / initial-time 定位也可能触发 waiting；
    // 没有播放请求时不能显示 loading，否则会一直转圈直到用户点击播放。
    if (!playRequestedRef.current) {
      return
    }
    setLoading(true)
  }

  const handlePlay = () => {
    // 原生中央播放键也会走到这里，补记播放请求，保证后续缓冲能显示 loading。
    playRequestedRef.current = true
    seekChangingRef.current = false
    seekResumeRef.current = false
    clearSeekTimers()
    // 补偿 seek 尚未完成时不撤加载层，否则旧画面会露出来。
    if (!restoreLoadingRef.current) {
      setLoading(false)
    }
    setPlaying(true)
    setEnded(false)
    // pause→play 起播后原生播放器可能回到 1.0 倍，按用户选择恢复。
    scheduleRateReapply()
  }

  const handlePause = () => {
    // 倍速切换时的技术性暂停：保持播放意图，稍后由倍速流程主动恢复。
    if (rateChangingRef.current) {
      return
    }
    // 拖动定位时的技术性暂停：等定位完成后统一恢复，不当作主动暂停。
    if (seekChangingRef.current) {
      return
    }
    // 横竖屏旋转会让原生 video 暂停，且首次横屏的 pause 可能延迟数秒才补发；
    // 续播意图有效期间一律视为旋转引起，稍等布局稳定后再次恢复播放。
    if (autoResumeRef.current) {
      setPlaying(false)
      if (fullscreenPauseResumeTimerRef.current) {
        clearTimeout(fullscreenPauseResumeTimerRef.current)
      }
      fullscreenPauseResumeTimerRef.current = setTimeout(() => {
        fullscreenPauseResumeTimerRef.current = null
        resumePlaybackAfterFullscreen()
      }, FULLSCREEN_PAUSE_RESUME_DELAY_MS)
      return
    }
    playRequestedRef.current = false
    clearRestoreLoading()
    setLoading(false)
    setPlaying(false)
    showControls()
  }

  const handleEnded = () => {
    clearRateChangeTimers()
    clearSeekTimers()
    clearRestoreLoading()
    seekChangingRef.current = false
    seekResumeRef.current = false
    playRequestedRef.current = false
    cancelAutoResume()
    setLoading(false)
    setPlaying(false)
    setEnded(true)
    setControlsVisible(true)
    setSpeedOpen(false)
    onEnded?.()
    if (autoNext && nextLesson) {
      setCountdown(AUTO_NEXT_SECONDS)
    } else {
      setCountdown(null)
    }
  }

  const handleError = (event: VodVideoEvent) => {
    const detail = event.detail || {}
    clearRateChangeTimers()
    clearSeekTimers()
    clearRestoreLoading()
    seekChangingRef.current = false
    seekResumeRef.current = false
    playRequestedRef.current = false
    cancelAutoResume()
    setLoading(false)
    setPlaying(false)
    onError?.(detail.errMsg || detail.message || '视频加载失败，请稍后重试')
  }

  /** 播放 / 暂停；播放结束后再次点击从头播放。 */
  const handleTogglePlay = () => {
    clearHideTimer()
    setControlsVisible(true)
    const context = getVideoContext()
    if (!context) {
      return
    }
    if (playing) {
      // 用户主动暂停：取消全屏切换期间的自动恢复，避免暂停后又被拉起。
      cancelAutoResume()
      clearSeekTimers()
      clearRestoreLoading()
      seekChangingRef.current = false
      seekResumeRef.current = false
      playRequestedRef.current = false
      context.pause()
      return
    }
    playRequestedRef.current = true
    setLoading(true)
    const reachedEnd =
      ended || (duration > 0 && currentTime >= duration - 0.3)
    if (reachedEnd) {
      manualSeekRef.current = true
      context.seek(0)
      setCurrentTime(0)
      setDragTime(null)
      setEnded(false)
    }
    context.play()
    scheduleRateReapply()
  }

  const handleSliderChanging = (event: VodSliderEvent) => {
    const value = readNumber(event.detail?.value)
    setDragTime(value)
    setControlsVisible(true)
    // 拖动期间不要自动隐藏控制栏。
    clearHideTimer()
  }

  const handleSliderChange = (event: VodSliderEvent) => {
    const value = clamp(readNumber(event.detail?.value), 0, duration || 0)
    manualSeekRef.current = true
    // 用户主动定位后，全屏切换不再做位置回补。
    positionGuardRef.current = null
    // 用户新的定位优先于旋转补偿，撤掉补偿加载标记（下方会重新展示加载层）。
    clearRestoreLoading()
    // 同步更新实时位置，避免紧接着点全屏时读到旧值。
    currentTimeRef.current = value
    lastNativeTimeRef.current = value
    setDragTime(null)
    setCurrentTime(value)
    setEnded(false)

    const context = getVideoContext()
    // 定位期间先暂停：避免「重新缓冲 + 播放中重设倍速」叠加导致画面定格。
    // 原本暂停的用户只定位，不自动续播。
    const shouldResume = playingRef.current
    clearRateReapplyTimers()
    clearSeekTimers()
    seekResumeRef.current = shouldResume
    seekChangingRef.current = shouldResume
    setLoading(true)
    if (shouldResume) {
      try {
        context?.pause()
      } catch {
        seekChangingRef.current = false
      }
    }
    try {
      context?.seek(value)
    } catch {
      // 上下文不可用时退回原来的直接定位行为。
      scheduleRateReapply()
    }

    // onSeekComplete 在部分机型 / 部分状态下不会触发，兜底恢复避免卡在加载层。
    seekFallbackTimerRef.current = setTimeout(() => {
      seekFallbackTimerRef.current = null
      if (!seekChangingRef.current && !seekResumeRef.current) {
        return
      }
      const resume = seekChangingRef.current
      seekChangingRef.current = false
      seekResumeRef.current = false
      applyDesiredRate()
      if (resume && playRequestedRef.current) {
        try {
          getVideoContext()?.play()
        } catch {
          // 播放失败时保留加载层，用户可再次点击播放。
        }
      } else {
        setLoading(false)
      }
    }, SEEK_FALLBACK_RESUME_MS)
    armHideTimer()
  }

  /**
   * 切换倍速。
   *
   * 播放中直接调用 playbackRate，部分机型会出现「声音已变速、画面定格」；
   * 这里先暂停，等原生播放器稳定后再设置倍速，然后恢复播放。基础库
   * < 2.13.0 不支持倍速时报错被吞掉，不打断正常播放。
   */
  const handleRateChange = (next: PlaybackRate) => {
    if (next !== rate) {
      desiredRateRef.current = next
      setRate(next)
      onPlaybackRateChange?.(next)

      clearRateReapplyTimers()
      clearRateChangeTimers()
      // 定位流程尚未结束时只记录目标倍速，由 handleSeekComplete 统一应用，
      // 避免暂停 / 恢复播放与 seek 相互打断。
      if (seekChangingRef.current || seekResumeRef.current) {
        setSpeedOpen(false)
        showControls()
        return
      }
      const context = getVideoContext()
      const resumeAfterChange = playingRef.current
      if (context) {
        rateChangingRef.current = resumeAfterChange
        if (resumeAfterChange) {
          try {
            // 技术性暂停：handlePause 会忽略，不改播放意图。
            context.pause()
          } catch {
            rateChangingRef.current = false
          }
        }
        rateChangeTimerRef.current = setTimeout(() => {
          rateChangeTimerRef.current = null
          try {
            getVideoContext()?.playbackRate(next)
          } catch {
            // 基础库不支持或上下文已失效：静默忽略。
          }
          rateResumeTimerRef.current = setTimeout(() => {
            rateResumeTimerRef.current = null
            try {
              // 二次设置，覆盖首次调用早于原生播放器就绪的机型。
              getVideoContext()?.playbackRate(next)
            } catch {
              // 同上。
            }
            // 期间用户主动暂停时 playRequestedRef 已被清零，不再拉起。
            if (resumeAfterChange && playRequestedRef.current) {
              try {
                getVideoContext()?.play()
              } catch {
                // 上下文不可用时由用户再次点击播放恢复。
              }
            }
            rateChangingRef.current = false
          }, RATE_CHANGE_RESUME_DELAY_MS)
        }, RATE_CHANGE_PAUSE_DELAY_MS)
      }
    }
    setSpeedOpen(false)
    showControls()
  }

  /** 倍速按钮：打开 / 再次点击关闭右侧面板。 */
  const handleToggleSpeed = () => {
    setSpeedOpen((previous) => !previous)
    setControlsVisible(true)
    clearHideTimer()
  }

  const handleCloseSpeed = () => {
    setSpeedOpen(false)
    showControls()
  }

  const handleAutoNext = () => {
    const next = !autoNext
    onAutoNextChange?.(next)
    if (!next) {
      setCountdown(null)
    }
    showControls()
  }

  const handlePlayNext = () => {
    if (!nextLesson) {
      setCountdown(null)
      showControls()
      return
    }
    setCountdown(null)
    onSelectLesson?.(nextLesson)
  }

  const handleCancelCountdown = () => {
    setCountdown(null)
    showControls()
  }

  /**
   * 进入 / 退出横屏全屏。
   *
   * 不使用 `videoContext.requestFullScreen`：微信原生全屏会接管控制栏，
   * 倍速、自动连播等自定义按钮无法在上面展示。这里由播放器 fixed 覆盖
   * 整个视口，父页面再通过 `<PageMeta pageOrientation='landscape' />`
   * 切到横屏，因此播放、进度、倍速、自动、退出按钮都保留。
   *
   * 全屏状态由父页面持有：自动连播重挂播放器后仍保持全屏，不会闪回竖屏。
   *
   * 无缝切换：不重挂 video、不改 src，仅切换覆盖层样式和页面方向。
   * 旋转会触发原生 video 重新布局，部分机型此时会短暂暂停并回报
   * onWaiting；切换窗口内抑制 loading 浮层，并在布局稳定后主动续播。
   */
  const handleFullscreen = () => {
    clearHideTimer()
    setControlsVisible(true)
    setSpeedOpen(false)

    // 连续切换时（上一次旋转的 pause / 续播尚未确认完），playingRef 可能
    // 暂时为 false；用续播意图兜底，避免第二次切换后被当成用户暂停。
    const wasPlaying = playingRef.current || autoResumeRef.current
    // 上一次切换的补偿 seek 还没收敛时，以它的目标为锚点，避免读到旧值。
    const resumeAt = restoreTargetRef.current ?? currentTimeRef.current

    // 上一次切换遗留的补偿加载层先撤掉，本次旋转会按实际重置情况重新触发。
    if (restoreLoadingRef.current) {
      clearRestoreLoading()
      setLoading(false)
    }

    clearFullscreenTimers()
    fullscreenSwitchingRef.current = true
    autoResumeRef.current = wasPlaying
    manualSeekRef.current = false
    // 记录切屏前的真实进度；旋转后原生 video 可能被 initial-time 重置。
    positionGuardRef.current = {
      time: resumeAt,
      until: Date.now() + FULLSCREEN_POSITION_GUARD_MS
    }

    onFullscreenChange?.(!fullscreen)

    // 横屏后原生 video 节点可能重建，丢弃旧上下文，下一次操作重新绑定。
    contextRef.current = null

    if (wasPlaying) {
      // 续播意图只保留有限时间，超时后恢复为普通暂停逻辑，避免用户之后
      // 正常暂停节目时被误判为旋转引起的暂停。
      autoResumeDeadlineTimerRef.current = setTimeout(() => {
        autoResumeDeadlineTimerRef.current = null
        autoResumeRef.current = false
      }, FULLSCREEN_AUTO_RESUME_MAX_MS)

      fullscreenResumeTimerRef.current = setTimeout(() => {
        fullscreenResumeTimerRef.current = null
        resumePlaybackAfterFullscreen()
      }, FULLSCREEN_RESUME_DELAY_MS)
    }

    fullscreenSettleTimerRef.current = setTimeout(() => {
      fullscreenSettleTimerRef.current = null
      fullscreenSwitchingRef.current = false
      // 兜底：旋转把进度重置到任意位置（早于或晚于切屏前）都拉回来。
      restoreFullscreenPosition(resumeAt)
      // 原生 video 重绑后倍速回到 1.0，暂停态也需要恢复用户选择。
      scheduleRateReapply()
      // 部分机型在旋转结束时才补发 pause；这里再做一次恢复。
      if (autoResumeRef.current && !playingRef.current) {
        resumePlaybackAfterFullscreen()
      }
    }, FULLSCREEN_SETTLE_MS)

    // 暂停态旋转不一定派发 timeupdate，延迟再校验一次进度。
    fullscreenPositionTimerRef.current = setTimeout(() => {
      fullscreenPositionTimerRef.current = null
      restoreFullscreenPosition(resumeAt)
    }, FULLSCREEN_POSITION_CHECK_DELAY_MS)

    armHideTimer()
  }

  /** 点击视频区域：收起倍速面板 / 显示或隐藏控制栏。 */
  const handleStageTap = () => {
    if (speedOpen) {
      setSpeedOpen(false)
      return
    }
    if (!controlsVisible) {
      showControls()
      return
    }
    if (playing) {
      clearHideTimer()
      setControlsVisible(false)
      return
    }
    showControls()
  }

  const displayTime = dragTime ?? currentTime
  const sliderMax = duration > 0 ? duration : 1
  const sliderValue = clamp(displayTime, 0, sliderMax)
  // 暂停和播放结束都展示中央按钮；结束时再次点击会从头播放。
  const showCenterPlay =
    !playing && !loading && !speedOpen && countdown === null

  return (
    <View
      className={
        fullscreen ? 'vod-player vod-player--fullscreen' : 'vod-player'
      }
      // 全屏时阻止页面跟随手指滚动，避免背后的课时列表移动。
      catchMove={fullscreen}
    >
      <View className='vod-player__stage' onClick={handleStageTap}>
        <Video
          id={videoId}
          className='vod-player__video'
          src={src}
          title={title}
          // 始终关闭原生 controls：普通模式和全屏都使用同一套自定义控件。
          controls={false}
          showPlayBtn
          showCenterPlayBtn
          showProgress
          showFullscreenBtn
          showBottomProgress={false}
          enableProgressGesture
          autoplay={autoplay}
          initialTime={Math.max(0, Math.floor(initialTime))}
          objectFit='contain'
          poster={poster}
          onPlay={handlePlay}
          onPause={handlePause}
          onTimeUpdate={handleTimeUpdate}
          onLoadedMetaData={handleLoadedMetaData}
          onSeekComplete={handleSeekComplete}
          onWaiting={handleWaiting}
          onEnded={handleEnded}
          onError={handleError}
        />

        {/* 全屏退出入口固定在画面左上角，不占用顶部系统栏 / 标题栏；
            控制栏自动隐藏时也保持可点击。返回图标右侧展示当前课时导航标题，
            右侧预留胶囊区域，标题过长时省略。 */}
        {fullscreen ? (
          <View className='vod-player__fs-top'>
            <View
              id='vod-fs-exit'
              className='vod-player__fs-exit'
              hoverClass='vod-player__fs-exit--pressed'
              onClick={(event) => {
                stopPropagation(event)
                handleFullscreen()
              }}
            >
              <View className='vod-player__fs-back-icon' />
            </View>
            {navTitle ? (
              <View className='vod-player__fs-title'>
                <View className='vod-player__fs-title-dot' />
                <Text className='vod-player__fs-title-text'>{navTitle}</Text>
              </View>
            ) : null}
          </View>
        ) : null}

        {loading ? (
          <View className='vod-player__loading'>
            <LoadingSpin tip='视频正在加载…' compact={fullscreen} />
          </View>
        ) : null}

        {showCenterPlay ? (
          <View
            id='vod-center-play'
            className='vod-player__center-play'
            onClick={(event) => {
              stopPropagation(event)
              handleTogglePlay()
            }}
          >
            <View className='vod-player__play-triangle vod-player__play-triangle--large' />
          </View>
        ) : null}

        <View
          className={
            controlsVisible
              ? 'vod-player__control'
              : 'vod-player__control vod-player__control--hidden'
          }
          onClick={stopPropagation}
        >
            <View className='vod-player__control-left'>
              <View
                id='vod-play-toggle'
                className='vod-player__icon-btn'
                onClick={handleTogglePlay}
              >
                {playing ? (
                  <View className='vod-player__pause-icon'>
                    <View className='vod-player__pause-bar' />
                    <View className='vod-player__pause-bar' />
                  </View>
                ) : (
                  <View className='vod-player__play-triangle' />
                )}
              </View>
              <Text className='vod-player__time'>
                {formatPlayTime(displayTime)}/{formatPlayTime(duration)}
              </Text>
            </View>

            <View className='vod-player__progress' onClick={stopPropagation}>
              <Slider
                id='vod-progress'
                className='vod-player__slider'
                min={0}
                max={sliderMax}
                step={1}
                value={sliderValue}
                disabled={duration <= 0}
                activeColor='#e2c084'
                backgroundColor='rgba(255, 255, 255, 0.3)'
                blockColor='#ffffff'
                blockSize={10}
                onChanging={handleSliderChanging}
                onChange={handleSliderChange}
              />
            </View>

            <View className='vod-player__control-right'>
              <View
                id='vod-speed-btn'
                className='vod-player__text-btn'
                onClick={handleToggleSpeed}
              >
                <Text className='vod-player__text-btn-label'>倍速</Text>
              </View>
              <View
                id='vod-auto-btn'
                className='vod-player__text-btn vod-player__auto'
                onClick={handleAutoNext}
              >
                <Text className='vod-player__auto-label'>自动</Text>
                <View
                  className={
                    autoNext
                      ? 'vod-player__auto-dot vod-player__auto-dot--on'
                      : 'vod-player__auto-dot'
                  }
                />
              </View>
              {/* 全屏态用画面内的左上角返回按钮退出，底部不再重复放退出键。 */}
              {!fullscreen ? (
                <View
                  id='vod-fullscreen-btn'
                  className='vod-player__icon-btn'
                  onClick={handleFullscreen}
                >
                  <View className='vod-player__fs-icon'>
                    <View className='vod-player__fs-corner vod-player__fs-corner--tl' />
                    <View className='vod-player__fs-corner vod-player__fs-corner--tr' />
                    <View className='vod-player__fs-corner vod-player__fs-corner--bl' />
                    <View className='vod-player__fs-corner vod-player__fs-corner--br' />
                  </View>
                </View>
              ) : null}
            </View>
          </View>

        {speedOpen ? (
          <View
            id='vod-speed-mask'
            className='vod-player__speed-layer'
            onClick={handleCloseSpeed}
          >
            <View
              id='vod-speed-panel'
              className='vod-player__speed-panel'
              onClick={stopPropagation}
            >
              {rates.map((item) => (
                <View
                  key={item}
                  id={`vod-rate-${String(item).replace('.', '_')}`}
                  className={
                    item === rate
                      ? 'vod-player__speed-option vod-player__speed-option--active'
                      : 'vod-player__speed-option'
                  }
                  onClick={() => handleRateChange(item)}
                >
                  <Text className='vod-player__speed-option-text'>
                    {formatRate(item)}
                  </Text>
                </View>
              ))}
            </View>
          </View>
        ) : null}

        {countdown !== null && nextLesson ? (
          <View className='vod-player__countdown' onClick={stopPropagation}>
            <Text className='vod-player__countdown-title'>即将播放下一课</Text>
            <Text className='vod-player__countdown-lesson'>
              {nextLesson.title}
            </Text>
            <Text className='vod-player__countdown-tip'>
              {Math.max(countdown, 0)} 秒后自动播放
            </Text>
            <View className='vod-player__countdown-actions'>
              <View
                id='vod-next-play'
                className='vod-player__countdown-btn vod-player__countdown-btn--primary'
                onClick={handlePlayNext}
              >
                <Text className='vod-player__countdown-btn-text'>立即播放</Text>
              </View>
              <View
                id='vod-next-cancel'
                className='vod-player__countdown-btn'
                onClick={handleCancelCountdown}
              >
                <Text className='vod-player__countdown-btn-text'>取消</Text>
              </View>
            </View>
          </View>
        ) : null}
      </View>
    </View>
  )
}
