import { useEffect } from 'react'
import { useDidShow } from '@tarojs/taro'

import { useAppDispatch, useAppSelector } from '../store/hooks'
import { fetchConfigs } from '../store/slices/configSlice'
import { applyTabBarTexts } from '../utils/tabBar'

/**
 * 每个页面 onShow 拉取公开配置；Tab 文字固定两项，
 * 只根据 tab_home_text / tab_course_text 动态更新文字。
 */
export function useSystemConfig(): Record<string, string> {
  const dispatch = useAppDispatch()
  const values = useAppSelector((state) => state.config.values)
  const homeText = values.tab_home_text
  const courseText = values.tab_course_text

  useDidShow(() => {
    void dispatch(fetchConfigs())
  })

  useEffect(() => {
    void applyTabBarTexts(homeText, courseText)
  }, [homeText, courseText])

  return values
}
