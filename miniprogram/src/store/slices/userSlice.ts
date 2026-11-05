import { createSlice, type PayloadAction } from '@reduxjs/toolkit'

import type { AuthUser } from '../../types'

export type LoginStatus = 'idle' | 'loading' | 'success' | 'error'

export interface UserState {
  profile: AuthUser | null
  token: string | null
  isMockLogin: boolean
  initialized: boolean
  loginStatus: LoginStatus
  error: string | null
}

const initialState: UserState = {
  profile: null,
  token: null,
  isMockLogin: false,
  initialized: false,
  loginStatus: 'idle',
  error: null
}

interface SetCredentialsPayload {
  profile: AuthUser
  token: string
  isMockLogin: boolean
}

const userSlice = createSlice({
  name: 'user',
  initialState,
  reducers: {
    setCredentials(state, action: PayloadAction<SetCredentialsPayload>) {
      state.profile = action.payload.profile
      state.token = action.payload.token
      state.isMockLogin = action.payload.isMockLogin
      state.loginStatus = 'success'
      state.error = null
      state.initialized = true
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
    setInitialized(state, action: PayloadAction<boolean>) {
      state.initialized = action.payload
    },
    setLoginStatus(state, action: PayloadAction<LoginStatus>) {
      state.loginStatus = action.payload
      if (action.payload !== 'error') {
        state.error = null
      }
    },
    setLoginError(state, action: PayloadAction<string>) {
      state.loginStatus = 'error'
      state.error = action.payload
    },
    clearUser(state) {
      state.profile = null
      state.token = null
      state.isMockLogin = false
      state.initialized = true
      state.loginStatus = 'idle'
      state.error = null
    }
  }
})

export const {
  clearUser,
  setCredentials,
  setInitialized,
  setLoginError,
  setLoginStatus,
  updateProfile
} = userSlice.actions

export const selectUserState = (state: { user: UserState }): UserState =>
  state.user

export default userSlice.reducer
