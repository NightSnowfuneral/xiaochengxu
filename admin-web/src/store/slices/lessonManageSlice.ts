import { createAsyncThunk, createSlice } from '@reduxjs/toolkit'

import {
  createAdminLesson,
  deleteAdminLesson,
  listAdminLessons,
  updateAdminLesson
} from '../../api/lessonApi'
import { getErrorMessage } from '../../api/request'
import type {
  Lesson,
  LessonCreatePayload,
  LessonUpdatePayload,
  MessageResponse
} from '../../types'

/** 与后端列表、C 端课程详情一致：先按 sort_order，再按 id 升序。 */
function sortLessons(lessons: Lesson[]): Lesson[] {
  return [...lessons].sort(
    (left, right) => left.sort_order - right.sort_order || left.id - right.id
  )
}

export interface LessonManageState {
  items: Lesson[]
  courseId: number | null
  loading: boolean
  error: string | null
  saving: boolean
  deletingId: number | null
}

const initialState: LessonManageState = {
  items: [],
  courseId: null,
  loading: false,
  error: null,
  saving: false,
  deletingId: null
}

export const fetchLessons = createAsyncThunk<
  Lesson[],
  number,
  { rejectValue: string }
>('lessonManage/fetch', async (courseId, { rejectWithValue }) => {
  try {
    return await listAdminLessons(courseId)
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

export const createLesson = createAsyncThunk<
  Lesson,
  LessonCreatePayload,
  { rejectValue: string }
>('lessonManage/create', async (payload, { rejectWithValue }) => {
  try {
    return await createAdminLesson(payload)
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

export const updateLesson = createAsyncThunk<
  Lesson,
  { id: number; payload: LessonUpdatePayload },
  { rejectValue: string }
>('lessonManage/update', async ({ id, payload }, { rejectWithValue }) => {
  try {
    return await updateAdminLesson(id, payload)
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

export const deleteLesson = createAsyncThunk<
  MessageResponse,
  number,
  { rejectValue: string }
>('lessonManage/delete', async (lessonId, { rejectWithValue }) => {
  try {
    return await deleteAdminLesson(lessonId)
  } catch (error) {
    return rejectWithValue(getErrorMessage(error))
  }
})

const lessonManageSlice = createSlice({
  name: 'lessonManage',
  initialState,
  reducers: {
    clearLessons(state) {
      state.items = []
      state.courseId = null
      state.loading = false
      state.error = null
      state.deletingId = null
    }
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchLessons.pending, (state, action) => {
        if (state.courseId !== action.meta.arg) {
          state.items = []
        }
        state.courseId = action.meta.arg
        state.loading = true
        state.error = null
      })
      .addCase(fetchLessons.fulfilled, (state, action) => {
        if (state.courseId !== action.meta.arg) {
          return
        }
        state.loading = false
        state.items = sortLessons(action.payload)
      })
      .addCase(fetchLessons.rejected, (state, action) => {
        if (state.courseId !== action.meta.arg) {
          return
        }
        state.loading = false
        state.error =
          action.payload || action.error.message || '课时列表加载失败'
      })
      .addCase(createLesson.pending, (state) => {
        state.saving = true
      })
      .addCase(createLesson.fulfilled, (state, action) => {
        state.saving = false
        if (state.courseId === action.payload.course_id) {
          state.items = sortLessons([...state.items, action.payload])
        }
      })
      .addCase(createLesson.rejected, (state) => {
        state.saving = false
      })
      .addCase(updateLesson.pending, (state) => {
        state.saving = true
      })
      .addCase(updateLesson.fulfilled, (state, action) => {
        state.saving = false
        state.items = sortLessons(
          state.items.map((lesson) =>
            lesson.id === action.payload.id ? action.payload : lesson
          )
        )
      })
      .addCase(updateLesson.rejected, (state) => {
        state.saving = false
      })
      .addCase(deleteLesson.pending, (state, action) => {
        state.deletingId = action.meta.arg
      })
      .addCase(deleteLesson.fulfilled, (state, action) => {
        state.deletingId = null
        state.items = state.items.filter(
          (lesson) => lesson.id !== action.meta.arg
        )
      })
      .addCase(deleteLesson.rejected, (state) => {
        state.deletingId = null
      })
  }
})

export const { clearLessons } = lessonManageSlice.actions

export const selectLessonManage = (state: {
  lessonManage: LessonManageState
}): LessonManageState => state.lessonManage

export default lessonManageSlice.reducer
