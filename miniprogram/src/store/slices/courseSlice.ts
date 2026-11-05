import { createAsyncThunk, createSlice, type PayloadAction } from '@reduxjs/toolkit'

import {
  DEFAULT_PAGE_SIZE,
  HOT_COURSE_PAGE_SIZE
} from '../../constants'
import {
  getCourseDetail,
  getCourses,
  getMyCourses
} from '../../services/courseApi'
import { getErrorMessage } from '../../services/request'
import type { CourseDetail, CourseListItem } from '../../types'

export type LoadStatus = 'idle' | 'loading' | 'success' | 'error'

export interface ListViewState {
  items: CourseListItem[]
  total: number
  page: number
  pageSize: number
  hasMore: boolean
  status: LoadStatus
  error: string | null
  keyword: string
  isHotTopic: boolean
}

export interface HotViewState {
  items: CourseListItem[]
  total: number
  status: LoadStatus
  error: string | null
}

export interface DetailEntry {
  data: CourseDetail | null
  status: LoadStatus
  error: string | null
}

export interface CourseState {
  catalog: ListViewState
  hot: HotViewState
  mine: ListViewState
  details: Record<string, DetailEntry>
}

function createListView(): ListViewState {
  return {
    items: [],
    total: 0,
    page: 0,
    pageSize: DEFAULT_PAGE_SIZE,
    hasMore: true,
    status: 'idle',
    error: null,
    keyword: '',
    isHotTopic: false
  }
}

const initialState: CourseState = {
  catalog: createListView(),
  hot: {
    items: [],
    total: 0,
    status: 'idle',
    error: null
  },
  mine: createListView(),
  details: {}
}

interface FetchCatalogArgs {
  page?: number
  pageSize?: number
  keyword?: string
  isHotTopic?: boolean
  append?: boolean
}

export const fetchHotCourses = createAsyncThunk<
  { items: CourseListItem[]; total: number },
  { pageSize?: number } | undefined,
  { rejectValue: string }
>('course/fetchHot', async (args, { rejectWithValue }) => {
  try {
    const response = await getCourses({
      page: 1,
      pageSize: args?.pageSize ?? HOT_COURSE_PAGE_SIZE,
      isHotTopic: true
    })
    return { items: response.items, total: response.total }
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

export const fetchCatalog = createAsyncThunk<
  Awaited<ReturnType<typeof getCourses>>,
  FetchCatalogArgs,
  { rejectValue: string }
>('course/fetchCatalog', async (args, { rejectWithValue }) => {
  try {
    return await getCourses({
      page: args.page ?? 1,
      pageSize: args.pageSize ?? DEFAULT_PAGE_SIZE,
      keyword: args.keyword,
      isHotTopic: args.isHotTopic
    })
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

interface FetchMineArgs {
  page?: number
  pageSize?: number
  append?: boolean
}

export const fetchMyCourses = createAsyncThunk<
  Awaited<ReturnType<typeof getMyCourses>>,
  FetchMineArgs | undefined,
  { rejectValue: string }
>('course/fetchMine', async (args, { rejectWithValue }) => {
  try {
    return await getMyCourses({
      page: args?.page ?? 1,
      pageSize: args?.pageSize ?? DEFAULT_PAGE_SIZE
    })
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

export const fetchCourseDetail = createAsyncThunk<
  CourseDetail,
  number,
  { rejectValue: string }
>('course/fetchDetail', async (courseId, { rejectWithValue }) => {
  try {
    return await getCourseDetail(courseId)
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

function mergeItems(
  current: CourseListItem[],
  incoming: CourseListItem[]
): CourseListItem[] {
  const seen = new Set(current.map((item) => item.id))
  return [...current, ...incoming.filter((item) => !seen.has(item.id))]
}

const courseSlice = createSlice({
  name: 'course',
  initialState,
  reducers: {
    resetCatalog(
      state,
      action: PayloadAction<
        { keyword?: string; isHotTopic?: boolean } | undefined
      >
    ) {
      state.catalog = {
        ...createListView(),
        keyword: action.payload?.keyword?.trim() || '',
        isHotTopic: Boolean(action.payload?.isHotTopic)
      }
    },
    resetCourseData() {
      return {
        catalog: createListView(),
        hot: {
          items: [],
          total: 0,
          status: 'idle' as const,
          error: null
        },
        mine: createListView(),
        details: {}
      }
    }
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchHotCourses.pending, (state) => {
        state.hot.status = 'loading'
        state.hot.error = null
      })
      .addCase(fetchHotCourses.fulfilled, (state, action) => {
        state.hot.items = action.payload.items
        state.hot.total = action.payload.total
        state.hot.status = 'success'
        state.hot.error = null
      })
      .addCase(fetchHotCourses.rejected, (state, action) => {
        state.hot.status = 'error'
        state.hot.error =
          action.payload || action.error.message || '热门课程加载失败'
      })
      .addCase(fetchCatalog.pending, (state, action) => {
        state.catalog.status = 'loading'
        state.catalog.error = null
        state.catalog.keyword = action.meta.arg.keyword?.trim() || ''
        state.catalog.isHotTopic = Boolean(action.meta.arg.isHotTopic)
        state.catalog.pageSize = action.meta.arg.pageSize ?? DEFAULT_PAGE_SIZE
        if (!action.meta.arg.append) {
          state.catalog.items = []
          state.catalog.page = 0
          state.catalog.total = 0
          state.catalog.hasMore = true
        }
      })
      .addCase(fetchCatalog.fulfilled, (state, action) => {
        const append = Boolean(action.meta.arg.append) && action.payload.page > 1
        state.catalog.items = append
          ? mergeItems(state.catalog.items, action.payload.items)
          : action.payload.items
        state.catalog.total = action.payload.total
        state.catalog.page = action.payload.page
        state.catalog.pageSize = action.payload.page_size
        state.catalog.hasMore =
          action.payload.page * action.payload.page_size < action.payload.total
        state.catalog.status = 'success'
        state.catalog.error = null
      })
      .addCase(fetchCatalog.rejected, (state, action) => {
        state.catalog.status = 'error'
        state.catalog.error =
          action.payload || action.error.message || '课程列表加载失败'
      })
      .addCase(fetchMyCourses.pending, (state, action) => {
        state.mine.status = 'loading'
        state.mine.error = null
        state.mine.pageSize = action.meta.arg?.pageSize ?? DEFAULT_PAGE_SIZE
        if (!action.meta.arg?.append) {
          state.mine.items = []
          state.mine.page = 0
          state.mine.total = 0
          state.mine.hasMore = true
        }
      })
      .addCase(fetchMyCourses.fulfilled, (state, action) => {
        const append =
          Boolean(action.meta.arg?.append) && action.payload.page > 1
        state.mine.items = append
          ? mergeItems(state.mine.items, action.payload.items)
          : action.payload.items
        state.mine.total = action.payload.total
        state.mine.page = action.payload.page
        state.mine.pageSize = action.payload.page_size
        state.mine.hasMore =
          action.payload.page * action.payload.page_size < action.payload.total
        state.mine.status = 'success'
        state.mine.error = null
      })
      .addCase(fetchMyCourses.rejected, (state, action) => {
        state.mine.status = 'error'
        state.mine.error =
          action.payload || action.error.message || '我的课程加载失败'
      })
      .addCase(fetchCourseDetail.pending, (state, action) => {
        const key = String(action.meta.arg)
        const entry = state.details[key] || {
          data: null,
          status: 'idle' as const,
          error: null
        }
        state.details[key] = {
          ...entry,
          status: 'loading',
          error: null
        }
      })
      .addCase(fetchCourseDetail.fulfilled, (state, action) => {
        state.details[String(action.payload.id)] = {
          data: action.payload,
          status: 'success',
          error: null
        }
      })
      .addCase(fetchCourseDetail.rejected, (state, action) => {
        const key = String(action.meta.arg)
        const entry = state.details[key] || {
          data: null,
          status: 'idle' as const,
          error: null
        }
        state.details[key] = {
          ...entry,
          status: 'error',
          error: action.payload || action.error.message || '课程详情加载失败'
        }
      })
  }
})

export const { resetCatalog, resetCourseData } = courseSlice.actions

export const selectCatalog = (state: { course: CourseState }): ListViewState =>
  state.course.catalog

export const selectHotCourses = (state: {
  course: CourseState
}): HotViewState => state.course.hot

export const selectMyCourses = (state: { course: CourseState }): ListViewState =>
  state.course.mine

export const selectCourseDetailEntry = (
  state: { course: CourseState },
  courseId: number
): DetailEntry | undefined => state.course.details[String(courseId)]

export default courseSlice.reducer
