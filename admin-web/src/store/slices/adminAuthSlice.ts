import { createAsyncThunk, createSlice, type PayloadAction } from '@reduxjs/toolkit'

import { adminLoginApi, adminLogoutApi } from '../../api/adminApi'
import { getErrorMessage } from '../../api/request'
import type { AdminProfile } from '../../types'
import { readAdminSession, type AdminSession } from '../../utils/session'

export type AdminAuthStatus =
  | 'idle'
  | 'loading'
  | 'authenticated'
  | 'unauthenticated'

export interface AdminAuthState {
  token: string | null
  admin: AdminProfile | null
  expiresAt: number | null
  status: AdminAuthStatus
  error: string | null
}

interface AdminLoginArgs {
  username: string
  password: string
}

interface AdminLoginResult {
  token: string
  admin: AdminProfile
  expiresAt: number
}

const storedSession = readAdminSession()

const initialState: AdminAuthState = {
  token: storedSession?.token ?? null,
  admin: storedSession?.admin ?? null,
  expiresAt: storedSession?.expiresAt ?? null,
  status: storedSession ? 'authenticated' : 'idle',
  error: null
}

export const loginAdmin = createAsyncThunk<
  AdminLoginResult,
  AdminLoginArgs,
  { rejectValue: string }
>('adminAuth/login', async (credentials, { rejectWithValue }) => {
  try {
    const result = await adminLoginApi({
      username: credentials.username.trim(),
      password: credentials.password
    })
    return {
      token: result.access_token,
      admin: result.admin,
      expiresAt: Date.now() + result.expires_in * 1000
    }
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

/**
 * 后端 JWT 为无状态令牌，退出只需清空本地会话。
 * pending 阶段立即清除 Redux/localStorage，后台请求只作确认；
 * 即使退出请求网络失败，也绝不会把令牌留在浏览器中。
 */
export const logoutAdmin = createAsyncThunk<void, string | undefined>(
  'adminAuth/logout',
  async (token) => {
    if (!token) {
      return
    }
    try {
      await adminLogoutApi(token)
    } catch {
      // 本地会话已在 pending 阶段清除；服务端退出接口仅作确认。
    }
  }
)

const adminAuthSlice = createSlice({
  name: 'adminAuth',
  initialState,
  reducers: {
    adminSessionInvalidated(state, action: PayloadAction<string | undefined>) {
      state.token = null
      state.admin = null
      state.expiresAt = null
      state.status = 'unauthenticated'
      state.error = action.payload ?? null
    },
    adminSessionRestored(state, action: PayloadAction<AdminSession>) {
      state.token = action.payload.token
      state.admin = action.payload.admin
      state.expiresAt = action.payload.expiresAt
      state.status = 'authenticated'
      state.error = null
    },
    clearLoginError(state) {
      state.error = null
    }
  },
  extraReducers: (builder) => {
    builder
      .addCase(loginAdmin.pending, (state) => {
        state.status = 'loading'
        state.error = null
      })
      .addCase(loginAdmin.fulfilled, (state, action) => {
        state.token = action.payload.token
        state.admin = action.payload.admin
        state.expiresAt = action.payload.expiresAt
        state.status = 'authenticated'
        state.error = null
      })
      .addCase(loginAdmin.rejected, (state, action) => {
        state.token = null
        state.admin = null
        state.expiresAt = null
        state.status = 'unauthenticated'
        state.error = action.payload || action.error.message || '登录失败'
      })
      .addCase(logoutAdmin.pending, (state) => {
        state.token = null
        state.admin = null
        state.expiresAt = null
        state.status = 'idle'
        state.error = null
      })
      .addCase(logoutAdmin.fulfilled, (state) => {
        state.token = null
        state.admin = null
        state.expiresAt = null
        state.status = 'idle'
        state.error = null
      })
  }
})

export const {
  adminSessionInvalidated,
  adminSessionRestored,
  clearLoginError
} = adminAuthSlice.actions

export const selectAdminAuth = (state: {
  adminAuth: AdminAuthState
}): AdminAuthState => state.adminAuth

export const selectIsAdminAuthenticated = (state: {
  adminAuth: AdminAuthState
}): boolean =>
  Boolean(
    state.adminAuth.token &&
      state.adminAuth.expiresAt &&
      state.adminAuth.expiresAt > Date.now()
  )

export default adminAuthSlice.reducer
