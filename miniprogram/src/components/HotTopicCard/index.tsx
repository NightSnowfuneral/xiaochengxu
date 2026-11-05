import { Image, Text, View } from '@tarojs/components'

import type { CourseListItem } from '../../types'
import { formatPrice } from '../../utils/format'

import './index.scss'

interface HotTopicCardProps {
  course: CourseListItem
  onTap?: (course: CourseListItem) => void
}

export default function HotTopicCard({
  course,
  onTap
}: HotTopicCardProps) {
  const browseLabel =
    typeof course.view_count === 'number'
      ? `${course.view_count} 次浏览`
      : '热门推荐'

  return (
    <View className='hot-topic-card' onClick={() => onTap?.(course)}>
      <View className='hot-topic-card__cover-wrap'>
        <Image
          className='hot-topic-card__cover'
          src={course.cover_small}
          mode='aspectFill'
          lazyLoad
        />
        <View className='hot-topic-card__flag'>
          <Text>HOT</Text>
        </View>
      </View>
      <View className='hot-topic-card__body'>
        <Text className='hot-topic-card__title'>{course.title}</Text>
        <Text className='hot-topic-card__meta'>
          {course.lecturer} · {browseLabel}
        </Text>
        <View className='hot-topic-card__footer'>
          <Text className='hot-topic-card__price'>
            {formatPrice(course.price)}
          </Text>
          <Text className='hot-topic-card__link'>查看课程</Text>
        </View>
      </View>
    </View>
  )
}
