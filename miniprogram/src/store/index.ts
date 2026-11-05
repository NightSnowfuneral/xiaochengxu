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

import { STORAGE_PERSIST_KEY } from '../constants'
import { setAuthSession } from '../services/session'
import configReducer from './slices/configSlice'
import courseReducer from './slices/courseSlice'
import orderReducer from './slices/orderSlice'
import userReducer from './slices/userSlice'
import { taroStorage } from './storage'

const rootReducer = combineReducers({
  user: userReducer,
  config: configReducer,
  course: courseReducer,
  order: orderReducer
})

const persistConfig = {
  key: STORAGE_PERSIST_KEY,
  version: 1,
  storage: taroStorage,
  // 只持久化 C 端用户会话与展示配置；课程 / 订单属于服务端实时数据。
  whitelist: ['user', 'config']
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
