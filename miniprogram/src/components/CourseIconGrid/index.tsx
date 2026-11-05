import { Text, View } from '@tarojs/components'

import './index.scss'

export interface CourseIconItem {
  key: string
  label: string
  icon: string
  description?: string
  background?: string
}

interface CourseIconGridProps {
  items: CourseIconItem[]
  onSelect?: (item: CourseIconItem) => void
}

export default function CourseIconGrid({
  items,
  onSelect
}: CourseIconGridProps) {
  if (!items.length) {
    return null
  }

  return (
    <View className='course-icon-grid'>
      {items.map((item) => (
        <View
          key={item.key}
          className='course-icon-grid__item'
          onClick={() => onSelect?.(item)}
        >
          <View
            className='course-icon-grid__icon'
            style={{ background: item.background || '#f3e7d2' }}
          >
            <Text className='course-icon-grid__glyph'>{item.icon}</Text>
          </View>
          <Text className='course-icon-grid__label'>{item.label}</Text>
          {item.description ? (
            <Text className='course-icon-grid__description'>
              {item.description}
            </Text>
          ) : null}
        </View>
      ))}
    </View>
  )
}
