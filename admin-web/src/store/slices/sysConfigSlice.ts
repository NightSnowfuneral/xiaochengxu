import { createAsyncThunk, createSlice } from '@reduxjs/toolkit'

import {
  listAdminConfigs,
  resetAdminConfig,
  resetAllAdminConfigs,
  updateAdminConfig
} from '../../api/sysConfigApi'
import { getErrorMessage } from '../../api/request'
import type { SystemConfig, SystemConfigListResponse } from '../../types'

export interface SysConfigState {
  items: SystemConfig[]
  loading: boolean
  error: string | null
  savingKey: string | null
  resettingKey: string | null
  resettingAll: boolean
}

const initialState: SysConfigState = {
  items: [],
  loading: false,
  error: null,
  savingKey: null,
  resettingKey: null,
  resettingAll: false
}

export const fetchConfigs = createAsyncThunk<
  SystemConfigListResponse,
  void,
  { rejectValue: string }
>('sysConfig/fetch', async (_, { rejectWithValue }) => {
  try {
    return await listAdminConfigs()
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

export const updateConfig = createAsyncThunk<
  SystemConfig,
  { configKey: string; configValue: string },
  { rejectValue: string }
>('sysConfig/update', async ({ configKey, configValue }, { rejectWithValue }) => {
  try {
    return await updateAdminConfig(configKey, configValue)
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

export const resetConfig = createAsyncThunk<
  SystemConfig,
  string,
  { rejectValue: string }
>('sysConfig/resetOne', async (configKey, { rejectWithValue }) => {
  try {
    return await resetAdminConfig(configKey)
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

export const resetAllConfigs = createAsyncThunk<
  SystemConfig[],
  void,
  { rejectValue: string }
>('sysConfig/resetAll', async (_, { rejectWithValue }) => {
  try {
    const response = await resetAllAdminConfigs()
    return response.items
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

const sysConfigSlice = createSlice({
  name: 'sysConfig',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchConfigs.pending, (state) => {
        state.loading = true
        state.error = null
      })
      .addCase(fetchConfigs.fulfilled, (state, action) => {
        state.loading = false
        state.items = action.payload.items
      })
      .addCase(fetchConfigs.rejected, (state, action) => {
        state.loading = false
        state.error =
          action.payload || action.error.message || '系统配置加载失败'
      })
      .addCase(updateConfig.pending, (state, action) => {
        state.savingKey = action.meta.arg.configKey
      })
      .addCase(updateConfig.fulfilled, (state, action) => {
        state.savingKey = null
        state.items = state.items.map((item) =>
          item.config_key === action.payload.config_key ? action.payload : item
        )
      })
      .addCase(updateConfig.rejected, (state) => {
        state.savingKey = null
      })
      .addCase(resetConfig.pending, (state, action) => {
        state.resettingKey = action.meta.arg
      })
      .addCase(resetConfig.fulfilled, (state, action) => {
        state.resettingKey = null
        state.items = state.items.map((item) =>
          item.config_key === action.payload.config_key ? action.payload : item
        )
      })
      .addCase(resetConfig.rejected, (state) => {
        state.resettingKey = null
      })
      .addCase(resetAllConfigs.pending, (state) => {
        state.resettingAll = true
      })
      .addCase(resetAllConfigs.fulfilled, (state, action) => {
        state.resettingAll = false
        state.items = action.payload
      })
      .addCase(resetAllConfigs.rejected, (state) => {
        state.resettingAll = false
      })
  }
})

export const selectSysConfig = (state: {
  sysConfig: SysConfigState
}): SysConfigState => state.sysConfig

export default sysConfigSlice.reducer
