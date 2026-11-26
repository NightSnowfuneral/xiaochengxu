import { Text, View } from '@tarojs/components'

import './index.scss'

interface LoadingSpinProps {
  /** 转圈下方的提示文案，默认「视频正在加载…」。 */
  tip?: string
  /** 横屏全屏时使用更紧凑的尺寸。 */
  compact?: boolean
}

/**
 * 参考 antd Spin 的四点加载指示器。
 * 视频起播 / 缓冲期间统一使用，避免只有一行文字、用户不知道是否卡住。
 */
export default function LoadingSpin({
  tip = '视频正在加载…',
  compact = false
}: LoadingSpinProps) {
  return (
    <View
      className={compact ? 'loading-spin loading-spin--compact' : 'loading-spin'}
    >
      <View className='loading-spin__indicator'>
        <View className='loading-spin__dot loading-spin__dot--1' />
        <View className='loading-spin__dot loading-spin__dot--2' />
        <View className='loading-spin__dot loading-spin__dot--3' />
        <View className='loading-spin__dot loading-spin__dot--4' />
      </View>
      <Text className='loading-spin__tip'>{tip}</Text>
    </View>
  )
}
