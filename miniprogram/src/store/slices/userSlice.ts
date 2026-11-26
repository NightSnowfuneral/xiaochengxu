import { createSlice, type PayloadAction } from '@reduxjs/toolkit'

import type { AuthUser } from '../../types'

export interface UserState {
  profile: AuthUser | null
  token: string | null
  isMockLogin: boolean
}

const initialState: UserState = {
  profile: null,
  token: null,
  isMockLogin: false
}

interface SetAuthPayload {
  profile: AuthUser
  token: string
  isMockLogin: boolean
}

const userSlice = createSlice({
  name: 'user',
  initialState,
  reducers: {
    setAuth(state, action: PayloadAction<SetAuthPayload>) {
      state.profile = action.payload.profile
      state.token = action.payload.token
      state.isMockLogin = action.payload.isMockLogin
    },
    updateProfile(
      state,
      action: PayloadAction<
        Partial<Pick<AuthUser, 'nickname' | 'mobile' | 'avatar'>>
      >
    ) {
      if (!state.profile) {
        return
      }
      state.profile = {
        ...state.profile,
        ...action.payload
      }
    },
    /**
     * 清空认证状态（退出登录、Token 失效时调用）。
     * 仅重置内存状态；本机持久化缓存由 logout 流程中的
     * persistor.purge() 与 Storage 清理负责。
     */
    clearAuth(state) {
      state.profile = null
      state.token = null
      state.isMockLogin = false
    }
  }
})

export const { clearAuth, setAuth, updateProfile } = userSlice.actions

export default userSlice.reducer
