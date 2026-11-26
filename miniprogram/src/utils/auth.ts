import Taro from '@tarojs/taro'
import { getMockUser, MOCK_LOGIN_ENABLED } from '@mock-login'

import { IS_DEV } from '../config'
import { LOGIN_STORAGE_KEYS, STORAGE_PERSIST_KEY } from '../constants'
import {
  isUnauthorizedError,
  setUnauthorizedHandler
} from '../services/request'
import { setAuthSession } from '../services/session'
import {
  getProfile as getProfileApi,
  logoutRequest,
  tokenCheck,
  updateProfile as updateProfileApi,
  uploadAvatar as uploadAvatarApi,
  wxLogin
} from '../services/userApi'
import { persistor, store } from '../store'
import { resetOwnerScopedCourseData } from '../store/slices/courseSlice'
import { clearAuth, setAuth, updateProfile } from '../store/slices/userSlice'
import type { AuthUser, LoginUserInfo, UserProfileResponse } from '../types'
import { maskMobile } from './format'
import { ROUTES } from './navigation'

let bootstrapPromise: Promise<boolean> | null = null
let runtimeConfigured = false
/** 热启动鉴权防抖：短时间连续 onShow 复用最近一次校验结果。 */
const AUTH_CHECK_DEBOUNCE_MS = 2000
let inflightAuthCheck: Promise<boolean> | null = null
let lastAuthCheckAt = 0

function buildAuthUser(userInfo: LoginUserInfo, token: string): AuthUser {
  return {
    id: userInfo.userId,
    nickname: userInfo.nickname ?? '',
    mobile: userInfo.phoneMasked,
    avatar: userInfo.avatar ?? '',
    openid: userInfo.openid ?? undefined,
    token
  }
}

/** 后端个人资料接口返回未脱敏手机号，本地展示前统一脱敏。 */
function profilePatch(profile: UserProfileResponse) {
  return {
    nickname: profile.nickname ?? '',
    avatar: profile.avatar_url ?? '',
    mobile: profile.mobile ? maskMobile(profile.mobile) : null
  }
}

/**
 * 登录成功后的统一落盘：
 * ① 恢复 redux-persist 写入；
 * ② 写入认证状态切片（持久化快照由 store.subscribe 同步）。
 */
function applyLogin(authUser: AuthUser, isMockLogin: boolean): void {
  const token = authUser.token ?? ''
  resumePersistence()
  store.dispatch(setAuth({ profile: authUser, token, isMockLogin }))
}

/**
 * 手机号快捷登录：loginCode 来自 Taro.login()，phoneCode 来自
 * getPhoneNumber 回调的 e.detail.code。后端以手机号为主账号基准，
 * 不同账号使用同一手机号时自动合并到同一 user_id。
 */
export async function loginWithPhone(
  loginCode: string,
  phoneCode: string
): Promise<AuthUser> {
  const result = await wxLogin(loginCode, phoneCode)
  const authUser = buildAuthUser(result.userInfo, result.token)
  applyLogin(authUser, false)
  return authUser
}

/**
 * 仅开发环境使用（开发者工具无法调起 getPhoneNumber）。
 * 模拟对象字段严格固定，便于联调页面守卫与支付前流程。
 * 生产构建中该模块被 mockLogin.stub.ts 替换，不包含任何测试凭据。
 */
export async function loginAsMock(): Promise<AuthUser> {
  if (!MOCK_LOGIN_ENABLED) {
    throw new Error('模拟登录仅在开发环境可用')
  }
  const mockUser = getMockUser()
  applyLogin(mockUser, true)
  return mockUser
}

export async function refreshProfile(): Promise<UserProfileResponse | null> {
  if (!store.getState().user.token || store.getState().user.isMockLogin) {
    return null
  }
  const profile = await getProfileApi()
  store.dispatch(updateProfile(profilePatch(profile)))
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
  store.dispatch(updateProfile(profilePatch(profile)))
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
  store.dispatch(updateProfile(profilePatch(profile)))
}

/**
 * 清除所有本机登录缓存（不请求后端，不操作微信 session_key）。
 *
 * 登出、401 兜底、冷启动校验失败共用同一套清理流程，确保三条路径
 * 都不会残留 redux-persist 快照。
 */
async function clearLocalLoginState(): Promise<void> {
  // ② clearAuth：清空认证状态切片（userSlice 即当前认证状态）。
  store.dispatch(clearAuth())
  // 只清除与身份绑定的课程数据；公开热门/目录保留，页面不会闪空。
  store.dispatch(resetOwnerScopedCourseData())
  // 同步更新请求层会话快照，避免清理过程中仍携带旧 Token 发请求。
  setAuthSession(null, false)

  // ③ persistor.purge：清除 redux-persist 持久化缓存。
  try {
    await persistor.purge()
    // purge 本身会触发一次异步写回，先 flush 排空，避免它晚于下面的
    // Storage 删除又把持久化 key 写回来。
    await persistor.flush()
  } catch {
    // purge / flush 失败时仍继续清理 Storage，下面会再次删除持久化 key。
  }

  // ④ removeStorageSync：删除 token / userInfo 等全部登录缓存。
  //    openid 不属于登录凭证，按约定可以保留。
  removeLoginStorageKeys()

  // 暂停持久化写入：未登录期间页面的 config 刷新等 dispatch 不会再把
  // 持久化 key 写回来。下次登录时由 resumePersistence() 恢复。
  try {
    persistor.pause()
  } catch {
    // 暂停失败不影响已经完成的清理。
  }
}

/** 登录成功后恢复持久化写入（logout 期间曾暂停）。 */
function resumePersistence(): void {
  try {
    persistor.persist()
  } catch {
    // 恢复失败时本次会话仍可用，只是不会写入本机缓存。
  }
}

/** 删除登录相关 Storage，并兜底清理持久化 key 的历史分片。 */
function removeLoginStorageKeys(): void {
  const keys = new Set<string>(LOGIN_STORAGE_KEYS)
  try {
    Taro.getStorageInfoSync().keys.forEach((key) => {
      // 兼容 persist:huahuo-spark-root 及旧版本可能生成的分片键。
      if (key.includes(STORAGE_PERSIST_KEY)) {
        keys.add(key)
      }
    })
  } catch {
    // 读取 Storage 清单失败时，仅删除已知键。
  }
  keys.forEach((key) => {
    try {
      Taro.removeStorageSync(key)
    } catch {
      // 单个键删除失败不影响其余清理。
    }
  })
}

/**
 * 退出登录（严格五步）：
 * ① 调后端登出接口，把当前 Token 写入吊销名单；
 * ② clearAuth 清空认证状态切片；
 * ③ persistor.purge 清除 redux-persist 持久化缓存；
 * ④ removeStorageSync 删除 token / userInfo 等本地登录缓存；
 * ⑤ switchTab 回到首页，首页以未登录状态正常渲染。
 *
 * 后端不可达时仍完成本地清理，避免用户被困在已登录状态。
 */
export async function logout(): Promise<void> {
  const { token, isMockLogin } = store.getState().user

  // ① 后端作废当前 Token。
  if (token && !isMockLogin) {
    try {
      await logoutRequest(token)
    } catch {
      // 网络失败或 Token 已失效：本地清理照常进行。
    }
  }

  // ②③④ 清空内存状态、持久化缓存与本地身份快照。
  await clearLocalLoginState()

  // ⑤ 回到首页；首页永久公开，不依赖登录态。
  try {
    await Taro.switchTab({ url: ROUTES.home })
  } catch {
    // 页面栈异常时保持当前页面；用户仍处于已清理的未登录状态。
  }
}

export function configureAuthRuntime(): void {
  if (runtimeConfigured) {
    return
  }
  runtimeConfigured = true
  setUnauthorizedHandler(() => {
    const current = store.getState().user
    if (current.isMockLogin || !current.token) {
      return
    }
    // 运行期 401：只清理本地登录态，停留当前页，由页面渲染未登录态。
    void clearLocalLoginState()
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
 * 校验指定 Token，冷启动与热启动共用。
 *
 * - 校验期间重复调用直接复用同一个 Promise，避免并发请求；
 * - 校验返回前登录态已变化（登出 / 换号）：放弃本次结果，不覆盖新状态；
 * - `valid=false` 或 401：清理全部本地登录缓存并停留当前页；
 * - 网络异常：保留登录态，避免离线时误退出。
 */
function validateToken(token: string): Promise<boolean> {
  if (inflightAuthCheck) {
    return inflightAuthCheck
  }

  lastAuthCheckAt = Date.now()
  inflightAuthCheck = (async () => {
    try {
      const result = await tokenCheck(token)

      if (store.getState().user.token !== token) {
        return Boolean(store.getState().user.token)
      }

      if (!result.valid) {
        await clearLocalLoginState()
        return false
      }

      if (result.userInfo) {
        store.dispatch(
          setAuth({
            profile: buildAuthUser(result.userInfo, token),
            token,
            isMockLogin: false
          })
        )
      }
      return true
    } catch (error) {
      if (store.getState().user.token !== token) {
        return Boolean(store.getState().user.token)
      }
      if (isUnauthorizedError(error)) {
        await clearLocalLoginState()
        return false
      }
      // 网络异常（无法确认 Token 是否失效）时保留登录态。
      return true
    } finally {
      inflightAuthCheck = null
    }
  })()

  return inflightAuthCheck
}

/**
 * App 冷启动登录态校验（由 App.tsx 的 useLaunch 调用）。
 *
 * 首页永久公开：本地无 Token 时只结束校验，不跳转、不弹窗、不调起手机号
 * 授权。有 Token 才请求 /auth/token-check；失效时清空本地缓存并停留首页。
 */
export function bootstrapAuth(): Promise<boolean> {
  if (bootstrapPromise) {
    return bootstrapPromise
  }

  bootstrapPromise = (async () => {
    await waitForRehydration()

    if ((!MOCK_LOGIN_ENABLED || !IS_DEV) && store.getState().user.isMockLogin) {
      await clearLocalLoginState()
      return false
    }

    const persisted = store.getState().user
    if (!persisted.token) {
      return false
    }

    // 模拟 Token 仅开发环境可用，不请求后端校验。
    if (persisted.isMockLogin) {
      return true
    }

    return validateToken(persisted.token)
  })()

  return bootstrapPromise
}

/**
 * 热启动鉴权（由 App.tsx 的 useDidShow 调用）。
 *
 * 从后台切回、右上角重新进入、下拉唤起都会触发；这里只校验本地 Token，
 * 绝不重复调用 Taro.login / getPhoneNumber，也不自动拉起手机号授权。
 *
 * - 无 Token：直接返回，不跳转、不弹窗；
 * - 有 Token：POST /auth/token-check；失效则清理本地状态并停留当前页；
 * - 2 秒内连续 onShow 或已有校验进行中：复用结果，不重复发请求。
 */
export async function revalidateAuthOnShow(): Promise<boolean> {
  await waitForRehydration()

  if ((!MOCK_LOGIN_ENABLED || !IS_DEV) && store.getState().user.isMockLogin) {
    await clearLocalLoginState()
    return false
  }

  const session = store.getState().user
  if (!session.token) {
    return false
  }

  // 模拟 Token 仅开发环境可用，不请求后端校验。
  if (session.isMockLogin) {
    return true
  }

  if (inflightAuthCheck) {
    return inflightAuthCheck
  }

  if (Date.now() - lastAuthCheckAt < AUTH_CHECK_DEBOUNCE_MS) {
    return true
  }

  return validateToken(session.token)
}

// 应用启动早期即注册，避免首次 401 发生时 handler 尚未就绪。
configureAuthRuntime()
