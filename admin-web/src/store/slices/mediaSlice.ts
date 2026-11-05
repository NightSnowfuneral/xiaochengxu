import { createAsyncThunk, createSlice, type PayloadAction } from '@reduxjs/toolkit'

import {
  deleteVodMedia,
  listVodMedia,
  syncVodMediaStatus,
  updateVodMedia,
  uploadVodMedia
} from '../../api/mediaApi'
import { getErrorMessage } from '../../api/request'
import type {
  VodMedia,
  VodMediaListParams,
  VodMediaSyncResponse,
  VodMediaUpdatePayload
} from '../../types'

export interface MediaState {
  items: VodMedia[]
  total: number
  page: number
  pageSize: number
  keyword: string
  loading: boolean
  error: string | null
  uploading: boolean
  /** 0-100；-1 表示浏览器未提供总大小。 */
  uploadPercent: number
  uploadError: string | null
  syncing: boolean
  updating: boolean
  deletingId: number | null
}

const initialState: MediaState = {
  items: [],
  total: 0,
  page: 1,
  pageSize: 20,
  keyword: '',
  loading: false,
  error: null,
  uploading: false,
  uploadPercent: 0,
  uploadError: null,
  syncing: false,
  updating: false,
  deletingId: null
}

export const fetchMedia = createAsyncThunk<
  Awaited<ReturnType<typeof listVodMedia>>,
  VodMediaListParams,
  { rejectValue: string }
>('media/fetch', async (params, { rejectWithValue }) => {
  try {
    return await listVodMedia(params)
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

export const uploadMedia = createAsyncThunk<
  VodMedia,
  { file: File; onProgress?: (percent: number) => void },
  { rejectValue: string }
>('media/upload', async ({ file, onProgress }, { dispatch, rejectWithValue, signal }) => {
  try {
    return await uploadVodMedia(file, {
      signal,
      onProgress: (percent) => {
        dispatch(setUploadPercent(percent))
        onProgress?.(percent)
      }
    })
  } catch (error) {
    if (signal.aborted) {
      return rejectWithValue('已取消上传')
    }
    return rejectWithValue(getErrorMessage(error))
  }
})

export const syncMedia = createAsyncThunk<
  VodMediaSyncResponse,
  number[] | undefined,
  { rejectValue: string }
>('media/sync', async (mediaIds, { rejectWithValue }) => {
  try {
    return await syncVodMediaStatus(
      mediaIds && mediaIds.length ? { media_ids: mediaIds } : {}
    )
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

export const updateMedia = createAsyncThunk<
  VodMedia,
  { id: number; payload: VodMediaUpdatePayload },
  { rejectValue: string }
>('media/update', async ({ id, payload }, { rejectWithValue }) => {
  try {
    return await updateVodMedia(id, payload)
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

export const deleteMedia = createAsyncThunk<
  { id: number; message: string },
  number,
  { rejectValue: string }
>('media/delete', async (id, { rejectWithValue }) => {
  try {
    const result = await deleteVodMedia(id)
    return { id, message: result.message }
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

const mediaSlice = createSlice({
  name: 'media',
  initialState,
  reducers: {
    setUploadPercent(state, action: PayloadAction<number>) {
      state.uploadPercent = action.payload
    },
    clearUploadError(state) {
      state.uploadError = null
    }
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchMedia.pending, (state) => {
        state.loading = true
        state.error = null
      })
      .addCase(fetchMedia.fulfilled, (state, action) => {
        state.loading = false
        state.items = action.payload.items
        state.total = action.payload.total
        state.page = action.payload.page
        state.pageSize = action.payload.page_size
        state.keyword = action.meta.arg.keyword ?? ''
      })
      .addCase(fetchMedia.rejected, (state, action) => {
        state.loading = false
        state.error = action.payload ?? '媒资列表加载失败'
      })
      .addCase(uploadMedia.pending, (state) => {
        state.uploading = true
        state.uploadPercent = 0
        state.uploadError = null
      })
      .addCase(uploadMedia.fulfilled, (state) => {
        state.uploading = false
        state.uploadPercent = 100
      })
      .addCase(uploadMedia.rejected, (state, action) => {
        state.uploading = false
        state.uploadPercent = 0
        state.uploadError = action.meta.aborted
          ? '已取消上传'
          : action.payload ?? '视频上传失败'
      })
      .addCase(syncMedia.pending, (state) => {
        state.syncing = true
      })
      .addCase(syncMedia.fulfilled, (state, action) => {
        state.syncing = false
        const updated = new Map(
          action.payload.items.map((item) => [item.id, item])
        )
        state.items = state.items.map((item) => updated.get(item.id) ?? item)
      })
      .addCase(syncMedia.rejected, (state) => {
        state.syncing = false
      })
      .addCase(updateMedia.pending, (state) => {
        state.updating = true
      })
      .addCase(updateMedia.fulfilled, (state, action) => {
        state.updating = false
        state.items = state.items.map((item) =>
          item.id === action.payload.id ? action.payload : item
        )
      })
      .addCase(updateMedia.rejected, (state) => {
        state.updating = false
      })
      .addCase(deleteMedia.pending, (state, action) => {
        state.deletingId = action.meta.arg
      })
      .addCase(deleteMedia.fulfilled, (state, action) => {
        state.deletingId = null
        state.items = state.items.filter(
          (item) => item.id !== action.payload.id
        )
        state.total = Math.max(0, state.total - 1)
      })
      .addCase(deleteMedia.rejected, (state) => {
        state.deletingId = null
      })
  }
})

export const { setUploadPercent, clearUploadError } = mediaSlice.actions

export const selectMedia = (state: { media: MediaState }) => state.media

export default mediaSlice.reducer
