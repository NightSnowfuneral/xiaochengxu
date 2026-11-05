import Taro from '@tarojs/taro'
import { getMockUser, MOCK_LOGIN_ENABLED } from '@mock-login'

import { IS_DEV } from '../config'
import {
  getErrorMessage,
  setUnauthorizedHandler
} from '../services/request'
import {
  bindMobile as bindMobileApi,
  getProfile as getProfileApi,
  updateProfile as updateProfileApi,
  uploadAvatar as uploadAvatarApi,
  wxLogin
} from '../services/userApi'
import { persistor, store } from '../store'
import { resetCourseData } from '../store/slices/courseSlice'
import {
  clearUser,
  setCredentials,
  setInitialized,
  setLoginError,
  setLoginStatus,
  updateProfile
} from '../store/slices/userSlice'
import type { AuthUser, UserProfileResponse } from '../types'
import { closeLoginModal, openLoginModal } from './loginModal'

let bootstrapPromise: Promise<boolean> | null = null
let logoutSuppressed = false
let runtimeConfigured = false

function buildAuthUser(
  profile: UserProfileResponse,
  token: string
): AuthUser {
  return {
    id: profile.id,
    nickname: profile.nickname ?? '',
    mobile: profile.mobile,
    avatar: profile.avatar_url ?? '',
    token
  }
}

/**
 * 微信静默登录：wx.login -> code2Session（后端） -> C 端 JWT。
 * 不在前端接触 openid / session_key / 手机号明文。
 */
export async function loginWithWeChat(): Promise<AuthUser> {
  store.dispatch(setLoginStatus('loading'))
  try {
    const loginResult = await Taro.login()
    if (!loginResult.code) {
      throw new Error('微信登录失败：未获取到临时 code')
    }
    const result = await wxLogin(loginResult.code)
    const profile = buildAuthUser(result.user, result.access_token)
    logoutSuppressed = false
    store.dispatch(
      setCredentials({
        profile,
        token: result.access_token,
        isMockLogin: false
      })
    )
    return profile
  } catch (error) {
    store.dispatch(setLoginError(getErrorMessage(error)))
    throw error
  }
}

/**
 * 仅开发环境使用。模拟对象字段严格固定，便于联调页面守卫与支付前流程。
 * 生产构建中该模块被 mockLogin.stub.ts 替换，不包含任何测试凭据。
 */
export async function loginAsMock(): Promise<AuthUser> {
  if (!MOCK_LOGIN_ENABLED) {
    throw new Error('模拟登录仅在开发环境可用')
  }
  const mockUser = getMockUser()
  logoutSuppressed = false
  store.dispatch(
    setCredentials({
      profile: mockUser,
      token: mockUser.token || 'mock_test_token_123456',
      isMockLogin: true
    })
  )
  return mockUser
}

/**
 * getPhoneNumber 返回的 code 只能由后端换取手机号。
 * 若尚未登录，先完成静默登录再绑定。
 */
export async function bindPhoneWithCode(
  code: string
): Promise<UserProfileResponse> {
  if (store.getState().user.isMockLogin) {
    throw new Error('测试模式不会绑定真实手机号，请退出后使用微信登录')
  }
  if (!store.getState().user.token) {
    await loginWithWeChat()
  }
  const profile = await bindMobileApi(code)
  store.dispatch(updateProfile({ mobile: profile.mobile }))
  return profile
}

export async function refreshProfile(): Promise<UserProfileResponse | null> {
  if (!store.getState().user.token || store.getState().user.isMockLogin) {
    return null
  }
  const profile = await getProfileApi()
  store.dispatch(
    updateProfile({
      nickname: profile.nickname ?? '',
      avatar: profile.avatar_url ?? '',
      mobile: profile.mobile
    })
  )
  return profile
}

/** 保存微信昵称，成功后同步到本地登录态。 */
export async function saveNickname(nickname: string): Promise<void> {
  const state = store.getState().user
  if (!state.profile) {
    throw new Error('请先登录')
  }
  const normalized = nickname.trim()
  if (!normalized) {
    throw new Error('昵称不能为空')
  }
  if (state.isMockLogin) {
    store.dispatch(updateProfile({ nickname: normalized }))
    return
  }
  const profile = await updateProfileApi(normalized)
  store.dispatch(
    updateProfile({
      nickname: profile.nickname ?? '',
      avatar: profile.avatar_url ?? '',
      mobile: profile.mobile
    })
  )
}

/** 上传微信头像并保存 COS 地址；mock 模式仅本地预览临时路径。 */
export async function saveAvatar(filePath: string): Promise<void> {
  const state = store.getState().user
  if (!state.profile) {
    throw new Error('请先登录')
  }
  if (state.isMockLogin) {
    store.dispatch(updateProfile({ avatar: filePath }))
    return
  }
  const profile = await uploadAvatarApi(filePath)
  store.dispatch(
    updateProfile({
      nickname: profile.nickname ?? '',
      avatar: profile.avatar_url ?? '',
      mobile: profile.mobile
    })
  )
}

export function logout(): void {
  logoutSuppressed = true
  store.dispatch(clearUser())
  store.dispatch(resetCourseData())
  closeLoginModal()
  // 立即写入清空后的会话，避免进程被杀后本地残留旧 Token。
  void persistor.flush()
}

export function configureAuthRuntime(): void {
  if (runtimeConfigured) {
    return
  }
  runtimeConfigured = true
  setUnauthorizedHandler(() => {
    const current = store.getState().user
    if (current.isMockLogin) {
      return
    }
    if (!current.token) {
      openLoginModal('请先登录后继续')
      return
    }
    logoutSuppressed = true
    store.dispatch(clearUser())
    store.dispatch(resetCourseData())
    void persistor.flush()
    openLoginModal('登录状态已过期，请重新登录')
  })
}

function isRehydrated(): boolean {
  const state = store.getState() as {
    _persist?: { rehydrated?: boolean }
  }
  return Boolean(state._persist?.rehydrated)
}

function waitForRehydration(): Promise<void> {
  if (isRehydrated()) {
    return Promise.resolve()
  }
  return new Promise((resolve) => {
    let finished = false
    const finish = () => {
      if (finished) {
        return
      }
      finished = true
      unsubscribe()
      clearTimeout(timer)
      resolve()
    }
    const unsubscribe = store.subscribe(() => {
      if (isRehydrated()) {
        finish()
      }
    })
    // 防御性超时：极端情况下 Storage 异常也不能永久阻塞页面守卫。
    const timer = setTimeout(finish, 3000)
  })
}

/**
 * App 启动静默登录。持久化恢复完成后再判断：
 * 1. 已有 Token 直接复用；
 * 2. 生产环境清除意外残留的模拟会话；
 * 3. 开发环境 wx.login 失败时自动降级模拟登录；
 * 4. 用户主动退出后，本次会话不再自动重新登录。
 */
export function bootstrapAuth(): Promise<boolean> {
  if (bootstrapPromise) {
    return bootstrapPromise
  }

  bootstrapPromise = (async () => {
    await waitForRehydration()
    const persisted = store.getState().user

    if ((!MOCK_LOGIN_ENABLED || !IS_DEV) && persisted.isMockLogin) {
      store.dispatch(clearUser())
      store.dispatch(resetCourseData())
    }

    if (store.getState().user.token) {
      store.dispatch(setInitialized(true))
      return true
    }

    if (logoutSuppressed) {
      store.dispatch(setInitialized(true))
      return false
    }

    try {
      await loginWithWeChat()
      return true
    } catch {
      if (MOCK_LOGIN_ENABLED && IS_DEV) {
        try {
          await loginAsMock()
          return true
        } catch {
          // 继续走未登录流程。
        }
      }
      store.dispatch(setInitialized(true))
      return false
    }
  })()

  return bootstrapPromise
}

export async function ensureAuthenticated(): Promise<boolean> {
  await bootstrapAuth()
  return Boolean(store.getState().user.token)
}

// 应用启动早期即注册，避免首次 401 发生时 handler 尚未就绪。
configureAuthRuntime()
