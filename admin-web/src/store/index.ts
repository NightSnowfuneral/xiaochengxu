import { configureStore } from '@reduxjs/toolkit'

import {
  clearAdminSession,
  writeAdminSession
} from '../utils/session'
import adminAuthReducer from './slices/adminAuthSlice'
import courseManageReducer from './slices/courseManageSlice'
import giftReducer from './slices/giftSlice'
import lessonManageReducer from './slices/lessonManageSlice'
import mediaReducer from './slices/mediaSlice'
import sysConfigReducer from './slices/sysConfigSlice'

export const store = configureStore({
  reducer: {
    adminAuth: adminAuthReducer,
    courseManage: courseManageReducer,
    lessonManage: lessonManageReducer,
    media: mediaReducer,
    gift: giftReducer,
    sysConfig: sysConfigReducer
  },
  // 生产后台不向浏览器扩展暴露 Redux 历史（登录 thunk 参数含密码输入）。
  devTools: import.meta.env.DEV
})

function authSnapshot(): string {
  const { token, admin, expiresAt } = store.getState().adminAuth
  return JSON.stringify({ token, admin, expiresAt })
}

let lastAuthSnapshot = authSnapshot()

/**
 * 只持久化管理员会话（token + profile + 到期时间）。
 * 课程、课时、赠课日志、订单与配置永远从服务端读取，避免多标签页
 * 看到过期的业务数据。账号密码绝不写入任何存储。
 */
store.subscribe(() => {
  const nextSnapshot = authSnapshot()
  if (nextSnapshot === lastAuthSnapshot) {
    return
  }
  lastAuthSnapshot = nextSnapshot

  const { token, admin, expiresAt } = store.getState().adminAuth
  if (token && admin && expiresAt) {
    writeAdminSession({ token, admin, expiresAt })
  } else {
    clearAdminSession()
  }
})

export type RootState = ReturnType<typeof store.getState>
export type AppDispatch = typeof store.dispatch
