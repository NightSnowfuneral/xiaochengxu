import Taro from '@tarojs/taro'

export const ROUTES = {
  home: '/pages/home/index',
  academy: '/pages/academy/index',
  courseList: '/pages/course-list/index',
  courseDetail: '/pages/course-detail/index',
  player: '/pages/player/index',
  profile: '/pages/profile/index',
  paymentSuccess: '/pages/payment-success/index'
} as const

export function goAcademy(): void {
  void Taro.switchTab({ url: ROUTES.academy })
}

export function goHome(): void {
  void Taro.switchTab({ url: ROUTES.home })
}

export interface CourseListRouteOptions {
  mode?: 'all' | 'hot' | 'mine'
  keyword?: string
}

export function goCourseList(options: CourseListRouteOptions = {}): void {
  const params: string[] = []
  if (options.mode && options.mode !== 'all') {
    params.push(`mode=${encodeURIComponent(options.mode)}`)
  }
  if (options.keyword?.trim()) {
    params.push(`keyword=${encodeURIComponent(options.keyword.trim())}`)
  }
  const query = params.length ? `?${params.join('&')}` : ''
  void Taro.navigateTo({ url: `${ROUTES.courseList}${query}` })
}

export function goCourseDetail(courseId: number): void {
  void Taro.navigateTo({
    url: `${ROUTES.courseDetail}?id=${courseId}`
  })
}

export function goPlayer(
  lessonId: number,
  courseId: number,
  title: string
): void {
  void Taro.navigateTo({
    url: `${ROUTES.player}?lessonId=${lessonId}&courseId=${courseId}&title=${encodeURIComponent(
      title
    )}`
  })
}

export function goProfile(): void {
  void Taro.navigateTo({ url: ROUTES.profile })
}
