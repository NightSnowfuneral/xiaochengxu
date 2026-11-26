import { createAsyncThunk, createSlice } from '@reduxjs/toolkit'

import {
  grantGiftApi,
  listGiftLogsApi,
  listPregiftsApi
} from '../../api/giftApi'
import { getErrorMessage } from '../../api/request'
import type {
  AdminPregift,
  AdminPregiftFilters,
  GiftGrantPayload,
  GiftGrantResult,
  GiftLog,
  GiftLogFilters,
  PageResponse
} from '../../types'

export interface FetchGiftLogsArgs {
  page?: number
  pageSize?: number
  filters?: GiftLogFilters
}

export interface FetchPregiftsArgs {
  page?: number
  pageSize?: number
  filters?: AdminPregiftFilters
}

export interface GiftState {
  logs: GiftLog[]
  total: number
  page: number
  pageSize: number
  filters: GiftLogFilters
  loading: boolean
  error: string | null
  granting: boolean
  lastResult: GiftGrantResult | null
  grantError: string | null
  pregifts: AdminPregift[]
  pregiftTotal: number
  pregiftPage: number
  pregiftPageSize: number
  pregiftFilters: AdminPregiftFilters
  pregiftLoading: boolean
  pregiftError: string | null
}

const initialState: GiftState = {
  logs: [],
  total: 0,
  page: 1,
  pageSize: 20,
  filters: {},
  loading: false,
  error: null,
  granting: false,
  lastResult: null,
  grantError: null,
  pregifts: [],
  pregiftTotal: 0,
  pregiftPage: 1,
  pregiftPageSize: 20,
  pregiftFilters: {},
  pregiftLoading: false,
  pregiftError: null
}

export const fetchGiftLogs = createAsyncThunk<
  PageResponse<GiftLog>,
  FetchGiftLogsArgs,
  { rejectValue: string }
>('gift/fetchLogs', async (args, { rejectWithValue }) => {
  try {
    const filters = args.filters ?? {}
    return await listGiftLogsApi({
      page: args.page ?? 1,
      page_size: args.pageSize ?? 20,
      ...filters
    })
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

export const fetchPregifts = createAsyncThunk<
  PageResponse<AdminPregift>,
  FetchPregiftsArgs,
  { rejectValue: string }
>('gift/fetchPregifts', async (args, { rejectWithValue }) => {
  try {
    const filters = args.filters ?? {}
    return await listPregiftsApi({
      page: args.page ?? 1,
      page_size: args.pageSize ?? 20,
      ...filters
    })
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

export const grantGift = createAsyncThunk<
  GiftGrantResult,
  GiftGrantPayload,
  { rejectValue: string }
>('gift/grant', async (payload, { rejectWithValue }) => {
  try {
    return await grantGiftApi(payload)
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

const giftSlice = createSlice({
  name: 'gift',
  initialState,
  reducers: {
    clearGrantFeedback(state) {
      state.lastResult = null
      state.grantError = null
    }
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchGiftLogs.pending, (state) => {
        state.loading = true
        state.error = null
      })
      .addCase(fetchGiftLogs.fulfilled, (state, action) => {
        state.loading = false
        state.logs = action.payload.items
        state.total = action.payload.total
        state.page = action.payload.page
        state.pageSize = action.payload.page_size
        state.filters = { ...(action.meta.arg.filters ?? {}) }
      })
      .addCase(fetchGiftLogs.rejected, (state, action) => {
        state.loading = false
        state.error =
          action.payload || action.error.message || '赠课日志加载失败'
      })
      .addCase(fetchPregifts.pending, (state) => {
        state.pregiftLoading = true
        state.pregiftError = null
      })
      .addCase(fetchPregifts.fulfilled, (state, action) => {
        state.pregiftLoading = false
        state.pregifts = action.payload.items
        state.pregiftTotal = action.payload.total
        state.pregiftPage = action.payload.page
        state.pregiftPageSize = action.payload.page_size
        state.pregiftFilters = { ...(action.meta.arg.filters ?? {}) }
      })
      .addCase(fetchPregifts.rejected, (state, action) => {
        state.pregiftLoading = false
        state.pregiftError =
          action.payload || action.error.message || '预赠记录加载失败'
      })
      .addCase(grantGift.pending, (state) => {
        state.granting = true
        state.grantError = null
        state.lastResult = null
      })
      .addCase(grantGift.fulfilled, (state, action) => {
        state.granting = false
        state.lastResult = action.payload
      })
      .addCase(grantGift.rejected, (state, action) => {
        state.granting = false
        state.grantError =
          action.payload || action.error.message || '赠课失败，请稍后重试'
      })
  }
})

export const { clearGrantFeedback } = giftSlice.actions

export const selectGift = (state: { gift: GiftState }): GiftState => state.gift

export default giftSlice.reducer
