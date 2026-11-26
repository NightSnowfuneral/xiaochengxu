import { useEffect, useRef } from 'react'
import { ScrollView, Text, View } from '@tarojs/components'
import Taro, {
  useDidShow,
  usePullDownRefresh,
  useReachBottom
} from '@tarojs/taro'

import CourseCard from '../../components/CourseCard'
import HotTopicCard from '../../components/HotTopicCard'
import MockModeBadge from '../../components/MockModeBadge'
import WxAuthSheet from '../../components/WxAuthSheet'
import { DEFAULT_PAGE_SIZE, HOT_COURSE_PAGE_SIZE } from '../../constants'
import { useRequireAuth } from '../../hooks/useRequireAuth'
import { useSystemConfig } from '../../hooks/useSystemConfig'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { fetchConfigs } from '../../store/slices/configSlice'
import {
  fetchCatalog,
  fetchHotCourses,
  fetchMyCourses
} from '../../store/slices/courseSlice'
import { goCourseDetail, goCourseList } from '../../utils/navigation'

import './index.scss'

export default function AcademyPage() {
  const dispatch = useAppDispatch()
  const config = useSystemConfig()
  const { openLogin } = useRequireAuth()
  const token = useAppSelector((state) => state.user.token)
  const isMockLogin = useAppSelector((state) => state.user.isMockLogin)
  const catalog = useAppSelector((state) => state.course.catalog)
  const hot = useAppSelector((state) => state.course.hot)
  const mine = useAppSelector((state) => state.course.mine)
  const shownOnceRef = useRef(false)

  useEffect(() => {
    // 课程广场公开浏览，未登录也加载热门与全部课程。
    void dispatch(fetchHotCourses({ pageSize: HOT_COURSE_PAGE_SIZE }))
    void dispatch(fetchCatalog({ page: 1, pageSize: DEFAULT_PAGE_SIZE }))
  }, [dispatch])

  useEffect(() => {
    // 我的课程属于身份数据：未登录绝不请求接口。
    if (!token || isMockLogin) {
      return
    }
    void dispatch(fetchMyCourses({ page: 1, pageSize: 3 }))
  }, [dispatch, isMockLogin, token])

  useDidShow(() => {
    // 首次显示由上面的 effect 加载；之后回到本页时刷新，
    // 确保后台收回课程后列表立即反映最新授权。
    if (!shownOnceRef.current) {
      shownOnceRef.current = true
      return
    }
    if (!token || isMockLogin) {
      return
    }
    void dispatch(fetchMyCourses({ page: 1, pageSize: 3 }))
  })

  usePullDownRefresh(() => {
    const tasks: Array<Promise<unknown>> = [
      dispatch(fetchConfigs()).unwrap().catch(() => undefined),
      dispatch(fetchHotCourses({ pageSize: HOT_COURSE_PAGE_SIZE }))
        .unwrap()
        .catch(() => undefined),
      dispatch(fetchCatalog({ page: 1, pageSize: DEFAULT_PAGE_SIZE }))
        .unwrap()
        .catch(() => undefined)
    ]
    if (token && !isMockLogin) {
      tasks.push(
        dispatch(fetchMyCourses({ page: 1, pageSize: 3 }))
          .unwrap()
          .catch(() => undefined)
      )
    }
    void Promise.all(tasks).finally(() => {
      void Taro.stopPullDownRefresh()
    })
  })

  useReachBottom(() => {
    if (!catalog.hasMore || catalog.status === 'loading' || catalog.page < 1) {
      return
    }
    void dispatch(
      fetchCatalog({
        page: catalog.page + 1,
        pageSize: catalog.pageSize || DEFAULT_PAGE_SIZE,
        keyword: catalog.keyword,
        isHotTopic: catalog.isHotTopic || undefined,
        append: true
      })
    )
  })

  const retryCatalog = () => {
    void dispatch(
      fetchCatalog({
        page: 1,
        pageSize: DEFAULT_PAGE_SIZE,
        keyword: catalog.keyword,
        isHotTopic: catalog.isHotTopic || undefined
      })
    )
  }

  const renderMineSection = () => {
    if (!token) {
      return (
        <View className='state-block'>
          <Text>登录后查看你的课程与预约</Text>
          <Text
            className='state-block__action'
            onClick={() => openLogin('登录后查看你的课程与预约')}
          >
            手机号快捷登录
          </Text>
        </View>
      )
    }
    if (isMockLogin) {
      return (
        <View className='academy-inline-note'>
          测试模式不会请求真实课程列表；退出后使用手机号快捷登录即可查看已购课程。
        </View>
      )
    }
    if (mine.status === 'loading' && !mine.items.length) {
      return <View className='loading-line'>正在加载我的课程…</View>
    }
    if (mine.status === 'error' && !mine.items.length) {
      return (
        <View className='state-block'>
          <Text>{mine.error || '我的课程加载失败'}</Text>
          <Text
            className='state-block__action'
            onClick={() => {
              void dispatch(fetchMyCourses({ page: 1, pageSize: 3 }))
            }}
          >
            重新加载
          </Text>
        </View>
      )
    }
    if (!mine.items.length) {
      return (
        <View className='state-block'>
          <Text>还没有课程，去课程广场看看吧</Text>
        </View>
      )
    }
    return (
      <View>
        {mine.items.slice(0, 3).map((course) => (
          <CourseCard
            key={course.id}
            course={course}
            owned
            onTap={() => goCourseDetail(course.id)}
          />
        ))}
      </View>
    )
  }

  const renderHotSection = () => {
    if (!hot.items.length) {
      if (hot.status === 'loading') {
        return <View className='loading-line'>正在加载热门课程…</View>
      }
      if (hot.status === 'error') {
        return (
          <View className='academy-inline-note'>
            {isMockLogin
              ? '测试模式：热门课程接口未授权（预期）'
              : '热门课程暂时无法加载'}
          </View>
        )
      }
      return null
    }

    return (
      <ScrollView
        className='academy-hot-scroll'
        scrollX
        enhanced
        showScrollbar={false}
      >
        <View className='academy-hot-scroll__track'>
          {hot.items.map((course) => (
            <HotTopicCard
              key={course.id}
              course={course}
              onTap={() => goCourseDetail(course.id)}
            />
          ))}
        </View>
      </ScrollView>
    )
  }

  const renderCatalog = () => {
    if (catalog.status === 'loading' && !catalog.items.length) {
      return <View className='loading-line'>正在加载课程…</View>
    }
    if (catalog.status === 'error' && !catalog.items.length) {
      return (
        <View className='state-block'>
          <Text>
            {isMockLogin
              ? '测试模式下课程接口可能返回 401，暂不加载课程数据'
              : catalog.error || '课程列表加载失败'}
          </Text>
          <Text className='state-block__action' onClick={retryCatalog}>
            重新加载
          </Text>
        </View>
      )
    }
    if (!catalog.items.length) {
      return <View className='state-block'>课程正在准备中</View>
    }

    return (
      <View>
        {catalog.items.map((course) => (
          <CourseCard
            key={course.id}
            course={course}
            onTap={() => goCourseDetail(course.id)}
          />
        ))}
        {catalog.status === 'loading' ? (
          <View className='loading-line'>正在加载更多…</View>
        ) : null}
        {!catalog.hasMore ? (
          <View className='academy-end'>已展示全部课程</View>
        ) : null}
      </View>
    )
  }

  return (
    <View className='page academy-page'>
      <MockModeBadge />

      <View className='academy-header section'>
        <Text className='academy-header__eyebrow'>ACADEMY</Text>
        <Text className='academy-header__title'>
          {config.academy_page_title || '商学院课程广场'}
        </Text>
        <Text className='academy-header__subtitle'>
          精选系统课程，按自己的节奏持续学习
        </Text>
      </View>

      <View className='section academy-search' onClick={() => goCourseList()}>
        <Text className='academy-search__icon'>⌕</Text>
        <Text className='academy-search__placeholder'>
          {config.search_placeholder || '搜索课程名称'}
        </Text>
      </View>

      <View className='section academy-hot'>
        <View className='section-head'>
          <Text className='section-title'>
            {config.hot_topic_title || '热门课程'}
          </Text>
          <Text
            className='section-more'
            onClick={() => goCourseList({ mode: 'hot' })}
          >
            全部热门
          </Text>
        </View>
        {renderHotSection()}
      </View>

      <View className='section academy-mine'>
        <View className='section-head'>
          <Text className='section-title'>我的课程</Text>
          {token ? (
            <Text
              className='section-more'
              onClick={() => goCourseList({ mode: 'mine' })}
            >
              全部
            </Text>
          ) : null}
        </View>
        {renderMineSection()}
      </View>

      <View className='section academy-catalog'>
        <View className='section-head'>
          <Text className='section-title'>全部课程</Text>
          <Text className='academy-catalog__count'>
            共 {catalog.total} 门
          </Text>
        </View>
        {renderCatalog()}
      </View>

      <WxAuthSheet />
    </View>
  )
}
