import { useEffect } from 'react'
import { Button, ScrollView, Text, View } from '@tarojs/components'
import Taro, { usePullDownRefresh } from '@tarojs/taro'

import CourseIconGrid, {
  type CourseIconItem
} from '../../components/CourseIconGrid'
import HotTopicCard from '../../components/HotTopicCard'
import LoginModal from '../../components/LoginModal'
import MockModeBadge from '../../components/MockModeBadge'
import { HOT_COURSE_PAGE_SIZE } from '../../constants'
import { useSystemConfig } from '../../hooks/useSystemConfig'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { fetchConfigs } from '../../store/slices/configSlice'
import { fetchHotCourses } from '../../store/slices/courseSlice'
import { openLoginModal } from '../../utils/loginModal'
import {
  goAcademy,
  goCourseDetail,
  goCourseList,
  goProfile
} from '../../utils/navigation'

import './index.scss'

const iconItems: CourseIconItem[] = [
  {
    key: 'academy',
    label: '课程广场',
    icon: '📚',
    background: '#f3e4c9'
  },
  {
    key: 'all-courses',
    label: '全部课程',
    icon: '🎬',
    background: '#e9e1d1'
  },
  {
    key: 'my-courses',
    label: '我的课程',
    icon: '🎓',
    background: '#e3eadb'
  },
  {
    key: 'profile',
    label: '个人中心',
    icon: '👤',
    background: '#efe2df'
  }
]

export default function HomePage() {
  const dispatch = useAppDispatch()
  const config = useSystemConfig()
  const token = useAppSelector((state) => state.user.token)
  const isMockLogin = useAppSelector((state) => state.user.isMockLogin)
  const hot = useAppSelector((state) => state.course.hot)

  useEffect(() => {
    if (token) {
      void dispatch(fetchHotCourses({ pageSize: HOT_COURSE_PAGE_SIZE }))
    }
  }, [dispatch, token])

  usePullDownRefresh(() => {
    const tasks: Array<Promise<unknown>> = [
      dispatch(fetchConfigs()).unwrap().catch(() => undefined)
    ]
    if (token) {
      tasks.push(
        dispatch(fetchHotCourses({ pageSize: HOT_COURSE_PAGE_SIZE }))
          .unwrap()
          .catch(() => undefined)
      )
    }
    void Promise.all(tasks).finally(() => {
      void Taro.stopPullDownRefresh()
    })
  })

  const requireLogin = (): boolean => {
    if (token) {
      return true
    }
    openLoginModal('登录后即可查看课程')
    return false
  }

  const handleIconSelect = (item: CourseIconItem) => {
    switch (item.key) {
      case 'academy':
        goAcademy()
        break
      case 'all-courses':
        if (requireLogin()) {
          goCourseList()
        }
        break
      case 'my-courses':
        if (requireLogin()) {
          goCourseList({ mode: 'mine' })
        }
        break
      case 'profile':
        goProfile()
        break
      default:
        break
    }
  }

  const handleMore = () => {
    if (requireLogin()) {
      goCourseList({ mode: 'hot' })
    }
  }

  const handleHotCourse = (courseId: number) => {
    if (requireLogin()) {
      goCourseDetail(courseId)
    }
  }

  const renderHotContent = () => {
    if (!token) {
      return (
        <View className='home-login-card'>
          <Text className='home-login-card__title'>登录后查看热门课程</Text>
          <Text className='home-login-card__desc'>
            微信一键登录，购买课程后解锁全部课时。
          </Text>
          <Button
            className='home-login-card__button'
            onClick={() => openLoginModal('登录后即可查看课程')}
          >
            去登录
          </Button>
        </View>
      )
    }

    if (hot.status === 'loading' && !hot.items.length) {
      return <View className='loading-line'>正在加载热门课程…</View>
    }

    if (hot.status === 'error' && !hot.items.length) {
      return (
        <View className='state-block'>
          <Text>
            {isMockLogin
              ? '测试模式下后端接口可能返回 401，暂不加载课程数据'
              : hot.error || '热门课程加载失败'}
          </Text>
          <Text
            className='state-block__action'
            onClick={() => {
              void dispatch(
                fetchHotCourses({ pageSize: HOT_COURSE_PAGE_SIZE })
              )
            }}
          >
            重新加载
          </Text>
        </View>
      )
    }

    if (!hot.items.length) {
      return <View className='state-block'>暂无热门课程</View>
    }

    return (
      <ScrollView
        className='home-hot-scroll'
        scrollX
        enhanced
        showScrollbar={false}
      >
        <View className='home-hot-scroll__track'>
          {hot.items.map((course) => (
            <HotTopicCard
              key={course.id}
              course={course}
              onTap={() => handleHotCourse(course.id)}
            />
          ))}
        </View>
      </ScrollView>
    )
  }

  return (
    <View className='page home-page'>
      <MockModeBadge />

      <View className='home-hero'>
        <View className='home-hero__glow' />
        <Text className='home-hero__eyebrow'>HEXIA ACADEMY</Text>
        <Text className='home-hero__title'>
          {config.home_page_title || '禾下美学院'}
        </Text>
        <Text className='home-hero__subtitle'>
          以系统课程，点亮每一次成长
        </Text>
        {config.home_notice ? (
          <View className='home-hero__notice'>
            <Text className='home-hero__notice-dot'>◆</Text>
            <Text className='home-hero__notice-text'>{config.home_notice}</Text>
          </View>
        ) : null}
      </View>

      <View className='home-icons section'>
        <CourseIconGrid items={iconItems} onSelect={handleIconSelect} />
      </View>

      <View className='section home-hot'>
        <View className='section-head'>
          <Text className='section-title'>
            {config.hot_topic_title || '热门课程'}
          </Text>
          <Text className='section-more' onClick={handleMore}>
            {config.hot_topic_more_text || '查看更多'}
          </Text>
        </View>
        {renderHotContent()}
      </View>

      <View className='home-footer'>
        <Text className='home-footer__brand'>禾下美学院</Text>
        <Text className='home-footer__text'>课程内容均已获得授权</Text>
      </View>

      <LoginModal />
    </View>
  )
}
