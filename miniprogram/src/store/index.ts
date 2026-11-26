import { combineReducers, configureStore } from '@reduxjs/toolkit'
import {
  FLUSH,
  PAUSE,
  PERSIST,
  PURGE,
  REGISTER,
  REHYDRATE,
  persistReducer,
  persistStore
} from 'redux-persist'
import type { PersistedState } from 'redux-persist/lib/types'

import { STORAGE_PERSIST_KEY } from '../constants'
import { setAuthSession } from '../services/session'
import authSheetReducer from './slices/authSheetSlice'
import configReducer from './slices/configSlice'
import courseReducer from './slices/courseSlice'
import orderReducer from './slices/orderSlice'
import userReducer from './slices/userSlice'
import { taroStorage } from './storage'

const rootReducer = combineReducers({
  user: userReducer,
  authSheet: authSheetReducer,
  config: configReducer,
  course: courseReducer,
  order: orderReducer
})

/**
 * redux-persist 配置。
 * 退出登录时必须调用 persistor.purge()，否则冷启动会自动恢复 user
 * 切片（含 token），表现为“退出后重新进入仍是已登录”。
 */
const persistConfig = {
  key: STORAGE_PERSIST_KEY,
  version: 2,
  storage: taroStorage,
  // 只持久化 C 端用户会话与展示配置；课程 / 订单 / 登录弹窗不落盘。
  whitelist: ['user', 'config'],
  migrate: (state: unknown) => {
    const next = { ...((state ?? {}) as Record<string, unknown>) }
    const storedUser = next.user
    if (storedUser && typeof storedUser === 'object') {
      const { initialized, loginStatus, error, ...user } = storedUser as Record<
        string,
        unknown
      >
      void initialized
      void loginStatus
      void error
      next.user = user
    }
    // 根状态带有 redux-persist 注入的 _persist，类型断言保持迁移透明。
    return Promise.resolve(next as unknown as PersistedState)
  }
}

const persistedReducer = persistReducer(persistConfig, rootReducer)

export const store = configureStore({
  reducer: persistedReducer,
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware({
      serializableCheck: {
        ignoredActions: [FLUSH, REHYDRATE, PAUSE, PERSIST, PURGE, REGISTER]
      }
    }),
  devTools: process.env.NODE_ENV !== 'production'
})

export const persistor = persistStore(store)

// 请求层不直接依赖 store，避免 store → slice → api → request 的循环引用。
store.subscribe(() => {
  const { user } = store.getState()
  setAuthSession(user.token, user.isMockLogin)
})

{
  const { user } = store.getState()
  setAuthSession(user.token, user.isMockLogin)
}

export type RootState = ReturnType<typeof store.getState>
export type AppDispatch = typeof store.dispatch
