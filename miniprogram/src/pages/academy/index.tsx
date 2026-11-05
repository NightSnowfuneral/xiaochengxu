import { useEffect } from 'react'
import { ScrollView, Text, View } from '@tarojs/components'
import Taro, {
  usePullDownRefresh,
  useReachBottom
} from '@tarojs/taro'

import CourseCard from '../../components/CourseCard'
import HotTopicCard from '../../components/HotTopicCard'
import LoginModal from '../../components/LoginModal'
import MockModeBadge from '../../components/MockModeBadge'
import { DEFAULT_PAGE_SIZE, HOT_COURSE_PAGE_SIZE } from '../../constants'
import { useAuthGuard } from '../../hooks/useAuthGuard'
import { useSystemConfig } from '../../hooks/useSystemConfig'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { fetchConfigs } from '../../store/slices/configSlice'
import {
  fetchCatalog,
  fetchHotCourses
} from '../../store/slices/courseSlice'
import { openLoginModal } from '../../utils/loginModal'
import { goCourseDetail, goCourseList } from '../../utils/navigation'

import './index.scss'

export default function AcademyPage() {
  const dispatch = useAppDispatch()
  const config = useSystemConfig()
  const { checking, allowed } = useAuthGuard()
  const token = useAppSelector((state) => state.user.token)
  const isMockLogin = useAppSelector((state) => state.user.isMockLogin)
  const catalog = useAppSelector((state) => state.course.catalog)
  const hot = useAppSelector((state) => state.course.hot)

  useEffect(() => {
    if (!allowed || !token) {
      return
    }
    void dispatch(fetchHotCourses({ pageSize: HOT_COURSE_PAGE_SIZE }))
    void dispatch(fetchCatalog({ page: 1, pageSize: DEFAULT_PAGE_SIZE }))
  }, [allowed, dispatch, token])

  usePullDownRefresh(() => {
    if (!allowed || !token) {
      void Taro.stopPullDownRefresh()
      return
    }
    const tasks: Array<Promise<unknown>> = [
      dispatch(fetchConfigs()).unwrap().catch(() => undefined),
      dispatch(fetchHotCourses({ pageSize: HOT_COURSE_PAGE_SIZE }))
        .unwrap()
        .catch(() => undefined),
      dispatch(fetchCatalog({ page: 1, pageSize: DEFAULT_PAGE_SIZE }))
        .unwrap()
        .catch(() => undefined)
    ]
    void Promise.all(tasks).finally(() => {
      void Taro.stopPullDownRefresh()
    })
  })

  useReachBottom(() => {
    if (
      !allowed ||
      !catalog.hasMore ||
      catalog.status === 'loading' ||
      catalog.page < 1
    ) {
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

      {checking ? (
        <View className='section'>
          <View className='loading-line'>正在确认登录状态…</View>
        </View>
      ) : !allowed ? (
        <View className='section'>
          <View className='state-block'>
            <Text>登录后即可查看商学院课程</Text>
            <Text
              className='state-block__action'
              onClick={() => openLoginModal('登录后即可查看课程')}
            >
              去登录
            </Text>
          </View>
        </View>
      ) : (
        <>
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

          <View className='section academy-catalog'>
            <View className='section-head'>
              <Text className='section-title'>全部课程</Text>
              <Text className='academy-catalog__count'>
                共 {catalog.total} 门
              </Text>
            </View>
            {renderCatalog()}
          </View>
        </>
      )}

      <LoginModal />
    </View>
  )
}
