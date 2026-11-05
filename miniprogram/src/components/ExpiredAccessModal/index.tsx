import { Button, Text, View } from '@tarojs/components'

import './index.scss'

interface ExpiredAccessModalProps {
  visible: boolean
  onRepurchase: () => void
  onBackToCatalog: () => void
}

/**
 * 观看权限过期拦截弹窗。
 *
 * 只在播放鉴权返回 COURSE_ACCESS_EXPIRED 时展示；点击遮罩不关闭，
 * 必须选择重新购买或返回课程目录。
 */
export default function ExpiredAccessModal({
  visible,
  onRepurchase,
  onBackToCatalog
}: ExpiredAccessModalProps) {
  if (!visible) {
    return null
  }

  return (
    <View className='expired-modal'>
      <View className='expired-modal__backdrop' />
      <View className='expired-modal__panel'>
        <Text className='expired-modal__title'>观看权限已过期</Text>
        <Text className='expired-modal__description'>
          该课程观看权限已过期，视频暂无法观看，可重新购买继续学习
        </Text>
        <Button
          className='expired-modal__button expired-modal__button--primary'
          onClick={onRepurchase}
        >
          重新购买
        </Button>
        <Button
          className='expired-modal__button expired-modal__button--secondary'
          onClick={onBackToCatalog}
        >
          返回课程目录
        </Button>
      </View>
    </View>
  )
}
