import { createAsyncThunk, createSlice } from '@reduxjs/toolkit'

import {
  changeAdminCourseStatus,
  createAdminCourse,
  deleteAdminCourse,
  listAdminCourses,
  updateAdminCourse
} from '../../api/courseApi'
import { getErrorMessage } from '../../api/request'
import type {
  Course,
  CourseCreatePayload,
  CourseStatus,
  CourseUpdatePayload,
  MessageResponse,
  PageResponse
} from '../../types'

export interface FetchCoursesArgs {
  page?: number
  pageSize?: number
  keyword?: string
  hotOnly?: boolean
  status?: CourseStatus
}

export interface CourseManageState {
  items: Course[]
  total: number
  page: number
  pageSize: number
  keyword: string
  hotOnly: boolean
  statusFilter: CourseStatus | 'all'
  loading: boolean
  error: string | null
  saving: boolean
  deletingId: number | null
  statusChangingId: number | null
}

const initialState: CourseManageState = {
  items: [],
  total: 0,
  page: 1,
  pageSize: 20,
  keyword: '',
  hotOnly: false,
  statusFilter: 'all',
  loading: false,
  error: null,
  saving: false,
  deletingId: null,
  statusChangingId: null
}

export const fetchCourses = createAsyncThunk<
  PageResponse<Course>,
  FetchCoursesArgs,
  { rejectValue: string }
>('courseManage/fetch', async (args, { rejectWithValue }) => {
  try {
    return await listAdminCourses({
      page: args.page,
      page_size: args.pageSize,
      keyword: args.keyword?.trim() || undefined,
      is_hot_topic: args.hotOnly ? true : undefined,
      status: args.status
    })
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

export const createCourse = createAsyncThunk<
  Course,
  CourseCreatePayload,
  { rejectValue: string }
>('courseManage/create', async (payload, { rejectWithValue }) => {
  try {
    return await createAdminCourse(payload)
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

export const updateCourse = createAsyncThunk<
  Course,
  { id: number; payload: CourseUpdatePayload },
  { rejectValue: string }
>('courseManage/update', async ({ id, payload }, { rejectWithValue }) => {
  try {
    return await updateAdminCourse(id, payload)
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

export const deleteCourse = createAsyncThunk<
  MessageResponse,
  number,
  { rejectValue: string }
>('courseManage/delete', async (courseId, { rejectWithValue }) => {
  try {
    return await deleteAdminCourse(courseId)
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

export const changeCourseStatus = createAsyncThunk<
  Course,
  { id: number; status: CourseStatus },
  { rejectValue: string }
>('courseManage/changeStatus', async ({ id, status }, { rejectWithValue }) => {
  try {
    return await changeAdminCourseStatus(id, status)
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

const courseManageSlice = createSlice({
  name: 'courseManage',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchCourses.pending, (state) => {
        state.loading = true
        state.error = null
      })
      .addCase(fetchCourses.fulfilled, (state, action) => {
        state.loading = false
        state.items = action.payload.items
        state.total = action.payload.total
        state.page = action.payload.page
        state.pageSize = action.payload.page_size
        state.keyword = action.meta.arg.keyword?.trim() ?? ''
        state.hotOnly = Boolean(action.meta.arg.hotOnly)
        state.statusFilter = action.meta.arg.status ?? 'all'
      })
      .addCase(fetchCourses.rejected, (state, action) => {
        state.loading = false
        state.error =
          action.payload || action.error.message || '课程列表加载失败'
      })
      .addCase(createCourse.pending, (state) => {
        state.saving = true
      })
      .addCase(createCourse.fulfilled, (state) => {
        state.saving = false
      })
      .addCase(createCourse.rejected, (state) => {
        state.saving = false
      })
      .addCase(updateCourse.pending, (state) => {
        state.saving = true
      })
      .addCase(updateCourse.fulfilled, (state) => {
        state.saving = false
      })
      .addCase(updateCourse.rejected, (state) => {
        state.saving = false
      })
      .addCase(deleteCourse.pending, (state, action) => {
        state.deletingId = action.meta.arg
      })
      .addCase(deleteCourse.fulfilled, (state) => {
        state.deletingId = null
      })
      .addCase(deleteCourse.rejected, (state) => {
        state.deletingId = null
      })
      .addCase(changeCourseStatus.pending, (state, action) => {
        state.statusChangingId = action.meta.arg.id
      })
      .addCase(changeCourseStatus.fulfilled, (state, action) => {
        state.statusChangingId = null
        state.items = state.items.map((course) =>
          course.id === action.payload.id ? action.payload : course
        )
      })
      .addCase(changeCourseStatus.rejected, (state) => {
        state.statusChangingId = null
      })
  }
})

export const selectCourseManage = (state: {
  courseManage: CourseManageState
}): CourseManageState => state.courseManage

export default courseManageSlice.reducer
