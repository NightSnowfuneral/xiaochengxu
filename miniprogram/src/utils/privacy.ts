/**
 * 微信隐私授权（用户隐私保护指引）统一处理。
 *
 * 2023-09 起微信强制校验隐私协议：未同意时调用 getPhoneNumber 等隐私接口，
 * 会先触发 wx.onNeedPrivacyAuthorization，开发者必须自行弹窗并 resolve，
 * 否则接口直接失败、拿不到 event.detail.code。
 *
 * 这里在 app 启动时只注册一次监听，页面通过订阅拿到「有待处理的隐私授权」，
 * 再用 <Button open-type="agreePrivacyAuthorization"> 完成同意。
 */

import Taro from '@tarojs/taro'

type PrivacyResolve = (result: {
  event: 'agree' | 'disagree'
  buttonId?: string
}) => void

let pendingResolve: PrivacyResolve | null = null
let installed = false

const listeners = new Set<() => void>()

function notify() {
  listeners.forEach((listener) => {
    try {
      listener()
    } catch {
      // 某个页面订阅回调异常不应影响其它页面。
    }
  })
}

function getWeappApi() {
  const api = (globalThis as any).wx
  return api && typeof api === 'object' ? api : null
}

/** 在 app useLaunch 中调用一次。 */
export function setupPrivacyAuthorization() {
  if (installed) {
    return
  }
  const wxApi = getWeappApi()
  if (!wxApi || typeof wxApi.onNeedPrivacyAuthorization !== 'function') {
    return
  }
  installed = true
  wxApi.onNeedPrivacyAuthorization((resolve: PrivacyResolve) => {
    // 后一次请求直接覆盖前一次：隐私接口串行触发，用户只处理最新一次。
    pendingResolve = resolve
    notify()
  })
}

export function isPrivacyPending() {
  return pendingResolve !== null
}

export function subscribePrivacy(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** 必须在 open-type=agreePrivacyAuthorization 按钮的回调里调用。 */
export function agreePrivacy(buttonId: string) {
  const resolve = pendingResolve
  pendingResolve = null
  notify()
  resolve?.({ event: 'agree', buttonId })
}

export function disagreePrivacy() {
  const resolve = pendingResolve
  pendingResolve = null
  notify()
  resolve?.({ event: 'disagree' })
}

/** 打开《用户隐私保护指引》，用于弹窗里的「查看指引」。 */
export function openPrivacyContract() {
  const wxApi = getWeappApi()
  if (!wxApi || typeof wxApi.openPrivacyContract !== 'function') {
    return
  }
  wxApi.openPrivacyContract({
    fail: () => {
      void Taro.showToast({
        title: '隐私指引打开失败，请稍后重试',
        icon: 'none'
      })
    }
  })
}
