import Taro from '@tarojs/taro'

import { getErrorMessage } from '../services/request'
import { store } from '../store'
import {
  hideAuthSheet,
  showAuthSheet
} from '../store/slices/authSheetSlice'

type AuthAction = () => void | Promise<void>

let pendingAction: AuthAction | null = null
let openerRoute = ''

export function getCurrentRoute(): string {
  try {
    const pages = Taro.getCurrentPages() as Array<{ route?: string }>
    const route = pages[pages.length - 1]?.route
    return route ? `/${route.replace(/^\/+/, '')}` : ''
  } catch {
    return ''
  }
}

function runAction(action: AuthAction): void {
  Promise.resolve()
    .then(action)
    .catch((error) => {
      void Taro.showToast({
        title: getErrorMessage(error),
        icon: 'none'
      })
    })
}

function isLoggedIn(): boolean {
  return Boolean(store.getState().user.token)
}

/**
 * 需要身份的操作入口：
 * - 已登录：立即执行原动作；
 * - 未登录：暂存动作并打开登录弹窗，登录成功后自动继续。
 */
export function requestAuth(action: AuthAction, reason = ''): boolean {
  if (isLoggedIn()) {
    runAction(action)
    return true
  }
  pendingAction = action
  openerRoute = getCurrentRoute()
  store.dispatch(showAuthSheet({ reason }))
  return false
}

/** 仅打开登录弹窗，登录成功后停留在当前页（由页面自行刷新数据）。 */
export function openLogin(reason = ''): void {
  pendingAction = null
  openerRoute = getCurrentRoute()
  store.dispatch(showAuthSheet({ reason }))
}

/** 登录成功：关闭弹窗并继续登录前被拦截的动作。 */
export function completeAuthSheet(): void {
  const action = pendingAction
  const openedAt = openerRoute
  pendingAction = null
  openerRoute = ''
  store.dispatch(hideAuthSheet())
  if (!action) {
    return
  }
  // 弹窗打开后用户已切换到别的页面时，丢弃原动作，避免在错误页面跳转。
  const currentRoute = getCurrentRoute()
  if (openedAt && currentRoute && currentRoute !== openedAt) {
    return
  }
  runAction(action)
}

/** 用户主动关闭或点遮罩：中止本次操作，不执行任何动作。 */
export function cancelAuthSheet(): void {
  pendingAction = null
  openerRoute = ''
  store.dispatch(hideAuthSheet())
}

/**
 * 弹窗打开期间切换了页面（例如点了底部 Tab）时取消 pending 动作，
 * 避免在错误页面执行原跳转。
 */
export function cancelAuthSheetIfStale(currentRoute = getCurrentRoute()): void {
  if (!store.getState().authSheet.visible) {
    return
  }
  if (openerRoute && currentRoute && currentRoute !== openerRoute) {
    cancelAuthSheet()
  }
}
