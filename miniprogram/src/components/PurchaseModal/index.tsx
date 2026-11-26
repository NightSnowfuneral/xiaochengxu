import { Button, Text, View } from '@tarojs/components'

import { formatPrice } from '../../utils/format'

import './index.scss'

interface PurchaseModalProps {
  visible: boolean
  courseTitle: string
  amount: number
  paying: boolean
  error?: string | null
  onClose: () => void
  onConfirm: () => void
}

export default function PurchaseModal({
  visible,
  courseTitle,
  amount,
  paying,
  error,
  onClose,
  onConfirm
}: PurchaseModalProps) {
  if (!visible) {
    return null
  }

  const close = () => {
    if (!paying) {
      onClose()
    }
  }

  return (
    <View className='purchase-modal'>
      <View className='purchase-modal__backdrop' onClick={close} />
      <View className='purchase-modal__panel'>
        <View className='purchase-modal__mark'>
          <Text className='purchase-modal__mark-text'>禾下</Text>
        </View>
        <Text className='purchase-modal__title'>确认购买</Text>
        <Text className='purchase-modal__course'>{courseTitle}</Text>

        <View className='purchase-modal__amount-row'>
          <Text className='purchase-modal__label'>应付金额</Text>
          <Text className='purchase-modal__amount'>{formatPrice(amount)}</Text>
        </View>

        <Text className='purchase-modal__notice'>
          支付成功后解锁本课程全部课时，课时不支持单独购买。
        </Text>

        {error ? (
          <Text className='purchase-modal__error'>{error}</Text>
        ) : null}

        <Button
          className={`purchase-modal__confirm ${
            paying ? 'purchase-modal__confirm--disabled' : ''
          }`}
          disabled={paying}
          onClick={onConfirm}
        >
          {paying ? '正在确认支付结果…' : `确认支付 ${formatPrice(amount)}`}
        </Button>
        <Button
          className='purchase-modal__cancel'
          disabled={paying}
          onClick={close}
        >
          暂不购买
        </Button>
      </View>
    </View>
  )
}
