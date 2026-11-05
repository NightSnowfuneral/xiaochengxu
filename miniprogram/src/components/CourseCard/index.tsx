import { Image, Text, View } from '@tarojs/components'

import type { CourseListItem } from '../../types'
import { formatPrice } from '../../utils/format'

import './index.scss'

interface CourseCardProps {
  course: CourseListItem
  owned?: boolean
  onTap?: (course: CourseListItem) => void
}

export default function CourseCard({
  course,
  owned = false,
  onTap
}: CourseCardProps) {
  return (
    <View className='course-card' onClick={() => onTap?.(course)}>
      <View className='course-card__cover-wrap'>
        <Image
          className='course-card__cover'
          src={course.cover_small}
          mode='aspectFill'
          lazyLoad
        />
        {owned ? (
          <View className='course-card__badge course-card__badge--owned'>
            <Text>已解锁</Text>
          </View>
        ) : course.is_hot_topic ? (
          <View className='course-card__badge'>
            <Text>热门</Text>
          </View>
        ) : null}
      </View>
      <View className='course-card__content'>
        <Text className='course-card__title'>{course.title}</Text>
        <Text className='course-card__lecturer'>{course.lecturer}</Text>
        <View className='course-card__footer'>
          <Text className='course-card__price'>
            {formatPrice(course.price)}
          </Text>
          <Text className='course-card__enter'>进入课程 →</Text>
        </View>
      </View>
    </View>
  )
}
