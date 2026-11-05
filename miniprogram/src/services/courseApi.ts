import { FINISH_LESSON_URL } from '../config'
import type {
  CourseDetail,
  CourseListItem,
  PageResponse,
  PlaybackAuthResponse
} from '../types'
import type {
  FinishLessonRequest,
  FinishLessonResponse
} from '../types/vod'
import { request } from './request'

export interface CourseListParams {
  page?: number
  pageSize?: number
  keyword?: string
  isHotTopic?: boolean
}

function buildListQuery(params: CourseListParams): Record<string, unknown> {
  const query: Record<string, unknown> = {
    page: params.page,
    page_size: params.pageSize
  }
  const keyword = params.keyword?.trim()
  if (keyword) {
    query.keyword = keyword
  }
  if (typeof params.isHotTopic === 'boolean') {
    query.is_hot_topic = params.isHotTopic
  }
  return query
}

export function getCourses(
  params: CourseListParams = {}
): Promise<PageResponse<CourseListItem>> {
  return request<PageResponse<CourseListItem>>({
    url: '/client/courses',
    method: 'GET',
    params: buildListQuery(params)
  })
}

export function getMyCourses(
  params: Pick<CourseListParams, 'page' | 'pageSize'> = {}
): Promise<PageResponse<CourseListItem>> {
  return request<PageResponse<CourseListItem>>({
    url: '/client/courses/mine',
    method: 'GET',
    params: {
      page: params.page,
      page_size: params.pageSize
    }
  })
}

export function getCourseDetail(courseId: number): Promise<CourseDetail> {
  return request<CourseDetail>({
    url: `/client/courses/${courseId}`,
    method: 'GET'
  })
}

export function getPlaybackAuth(
  lessonId: number
): Promise<PlaybackAuthResponse> {
  return request<PlaybackAuthResponse>({
    url: `/client/lessons/${lessonId}/play-auth`,
    method: 'GET'
  })
}

/** 每 15 秒上报一次；后端先写 Redis 缓冲，再由定时任务批量落库。 */
export function reportProgress(
  lessonId: number,
  currentTime: number
): Promise<void> {
  return request<void>({
    url: '/client/study/progress',
    method: 'POST',
    data: {
      lesson_id: lessonId,
      current_time: Math.max(0, Math.floor(currentTime))
    }
  })
}

/**
 * 播放结束后标记课时已看完。
 *
 * 接口按产品约定固定为 `/api/vod/finish-lesson`（不带 /v1），因此使用
 * 绝对地址，request() 会跳过 baseURL；服务端会再次校验课程归属，且
 * 接口幂等，重复调用不会改写首次完成时间。
 */
export function finishLesson(
  lessonId: number
): Promise<FinishLessonResponse> {
  const data: FinishLessonRequest = {
    lesson_id: lessonId
  }
  return request<FinishLessonResponse>({
    url: FINISH_LESSON_URL,
    method: 'POST',
    data
  })
}
