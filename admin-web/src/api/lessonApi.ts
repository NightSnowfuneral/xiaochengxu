import type {
  Lesson,
  LessonCreatePayload,
  LessonUpdatePayload,
  MessageResponse
} from '../types'
import { apiDelete, apiGet, apiPost, apiPut } from './request'

export function listAdminLessons(courseId: number): Promise<Lesson[]> {
  return apiGet<Lesson[]>('/admin/lessons', {
    params: { course_id: courseId }
  })
}

export function createAdminLesson(
  payload: LessonCreatePayload
): Promise<Lesson> {
  return apiPost<Lesson>('/admin/lessons', payload)
}

export function updateAdminLesson(
  lessonId: number,
  payload: LessonUpdatePayload
): Promise<Lesson> {
  return apiPut<Lesson>(`/admin/lessons/${lessonId}`, payload)
}

export function deleteAdminLesson(lessonId: number): Promise<MessageResponse> {
  return apiDelete<MessageResponse>(`/admin/lessons/${lessonId}`)
}
