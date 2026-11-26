import { useEffect, useRef, useState } from 'react'
import {
  Button,
  Input,
  Text,
  View
} from '@tarojs/components'
import Taro, {
  useDidShow,
  usePullDownRefresh,
  useReachBottom,
  useRouter
} from '@tarojs/taro'

import CourseCard from '../../components/CourseCard'
import MockModeBadge from '../../components/MockModeBadge'
import WxAuthSheet from '../../components/WxAuthSheet'
import { DEFAULT_PAGE_SIZE } from '../../constants'
import { useRequireAuth } from '../../hooks/useRequireAuth'
import { useSystemConfig } from '../../hooks/useSystemConfig'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { fetchConfigs } from '../../store/slices/configSlice'
import {
  fetchCatalog,
  fetchMyCourses,
  resetCatalog
} from '../../store/slices/courseSlice'
import { safeDecode } from '../../utils/format'
import { goCourseDetail } from '../../utils/navigation'

import './index.scss'

type CourseListMode = 'all' | 'hot' | 'mine'

function resolveMode(value: string | undefined): CourseListMode {
  if (value === 'hot' || value === 'mine') {
    return value
  }
  return 'all'
}

export default function CourseListPage() {
  const router = useRouter()
  const dispatch = useAppDispatch()
  const config = useSystemConfig()
  const { openLogin } = useRequireAuth()
  const mode = resolveMode(router.params.mode)
  const initialKeyword = safeDecode(router.params.keyword).trim()
  const [searchInput, setSearchInput] = useState(initialKeyword)
  const [activeKeyword, setActiveKeyword] = useState(initialKeyword)

  const token = useAppSelector((state) => state.user.token)
  const isMockLogin = useAppSelector((state) => state.user.isMockLogin)
  const catalog = useAppSelector((state) => state.course.catalog)
  const mine = useAppSelector((state) => state.course.mine)
  const list = mode === 'mine' ? mine : catalog
  const shownOnceRef = useRef(false)

  useEffect(() => {
    if (mode === 'mine') {
      if (!token || isMockLogin) {
        return
      }
      void dispatch(fetchMyCourses({ page: 1, pageSize: DEFAULT_PAGE_SIZE }))
      return
    }
    dispatch(
      resetCatalog({
        keyword: activeKeyword,
        isHotTopic: mode === 'hot'
      })
    )
    void dispatch(
      fetchCatalog({
        page: 1,
        pageSize: DEFAULT_PAGE_SIZE,
        keyword: activeKeyword,
        isHotTopic: mode === 'hot' ? true : undefined
      })
    )
  }, [activeKeyword, dispatch, isMockLogin, mode, token])

  useDidShow(() => {
    // 返回「我的课程」时刷新，确保后台收回的课程不再展示。
    if (!shownOnceRef.current) {
      shownOnceRef.current = true
      return
    }
    if (mode !== 'mine' || !token || isMockLogin) {
      return
    }
    void dispatch(fetchMyCourses({ page: 1, pageSize: DEFAULT_PAGE_SIZE }))
  })

  usePullDownRefresh(() => {
    if (mode === 'mine' && (!token || isMockLogin)) {
      void Taro.stopPullDownRefresh()
      return
    }
    const tasks: Array<Promise<unknown>> = [
      dispatch(fetchConfigs()).unwrap().catch(() => undefined)
    ]
    if (mode === 'mine') {
      tasks.push(
        dispatch(fetchMyCourses({ page: 1, pageSize: DEFAULT_PAGE_SIZE }))
          .unwrap()
          .catch(() => undefined)
      )
    } else {
      dispatch(
        resetCatalog({
          keyword: activeKeyword,
          isHotTopic: mode === 'hot'
        })
      )
      tasks.push(
        dispatch(
          fetchCatalog({
            page: 1,
            pageSize: DEFAULT_PAGE_SIZE,
            keyword: activeKeyword,
            isHotTopic: mode === 'hot' ? true : undefined
          })
        )
          .unwrap()
          .catch(() => undefined)
      )
    }
    void Promise.all(tasks).finally(() => {
      void Taro.stopPullDownRefresh()
    })
  })

  useReachBottom(() => {
    if (
      (mode === 'mine' && (!token || isMockLogin)) ||
      !list.hasMore ||
      list.status === 'loading' ||
      list.page < 1
    ) {
      return
    }
    if (mode === 'mine') {
      void dispatch(
        fetchMyCourses({
          page: mine.page + 1,
          pageSize: mine.pageSize || DEFAULT_PAGE_SIZE,
          append: true
        })
      )
      return
    }
    void dispatch(
      fetchCatalog({
        page: catalog.page + 1,
        pageSize: catalog.pageSize || DEFAULT_PAGE_SIZE,
        keyword: catalog.keyword,
        isHotTopic: mode === 'hot' ? true : undefined,
        append: true
      })
    )
  })

  const submitSearch = () => {
    const nextKeyword = searchInput.trim()
    if (nextKeyword === activeKeyword) {
      dispatch(
        resetCatalog({ keyword: nextKeyword, isHotTopic: mode === 'hot' })
      )
      void dispatch(
        fetchCatalog({
          page: 1,
          pageSize: DEFAULT_PAGE_SIZE,
          keyword: nextKeyword,
          isHotTopic: mode === 'hot' ? true : undefined
        })
      )
      return
    }
    setActiveKeyword(nextKeyword)
  }

  const retry = () => {
    if (mode === 'mine') {
      void dispatch(fetchMyCourses({ page: 1, pageSize: DEFAULT_PAGE_SIZE }))
      return
    }
    void dispatch(
      fetchCatalog({
        page: 1,
        pageSize: DEFAULT_PAGE_SIZE,
        keyword: activeKeyword,
        isHotTopic: mode === 'hot' ? true : undefined
      })
    )
  }

  const heading =
    mode === 'mine'
      ? '我的课程'
      : mode === 'hot'
        ? config.hot_topic_title || '热门课程'
        : '全部课程'

  const renderList = () => {
    if (mode === 'mine' && !token) {
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
    if (mode === 'mine' && isMockLogin) {
      return (
        <View className='state-block'>
          测试模式不会请求真实课程列表；退出后使用手机号快捷登录即可查看已购课程。
        </View>
      )
    }
    if (list.status === 'loading' && !list.items.length) {
      return <View className='loading-line'>正在加载课程…</View>
    }
    if (list.status === 'error' && !list.items.length) {
      return (
        <View className='state-block'>
          <Text>
            {isMockLogin
              ? '测试模式下课程接口可能返回 401，暂不加载课程数据'
              : list.error || '课程列表加载失败'}
          </Text>
          <Text className='state-block__action' onClick={retry}>
            重新加载
          </Text>
        </View>
      )
    }
    if (!list.items.length) {
      return (
        <View className='state-block'>
          {mode === 'mine'
            ? '还没有课程，去课程广场看看吧'
            : mode === 'hot'
              ? '暂无热门课程'
              : '没有找到匹配的课程'}
        </View>
      )
    }

    return (
      <View>
        {list.items.map((course) => (
          <CourseCard
            key={course.id}
            course={course}
            owned={mode === 'mine'}
            onTap={() => goCourseDetail(course.id)}
          />
        ))}
        {list.status === 'loading' ? (
          <View className='loading-line'>正在加载更多…</View>
        ) : null}
        {!list.hasMore ? (
          <View className='course-list__end'>已展示全部课程</View>
        ) : null}
      </View>
    )
  }

  return (
    <View className='page course-list-page'>
      <MockModeBadge />

      <View className='section course-list__header'>
        <Text className='course-list__eyebrow'>COURSE LIBRARY</Text>
        <Text className='course-list__heading'>{heading}</Text>
        <Text className='course-list__count'>
          {mode === 'mine' ? '已购买或获赠的课程' : `共 ${list.total} 门课程`}
        </Text>

        {mode !== 'mine' ? (
          <View className='course-list__search'>
            <Input
              className='course-list__input'
              value={searchInput}
              placeholder={config.search_placeholder || '搜索课程名称'}
              placeholderClass='course-list__placeholder'
              confirmType='search'
              onInput={(event) => setSearchInput(event.detail.value)}
              onConfirm={submitSearch}
            />
            <Button className='course-list__search-btn' onClick={submitSearch}>
              搜索
            </Button>
          </View>
        ) : null}
      </View>

      <View className='section'>{renderList()}</View>

      <WxAuthSheet />
    </View>
  )
}
