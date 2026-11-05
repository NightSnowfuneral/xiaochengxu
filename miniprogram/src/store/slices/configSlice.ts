import { createAsyncThunk, createSlice } from '@reduxjs/toolkit'

import { getErrorMessage } from '../../services/request'
import { getPublicConfigs } from '../../services/systemApi'
import { normalizeConfigValues } from '../../utils/config'

export interface ConfigState {
  values: Record<string, string>
  loaded: boolean
  loading: boolean
  error: string | null
  lastFetchedAt: number | null
}

const initialState: ConfigState = {
  values: normalizeConfigValues(null),
  loaded: false,
  loading: false,
  error: null,
  lastFetchedAt: null
}

interface ConfigPayload {
  values: Record<string, string>
  fetchedAt: number
}

export const fetchConfigs = createAsyncThunk<
  ConfigPayload,
  void,
  { state: { config: ConfigState }; rejectValue: string }
>(
  'config/fetchConfigs',
  async (_, { rejectWithValue }) => {
    try {
      const response = await getPublicConfigs()
      return {
        values: normalizeConfigValues(response.configs),
        fetchedAt: Date.now()
      }
    } catch (error) {
      return rejectWithValue(getErrorMessage(error))
    }
  },
  {
    condition: (_, { getState }) => !getState().config.loading
  }
)

const configSlice = createSlice({
  name: 'config',
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
        state.loaded = true
        state.values = action.payload.values
        state.lastFetchedAt = action.payload.fetchedAt
      })
      .addCase(fetchConfigs.rejected, (state, action) => {
        state.loading = false
        state.error = action.payload || action.error.message || '配置加载失败'
        // 保留上一份配置与本地默认值，页面仍可正常渲染。
      })
  }
})

export const selectConfigState = (state: { config: ConfigState }): ConfigState =>
  state.config

export const selectConfigValues = (state: {
  config: ConfigState
}): Record<string, string> => state.config.values

export function selectConfigValue(
  state: { config: ConfigState },
  key: string
): string {
  return state.config.values[key] ?? ''
}

export default configSlice.reducer
