import { useCallback, useEffect, useRef, useState } from 'react'
import { Image, Text, View } from '@tarojs/components'
import Taro, {
  useDidShow,
  usePullDownRefresh,
  useRouter
} from '@tarojs/taro'

import MockModeBadge from '../../components/MockModeBadge'
import WxAuthSheet from '../../components/WxAuthSheet'
import { useRequireAuth } from '../../hooks/useRequireAuth'
import { useSystemConfig } from '../../hooks/useSystemConfig'
import { getOrderDetail } from '../../services/orderApi'
import { getErrorMessage } from '../../services/request'
import { useAppSelector } from '../../store/hooks'
import type { ClientOrderResponse, OrderStatus } from '../../types'
import { formatOrderTime, formatPrice, safeDecode } from '../../utils/format'
import { goCourseDetailRepurchase } from '../../utils/navigation'

import './index.scss'

const STATUS_LABELS: Record<OrderStatus, string> = {
  pending: '待支付',
  paid: '已支付',
  closed: '已取消'
}

/**
 * 订单详情。
 *
 * 只展示当前用户自己的订单；课程属虚拟商品，待支付订单只能返回课程页
 * 重新购买；已支付 / 已取消仅展示状态，不提供额外操作。
 */
export default function OrderDetailPage() {
  useSystemConfig()
  const router = useRouter()
  const { openLogin } = useRequireAuth()
  const token = useAppSelector((state) => state.user.token)
  const isMockLogin = useAppSelector((state) => state.user.isMockLogin)
  const orderNo = safeDecode(router.params.orderNo)
  const [order, setOrder] = useState<ClientOrderResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const seqRef = useRef(0)
  const shownOnceRef = useRef(false)

  const loadDetail = useCallback(async () => {
    if (!token || isMockLogin || !orderNo) {
      return
    }
    const seq = seqRef.current + 1
    seqRef.current = seq
    setLoading(true)
    setError('')
    try {
      const result = await getOrderDetail(orderNo)
      if (seq !== seqRef.current) {
        return
      }
      setOrder(result)
    } catch (loadError) {
      if (seq !== seqRef.current) {
        return
      }
      setError(getErrorMessage(loadError))
    } finally {
      if (seq === seqRef.current) {
        setLoading(false)
      }
    }
  }, [isMockLogin, orderNo, token])

  useEffect(() => {
    if (!token || isMockLogin) {
      seqRef.current += 1
      setOrder(null)
      setLoading(false)
      setError('')
      return
    }
    void loadDetail()
  }, [isMockLogin, loadDetail, token])

  useDidShow(() => {
    if (!shownOnceRef.current) {
      shownOnceRef.current = true
      return
    }
    if (token && !isMockLogin) {
      void loadDetail()
    }
  })

  usePullDownRefresh(() => {
    const task =
      token && !isMockLogin ? loadDetail() : Promise.resolve()
    void task.finally(() => {
      void Taro.stopPullDownRefresh()
    })
  })

  const renderContent = () => {
    if (!orderNo) {
      return (
        <View className='state-block'>
          <Text>订单号缺失，请返回订单列表重试</Text>
        </View>
      )
    }

    if (!token) {
      return (
        <View className='state-block'>
          <Text>登录后查看订单详情</Text>
          <Text
            className='state-block__action'
            onClick={() => openLogin('登录后查看订单详情')}
          >
            手机号快捷登录
          </Text>
        </View>
      )
    }

    if (isMockLogin) {
      return (
        <View className='order-detail__note'>
          测试模式不会请求真实订单；退出后使用手机号快捷登录即可查看。
        </View>
      )
    }

    if (loading && !order) {
      return <View className='loading-line'>正在加载订单详情…</View>
    }

    if (error && !order) {
      return (
        <View className='state-block'>
          <Text>{error}</Text>
          <Text
            className='state-block__action'
            onClick={() => {
              void loadDetail()
            }}
          >
            重新加载
          </Text>
        </View>
      )
    }

    if (!order) {
      return null
    }

    const pending = order.status === 'pending'

    return (
      <View>
        <View className='order-detail__course'>
          {order.course_cover ? (
            <Image
              className='order-detail__cover'
              src={order.course_cover}
              mode='aspectFill'
            />
          ) : (
            <View className='order-detail__cover order-detail__cover--empty'>
              <Text className='order-detail__cover-text'>禾</Text>
            </View>
          )}
          <View className='order-detail__course-main'>
            <Text className='order-detail__course-title'>
              {order.course_title || '课程订单'}
            </Text>
            <Text
              className={`order-detail__status order-detail__status--${order.status}`}
            >
              {STATUS_LABELS[order.status]}
            </Text>
          </View>
        </View>

        <View className='order-detail__card'>
          <View className='order-detail__row'>
            <Text className='order-detail__label'>订单号</Text>
            <Text className='order-detail__value order-detail__value--mono'>
              {order.order_no}
            </Text>
          </View>
          <View className='order-detail__row'>
            <Text className='order-detail__label'>下单时间</Text>
            <Text className='order-detail__value'>
              {formatOrderTime(order.created_at)}
            </Text>
          </View>
          <View className='order-detail__row'>
            <Text className='order-detail__label'>课程名称</Text>
            <Text className='order-detail__value'>
              {order.course_title || '课程订单'}
            </Text>
          </View>
          <View className='order-detail__row'>
            <Text className='order-detail__label'>订单金额</Text>
            <Text className='order-detail__value order-detail__value--amount'>
              {formatPrice(order.amount)}
            </Text>
          </View>
          <View className='order-detail__row'>
            <Text className='order-detail__label'>订单状态</Text>
            <Text className='order-detail__value'>
              {STATUS_LABELS[order.status]}
            </Text>
          </View>
        </View>

        {pending ? (
          <View>
            <Text className='order-detail__hint'>
              课程属于虚拟商品，只能通过微信「小程序虚拟支付」购买；订单号
              一次有效，需返回课程页重新发起支付。
            </Text>
            <View className='order-detail__actions'>
              <View
                className='order-detail__button order-detail__button--primary'
                onClick={() => {
                  goCourseDetailRepurchase(order.course_id)
                }}
              >
                重新购买
              </View>
            </View>
          </View>
        ) : (
          <Text className='order-detail__hint'>
            {order.status === 'paid'
              ? '订单已完成，课程权益已发放。'
              : '订单已取消，不会发放课程权益。'}
          </Text>
        )}
      </View>
    )
  }

  return (
    <View className='page order-detail-page'>
      <MockModeBadge />

      <View className='order-detail__header section'>
        <Text className='order-detail__eyebrow'>ORDER DETAIL</Text>
        <Text className='order-detail__title'>订单详情</Text>
      </View>

      <View className='section'>{renderContent()}</View>

      <WxAuthSheet />
    </View>
  )
}
