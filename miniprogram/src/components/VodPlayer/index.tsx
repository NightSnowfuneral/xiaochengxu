import { useCallback, useEffect, useRef, useState } from 'react'
import { Slider, Text, Video, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

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
  const [loading, setLoading] = useState(true)
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
  /** 实时播放位置 / 状态：全屏切换时用于恢复，不依赖 React 状态更新时序。 */
  const currentTimeRef = useRef(currentTime)
  const playingRef = useRef(playing)
  /** 全屏切换窗口内抑制 loading 浮层，避免横竖屏旋转时闪黑。 */
  const fullscreenSwitchingRef = useRef(false)
  /** 切换窗口内用户是否手动拖动过进度；有则不做位置回补。 */
  const manualSeekRef = useRef(false)
  const fullscreenResumeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  )
  const fullscreenSettleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
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
    fullscreenSwitchingRef.current = false
  }, [])

  useEffect(() => clearFullscreenTimers, [clearFullscreenTimers])

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
    setLoading(false)
    // 原生 autoplay 对异步挂载的 video 不一定生效（切换课时后尤其明显），
    // 这里用挂载时锁定的开关主动播放一次，保证切换后立即续播。
    if (autoplayRef.current) {
      autoplayRef.current = false
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
    if (totalDuration > 0) {
      setDuration(totalDuration)
      setLoading(false)
    }
    if (ended && totalDuration > 0 && time < totalDuration - 0.5) {
      setEnded(false)
    }
    setCurrentTime(time)
    onTimeUpdate?.(time, totalDuration)
  }

  /** 缓冲 / 卡顿时展示 loading，播放恢复后由 onPlay 或 timeupdate 关闭。 */
  const handleWaiting = () => {
    // 横竖屏切换会让原生 video 重新布局，此时 onWaiting 不代表真正缓冲；
    // 900ms 内继续显示正常画面，避免出现黑屏 / 转圈。
    if (fullscreenSwitchingRef.current) {
      return
    }
    setLoading(true)
  }

  const handlePlay = () => {
    setLoading(false)
    setPlaying(true)
    setEnded(false)
  }

  const handlePause = () => {
    setPlaying(false)
    showControls()
  }

  const handleEnded = () => {
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
      context.pause()
      return
    }
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
    setDragTime(null)
    setCurrentTime(value)
    setEnded(false)
    getVideoContext()?.seek(value)
    armHideTimer()
  }

  /** 切换倍速；低版本基础库不支持时静默忽略，不打断播放。 */
  const handleRateChange = (next: PlaybackRate) => {
    if (next !== rate) {
      setRate(next)
      try {
        getVideoContext()?.playbackRate(next)
      } catch {
        // 基础库 < 2.13.0 或 video 尚未挂载时忽略。
      }
      onPlaybackRateChange?.(next)
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

    const wasPlaying = playingRef.current
    const resumeAt = currentTimeRef.current

    clearFullscreenTimers()
    fullscreenSwitchingRef.current = true
    manualSeekRef.current = false

    onFullscreenChange?.(!fullscreen)

    fullscreenResumeTimerRef.current = setTimeout(() => {
      fullscreenResumeTimerRef.current = null
      if (!wasPlaying) {
        return
      }
      try {
        getVideoContext()?.play()
      } catch {
        // 上下文不可用时保留 video 原生状态，不做额外处理。
      }
    }, FULLSCREEN_RESUME_DELAY_MS)

    fullscreenSettleTimerRef.current = setTimeout(() => {
      fullscreenSettleTimerRef.current = null
      fullscreenSwitchingRef.current = false
      // 兜底：若个别机型在旋转后把进度重置到开头，回到切换前的位置。
      // 用户在窗口内主动拖动过进度时以用户操作为准。
      if (
        !manualSeekRef.current &&
        resumeAt > 1 &&
        currentTimeRef.current < resumeAt - 2
      ) {
        try {
          getVideoContext()?.seek(resumeAt)
        } catch {
          // seek 失败则继续使用当前进度。
        }
      }
    }, FULLSCREEN_SETTLE_MS)

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
            <View className='vod-player__spinner' />
            <Text className='vod-player__loading-text'>视频加载中…</Text>
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
