import Taro from '@tarojs/taro'

import { IS_DEV } from '../config'
import { TAB_ROUTES } from '../constants'

function currentRoute(): string {
  const pages = Taro.getCurrentPages()
  const page = pages[pages.length - 1]
  return page?.route || ''
}

function normalizeText(value: string | undefined, fallback: string): string {
  const text = (value ?? '').trim()
  return text || fallback
}

/**
 * TabBar 固定两项，仅文字可配置；不在非 Tab 页面调用，避免原生报错。
 */
export async function applyTabBarTexts(
  homeText: string | undefined,
  courseText: string | undefined
): Promise<void> {
  if (!TAB_ROUTES.includes(currentRoute() as (typeof TAB_ROUTES)[number])) {
    return
  }
  const home = normalizeText(homeText, '首页')
  const course = normalizeText(courseText, '课程')

  try {
    await Taro.setTabBarItem({ index: 0, text: home })
    await Taro.setTabBarItem({ index: 1, text: course })
  } catch (error) {
    if (IS_DEV) {
      console.warn('[tabBar] 动态文字更新失败', error)
    }
  }
}
