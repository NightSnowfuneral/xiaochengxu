import { Text, View } from '@tarojs/components'

import { useAppSelector } from '../../store/hooks'

import './index.scss'

/** 仅模拟登录会话可见；生产环境不会出现该状态。 */
export default function MockModeBadge() {
  const isMockLogin = useAppSelector((state) => state.user.isMockLogin)

  if (!isMockLogin) {
    return null
  }

  return (
    <View className='mock-mode-badge'>
      <Text className='mock-mode-badge__text'>测试模式</Text>
    </View>
  )
}
