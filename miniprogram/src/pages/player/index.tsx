import { useCallback, useEffect, useRef, useState } from 'react'
import { PageMeta, Text, View } from '@tarojs/components'
import Taro, {
  useDidHide,
  useRouter
} from '@tarojs/taro'

import ExpiredAccessModal from '../../components/ExpiredAccessModal'
import LoginModal from '../../components/LoginModal'
import MockModeBadge from '../../components/MockModeBadge'
import VodPlayer from '../../components/VodPlayer'
import { PROGRESS_REPORT_INTERVAL_MS } from '../../constants'
import { useAuthGuard } from '../../hooks/useAuthGuard'
import { useSystemConfig } from '../../hooks/useSystemConfig'
import {
  finishLesson,
  getCourseDetail,
  getPlaybackAuth,
  reportProgress as reportProgressApi
} from '../../services/courseApi'
import { ApiError, getErrorMessage } from '../../services/request'
import { useAppSelector } from '../../store/hooks'
import type {
  FinishLessonStatus,
  PlaybackAuthResponse,
  VodLesson
} from '../../types/vod'
import {
  formatPlayTime,
  parsePositiveInt,
  safeDecode
} from '../../utils/format'
import { openLoginModal } from '../../utils/loginModal'

import './index.scss'

type PlayerStatus = 'idle' | 'loading' | 'ready' | 'error'

/** 课时列表时长；后端尚未取得 VOD 时长时展示 --:--。 */
function formatLessonDuration(seconds: number | undefined): string {
  const value = Number(seconds)
  if (!Number.isFinite(value) || value <= 0) {
    return '--:--'
  }
  return formatPlayTime(Math.round(value))
}

export default function PlayerPage() {
  const router = useRouter()
  const { checking, allowed } = useAuthGuard()
  useSystemConfig()

  const routeLessonId = parsePositiveInt(router.params.lessonId)
  const routeCourseId = parsePositiveInt(router.params.courseId)
  const routeTitle = safeDecode(router.params.title) || '课程播放'
  const isMockLogin = useAppSelector((state) => state.user.isMockLogin)

  const [status, setStatus] = useState<PlayerStatus>('idle')
  const [playAuth, setPlayAuth] = useState<PlaybackAuthResponse | null>(null)
  const [accessDenied, setAccessDenied] = useState(false)
  const [expiredVisible, setExpiredVisible] = useState(false)
  const [error, setError] = useState('')
  const [duration, setDuration] = useState(0)
  /** 当前课时；从课时列表切换后覆盖路由参数，不重新压栈。 */
  const [selectedLesson, setSelectedLesson] = useState<VodLesson | null>(null)
  const [courseLessons, setCourseLessons] = useState<VodLesson[]>([])
  const [lessonsLoading, setLessonsLoading] = useState(false)
  const [lessonsError, setLessonsError] = useState('')
  /** 自动连播开关放在页面层，切换课时后仍保持原状态。 */
  const [autoNext, setAutoNext] = useState(true)
  /** 切换课时后自动开始播放；只在本次切换挂载时生效。 */
  const [autoplayNext, setAutoplayNext] = useState(false)
  /** 播放器页面内全屏状态；驱动 PageMeta 切换横屏。 */
  const [playerFullscreen, setPlayerFullscreen] = useState(false)
  /** 自定义导航栏高度：状态栏 + 44px 内容区，与右上角胶囊垂直对齐。 */
  const [navInsetTop] = useState(() => {
    try {
      return Taro.getSystemInfoSync().statusBarHeight || 0
    } catch {
      return 0
    }
  })

  const lessonId = selectedLesson?.id ?? routeLessonId
  const lessonTitle =
    selectedLesson?.title ||
    courseLessons.find((item) => item.id === lessonId)?.title ||
    routeTitle
  const resolvedCourseId = routeCourseId ?? playAuth?.course_id ?? null
  const lessonIndex = courseLessons.findIndex((item) => item.id === lessonId)
  const nextLesson =
    lessonIndex >= 0 ? courseLessons[lessonIndex + 1] ?? null : null

  const mountedRef = useRef(true)
  const lastTimeRef = useRef(0)
  const lastReportedRef = useRef(-1)
  /** 用 ref 防止 ended 重复触发时并发调用 finish-lesson。 */
  const finishStatusRef = useRef<FinishLessonStatus>('idle')
  /** 当前实际课时，用于丢弃切换课时后迟到的鉴权 / 完成响应。 */
  const activeLessonIdRef = useRef<number | null>(lessonId)
  const authSeqRef = useRef(0)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    activeLessonIdRef.current = lessonId
  }, [lessonId])

  const loadAuth = useCallback(async () => {
    const seq = authSeqRef.current + 1
    authSeqRef.current = seq
    if (!lessonId) {
      setStatus('error')
      setError('课时参数有误')
      return
    }
    setStatus('loading')
    // 先卸载旧 video，避免切换课时后旧视频继续播放。
    setPlayAuth(null)
    setDuration(0)
    setAccessDenied(false)
    setExpiredVisible(false)
    setError('')
    finishStatusRef.current = 'idle'
    try {
      const auth = await getPlaybackAuth(lessonId)
      // 快速连续切换课时时，只接受最后一次请求的结果。
      if (!mountedRef.current || seq !== authSeqRef.current) {
        return
      }
      setPlayAuth(auth)
      lastTimeRef.current = auth.last_position
      lastReportedRef.current = auth.last_position
      setStatus('ready')
    } catch (loadError) {
      if (!mountedRef.current || seq !== authSeqRef.current) {
        return
      }
      if (
        loadError instanceof ApiError &&
        loadError.code === 'COURSE_ACCESS_EXPIRED'
      ) {
        setExpiredVisible(true)
        setError('该课程观看权限已过期，可重新购买继续学习')
      } else if (
        loadError instanceof ApiError &&
        loadError.code === 'COURSE_ACCESS_NOT_STARTED'
      ) {
        setError(getErrorMessage(loadError))
      } else if (
        loadError instanceof ApiError &&
        (loadError.code === 'COURSE_NOT_OWNED' || loadError.status === 403)
      ) {
        setAccessDenied(true)
        setError('购买课程后才能播放全部课时')
      } else {
        setError(getErrorMessage(loadError))
      }
      setStatus('error')
    }
  }, [lessonId])

  useEffect(() => {
    if (allowed && lessonId) {
      void loadAuth()
    }
  }, [allowed, lessonId, loadAuth])

  /** 拉取课程章节；失败不影响视频播放，只在常驻课时列表处提示。 */
  useEffect(() => {
    if (!allowed || !resolvedCourseId) {
      return
    }
    let cancelled = false
    setLessonsLoading(true)
    setLessonsError('')
    getCourseDetail(resolvedCourseId)
      .then((detail) => {
        if (cancelled) {
          return
        }
        setCourseLessons(detail.lessons)
      })
      .catch((lessonFailure) => {
        if (cancelled) {
          return
        }
        setCourseLessons([])
        setLessonsError(`章节加载失败：${getErrorMessage(lessonFailure)}`)
      })
      .finally(() => {
        if (!cancelled) {
          setLessonsLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [allowed, resolvedCourseId])

  const flushProgress = useCallback(() => {
    if (!lessonId) {
      return
    }
    const position = Math.max(0, Math.floor(lastTimeRef.current))
    if (position === lastReportedRef.current) {
      return
    }
    lastReportedRef.current = position
    void reportProgressApi(lessonId, position).catch(() => {
      // 进度上报失败不打断播放；下一周期继续尝试。
    })
  }, [lessonId])

  useEffect(() => {
    if (status !== 'ready') {
      return
    }
    const timer = setInterval(flushProgress, PROGRESS_REPORT_INTERVAL_MS)
    return () => {
      clearInterval(timer)
      flushProgress()
    }
  }, [flushProgress, status])

  useDidHide(() => {
    flushProgress()
  })

  /** 选集 / 自动连播：先落一次旧课时进度，再切换播放授权。 */
  const handleSelectLesson = useCallback(
    (lesson: VodLesson) => {
      if (lesson.id === lessonId) {
        return
      }
      flushProgress()
      // 手动选集、立即播放与倒计时连播都直接开始播放下一课。
      setAutoplayNext(true)
      setSelectedLesson({ id: lesson.id, title: lesson.title })
    },
    [flushProgress, lessonId]
  )

  /**
   * 调用 `/api/vod/finish-lesson` 标记已看完。
   *
   * 接口幂等：pending / done 状态下不重复请求。页面不再展示完成状态，
   * 成功时直接把课时列表标记为已完成；失败只轻提示，不打断播放。
   */
  const submitFinish = useCallback(async () => {
    if (!lessonId) {
      return
    }
    if (
      finishStatusRef.current === 'pending' ||
      finishStatusRef.current === 'done'
    ) {
      return
    }
    const targetLessonId = lessonId
    finishStatusRef.current = 'pending'
    try {
      await finishLesson(targetLessonId)
      if (
        !mountedRef.current ||
        activeLessonIdRef.current !== targetLessonId
      ) {
        return
      }
      finishStatusRef.current = 'done'
      // 常驻课时列表立即显示「已完成」，无需重新拉取课程详情。
      setCourseLessons((previous) =>
        previous.map((item) =>
          item.id === targetLessonId
            ? { ...item, is_finished: true }
            : item
        )
      )
    } catch (finishFailure) {
      if (
        !mountedRef.current ||
        activeLessonIdRef.current !== targetLessonId
      ) {
        return
      }
      finishStatusRef.current = 'error'
      void Taro.showToast({
        title: `看完标记未同步：${getErrorMessage(finishFailure)}`,
        icon: 'none'
      })
    }
  }, [lessonId])

  const handleEnded = useCallback(() => {
    // 播放结束时续播位置归零，下次进入从头播放；
    // 先把 0 上报到进度接口，即使 finish-lesson 失败也不会停在片尾。
    lastTimeRef.current = 0
    flushProgress()
    void submitFinish()
  }, [flushProgress, submitFinish])

  const handleTimeUpdate = (time: number, totalDuration: number) => {
    // 切换课时后的自动播放只对新挂载的播放器生效；真正开始播放后复位，
    // 避免之后因鉴权刷新等原因重挂载时再次自动播放。
    if (autoplayNext && time > 0) {
      setAutoplayNext(false)
    }
    // 已播放到结尾时把续播位置归零，避免下次进入直接停在片尾。
    const reachedEnd = totalDuration > 0 && time >= totalDuration - 0.5
    lastTimeRef.current = reachedEnd ? 0 : time
    if (totalDuration > 0) {
      setDuration(totalDuration)
      // 用视频真实元数据补全当前课时时长；只在变化时更新，避免每帧重渲染。
      const rounded = Math.round(totalDuration)
      setCourseLessons((previous) => {
        if (!lessonId) {
          return previous
        }
        let changed = false
        const next = previous.map((item) => {
          if (
            item.id !== lessonId ||
            item.duration_seconds === rounded
          ) {
            return item
          }
          changed = true
          return { ...item, duration_seconds: rounded }
        })
        return changed ? next : previous
      })
    }
  }

  const goBackToCourse = () => {
    if (resolvedCourseId) {
      void Taro.redirectTo({
        url: `/pages/course-detail/index?id=${resolvedCourseId}`
      })
      return
    }
    void Taro.navigateBack()
  }

  /** 观看权限过期：跳转课程详情并自动打开购买弹窗。 */
  const handleRepurchase = () => {
    setExpiredVisible(false)
    if (resolvedCourseId) {
      void Taro.redirectTo({
        url: `/pages/course-detail/index?id=${resolvedCourseId}&repurchase=1`
      })
      return
    }
    goBackToCourse()
  }

  /** 关闭过期弹窗并回到课程目录（课程详情页）。 */
  const handleBackToCatalog = () => {
    setExpiredVisible(false)
    goBackToCourse()
  }

  /** 自定义导航栏返回：优先回到上一页，直链进入时回到课程详情。 */
  const handleNavBack = () => {
    if (Taro.getCurrentPages().length > 1) {
      void Taro.navigateBack()
      return
    }
    goBackToCourse()
  }

  /** 播放页不再展示内联错误区，用轻提示反馈视频加载失败。 */
  const handlePlaybackError = (message: string) => {
    void Taro.showToast({
      title: message || '视频加载失败，请稍后重试',
      icon: 'none'
    })
  }

  const renderPlayerBody = () => {
    if (checking) {
      return <View className='loading-line'>正在确认登录状态…</View>
    }
    if (!allowed) {
      return (
        <View className='player-state'>
          <View className='state-block'>
            <Text>登录并购买课程后才能播放</Text>
            <Text
              className='state-block__action'
              onClick={() => openLoginModal('登录后即可播放课程')}
            >
              去登录
            </Text>
          </View>
        </View>
      )
    }
    if (status === 'loading' || status === 'idle') {
      return <View className='loading-line'>正在获取播放授权…</View>
    }
    if (status === 'error') {
      return (
        <View className='player-state'>
          <View className='state-block'>
            <Text>
              {isMockLogin && !accessDenied
                ? '测试模式下播放鉴权接口可能返回 401'
                : error}
            </Text>
            {accessDenied ? (
              <Text className='state-block__action' onClick={goBackToCourse}>
                返回课程详情购买
              </Text>
            ) : (
              <Text className='state-block__action' onClick={loadAuth}>
                重新获取授权
              </Text>
            )}
          </View>
        </View>
      )
    }
    if (!playAuth) {
      return (
        <View className='player-state'>
          <View className='state-block'>播放授权无效，请重试</View>
        </View>
      )
    }

    if (!playAuth.play_url) {
      return (
        <View className='player-state'>
          <View className='state-block'>
            <Text>视频地址暂时不可用，请稍后重试</Text>
            <Text className='state-block__action' onClick={loadAuth}>
              重新获取授权
            </Text>
          </View>
        </View>
      )
    }

    return (
      <View>
        <VodPlayer
          key={`${playAuth.lesson_id}-${playAuth.play_url}`}
          videoId='course-video'
          src={playAuth.play_url}
          title={lessonTitle}
          navTitle={lessonTitle}
          initialTime={playAuth.last_position}
          autoplay={autoplayNext}
          fullscreen={playerFullscreen}
          nextLesson={nextLesson}
          autoNext={autoNext}
          onAutoNextChange={setAutoNext}
          onSelectLesson={handleSelectLesson}
          onFullscreenChange={setPlayerFullscreen}
          onTimeUpdate={handleTimeUpdate}
          onEnded={handleEnded}
          onError={handlePlaybackError}
        />

        {/* 简化标题卡片：位于播放器与课程目录之间，仅保留当前课时标题。 */}
        <View className='player-title-card'>
          <View className='player-title-card__accent' />
          <Text className='player-title-card__eyebrow'>NOW PLAYING</Text>
          <Text className='player-title-card__title'>{lessonTitle}</Text>
        </View>

        {/* 常驻课时列表：紧贴标题卡片下方，不弹窗；点击任一条切换课时并续播。 */}
        <View className='lesson-list'>
          <View className='lesson-list__header'>
            <View className='lesson-list__heading'>
              <View className='lesson-list__bar' />
              <Text className='lesson-list__title'>课程目录</Text>
            </View>
            <Text className='lesson-list__count'>
              {courseLessons.length ? `共 ${courseLessons.length} 课` : ''}
            </Text>
          </View>
          {lessonsLoading ? (
            <Text className='lesson-list__hint'>正在加载章节…</Text>
          ) : null}
          {!lessonsLoading && lessonsError ? (
            <Text className='lesson-list__hint'>{lessonsError}</Text>
          ) : null}
          {!lessonsLoading && !lessonsError && !courseLessons.length ? (
            <Text className='lesson-list__hint'>暂无课时</Text>
          ) : null}
          {courseLessons.map((lesson, index) => {
            const isActive = lesson.id === lessonId
            const isFinished = Boolean(lesson.is_finished)
            const lessonDuration =
              isActive && duration > 0
                ? duration
                : lesson.duration_seconds
            const rowClass = [
              'lesson-row',
              isActive ? 'lesson-row--active' : '',
              isFinished ? 'lesson-row--finished' : ''
            ]
              .filter(Boolean)
              .join(' ')
            return (
              <View
                key={lesson.id}
                id={`lesson-row-${lesson.id}`}
                className={rowClass}
                hoverClass='lesson-row--pressed'
                hoverStayTime={90}
                onClick={() => handleSelectLesson(lesson)}
              >
                <Text className='lesson-row__index'>
                  {String(index + 1).padStart(2, '0')}
                </Text>
                <Text className='lesson-row__title'>{lesson.title}</Text>
                <View className='lesson-row__meta'>
                  <Text className='lesson-row__duration'>
                    {formatLessonDuration(lessonDuration)}
                  </Text>
                  {isFinished ? (
                    <Text className='lesson-row__status lesson-row__status--done'>
                      ✅ 已完成
                    </Text>
                  ) : null}
                  {isActive ? (
                    <Text className='lesson-row__status lesson-row__status--active'>
                      播放中
                    </Text>
                  ) : null}
                </View>
              </View>
            )
          })}
        </View>
      </View>
    )
  }

  return (
    <View
      className='page player-page'
      // 自定义导航栏：内容从状态栏 + 44px 标题栏下方开始。
      style={{ paddingTop: `${navInsetTop + 44}px` }}
    >
      {/* PageMeta 必须是页面第一个节点。显式写 portrait，退出全屏才能恢复竖屏
          （仅卸载 PageMeta 不会触发方向回退）。 */}
      <PageMeta
        pageOrientation={playerFullscreen ? 'landscape' : 'portrait'}
      />
      <MockModeBadge />
      {renderPlayerBody()}
      <ExpiredAccessModal
        visible={expiredVisible}
        onRepurchase={handleRepurchase}
        onBackToCatalog={handleBackToCatalog}
      />
      <LoginModal />
      {/* 全屏时整条导航栏隐藏，退出按钮只在视频画面内；胶囊为微信系统控件，
          无法通过小程序 API 隐藏，仅在深色画面上做视觉适配。 */}
      {!playerFullscreen ? (
        <View
          className='player-nav'
          style={{ paddingTop: `${navInsetTop}px` }}
        >
          <View className='player-nav__bar'>
            <View
              id='player-nav-back'
              className='player-nav__back'
              hoverClass='player-nav__back--pressed'
              onClick={handleNavBack}
            >
              <View className='player-nav__back-icon' />
            </View>
            <Text className='player-nav__title'>{lessonTitle}</Text>
          </View>
        </View>
      ) : null}
    </View>
  )
}
