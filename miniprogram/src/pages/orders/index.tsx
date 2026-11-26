import { useCallback, useEffect, useRef, useState } from 'react'
import { Image, Text, View } from '@tarojs/components'
import Taro, {
  useDidShow,
  usePullDownRefresh,
  useReachBottom
} from '@tarojs/taro'

import MockModeBadge from '../../components/MockModeBadge'
import WxAuthSheet from '../../components/WxAuthSheet'
import { DEFAULT_PAGE_SIZE } from '../../constants'
import { useRequireAuth } from '../../hooks/useRequireAuth'
import { useSystemConfig } from '../../hooks/useSystemConfig'
import { getMyOrders } from '../../services/orderApi'
import { getErrorMessage } from '../../services/request'
import { useAppSelector } from '../../store/hooks'
import type { ClientOrderResponse, OrderStatus } from '../../types'
import { formatOrderTime, formatPrice } from '../../utils/format'
import {
  goCourseDetailRepurchase,
  goCourseList,
  goOrderDetail
} from '../../utils/navigation'

import './index.scss'

type OrderTab = 'all' | OrderStatus

const STATUS_LABELS: Record<OrderStatus, string> = {
  pending: '待支付',
  paid: '已支付',
  closed: '已取消'
}

const TABS: { key: OrderTab; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'pending', label: '待支付' },
  { key: 'paid', label: '已支付' },
  { key: 'closed', label: '已取消' }
]

/**
 * 我的订单（订单中心）。
 *
 * - 支持 全部 / 待支付 / 已支付 / 已取消 筛选；
 * - 课程属虚拟商品，待支付订单只能返回课程页重新购买，不再提供
 *   普通微信支付入口；已支付 / 已取消只展示状态；
 * - 未登录时停留在本页并引导手机号快捷登录，进入页面不自动拉起授权。
 */
export default function OrdersPage() {
  useSystemConfig()
  const { openLogin } = useRequireAuth()
  const token = useAppSelector((state) => state.user.token)
  const isMockLogin = useAppSelector((state) => state.user.isMockLogin)
  const [activeTab, setActiveTab] = useState<OrderTab>('all')
  const [items, setItems] = useState<ClientOrderResponse[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const seqRef = useRef(0)
  const shownOnceRef = useRef(false)

  const loadOrders = useCallback(
    async (targetPage: number, append: boolean) => {
      if (!token || isMockLogin) {
        return
      }
      const seq = seqRef.current + 1
      seqRef.current = seq
      if (append) {
        setLoadingMore(true)
      } else {
        setLoading(true)
        setError('')
      }
      try {
        const result = await getMyOrders({
          page: targetPage,
          pageSize: DEFAULT_PAGE_SIZE,
          status: activeTab === 'all' ? undefined : activeTab
        })
        if (seq !== seqRef.current) {
          return
        }
        setItems((previous) =>
          append ? [...previous, ...result.items] : result.items
        )
        setTotal(result.total)
        setPage(result.page)
      } catch (loadError) {
        if (seq !== seqRef.current) {
          return
        }
        if (append) {
          void Taro.showToast({
            title: getErrorMessage(loadError),
            icon: 'none'
          })
        } else {
          setError(getErrorMessage(loadError))
        }
      } finally {
        if (seq === seqRef.current) {
          setLoading(false)
          setLoadingMore(false)
        }
      }
    },
    [activeTab, isMockLogin, token]
  )

  useEffect(() => {
    if (!token || isMockLogin) {
      seqRef.current += 1
      setItems([])
      setTotal(0)
      setPage(1)
      setLoading(false)
      setLoadingMore(false)
      setError('')
      return
    }
    void loadOrders(1, false)
  }, [isMockLogin, loadOrders, token])

  useDidShow(() => {
    // 首次展示由 useEffect 负责；从支付结果页返回时刷新订单状态。
    if (!shownOnceRef.current) {
      shownOnceRef.current = true
      return
    }
    if (token && !isMockLogin) {
      void loadOrders(1, false)
    }
  })

  usePullDownRefresh(() => {
    const task =
      token && !isMockLogin ? loadOrders(1, false) : Promise.resolve()
    void task.finally(() => {
      void Taro.stopPullDownRefresh()
    })
  })

  useReachBottom(() => {
    if (
      !token ||
      isMockLogin ||
      loading ||
      loadingMore ||
      items.length >= total
    ) {
      return
    }
    void loadOrders(page + 1, true)
  })

  const handleTabChange = (key: OrderTab) => {
    if (key === activeTab) {
      return
    }
    setActiveTab(key)
    setItems([])
    setTotal(0)
    setPage(1)
    setError('')
  }

  const renderCover = (order: ClientOrderResponse) => {
    if (order.course_cover) {
      return (
        <Image
          className='order-card__cover'
          src={order.course_cover}
          mode='aspectFill'
        />
      )
    }
    return (
      <View className='order-card__cover order-card__cover--empty'>
        <Text className='order-card__cover-text'>禾</Text>
      </View>
    )
  }

  const renderOrderCard = (order: ClientOrderResponse) => {
    const pending = order.status === 'pending'
    return (
      <View
        className='order-card'
        key={order.order_no}
        onClick={() => goOrderDetail(order.order_no)}
      >
        <View className='order-card__main'>
          {renderCover(order)}
          <View className='order-card__body'>
            <View className='order-card__head'>
              <Text className='order-card__title'>
                {order.course_title || '课程订单'}
              </Text>
              <Text
                className={`order-card__status order-card__status--${order.status}`}
              >
                {STATUS_LABELS[order.status]}
              </Text>
            </View>
            <Text className='order-card__time'>
              下单时间 {formatOrderTime(order.created_at)}
            </Text>
            <View className='order-card__meta'>
              <Text className='order-card__no'>{order.order_no}</Text>
              <Text className='order-card__amount'>
                {formatPrice(order.amount)}
              </Text>
            </View>
          </View>
        </View>
        {pending ? (
          <View className='order-card__footer'>
            <Text className='order-card__footer-hint'>
              待支付订单需返回课程页重新发起购买
            </Text>
            <View
              className='order-card__action order-card__action--primary'
              onClick={(event) => {
                event.stopPropagation()
                goCourseDetailRepurchase(order.course_id)
              }}
            >
              重新购买
            </View>
          </View>
        ) : null}
      </View>
    )
  }

  const renderEmptyState = () => {
    if (activeTab !== 'all') {
      return (
        <View className='orders-empty'>
          <View className='orders-empty__icon'>
            <Text className='orders-empty__icon-text'>单</Text>
          </View>
          <Text className='orders-empty__title'>没有对应订单</Text>
        </View>
      )
    }
    return (
      <View className='orders-empty'>
        <View className='orders-empty__icon'>
          <Text className='orders-empty__icon-text'>单</Text>
        </View>
        <Text className='orders-empty__title'>暂无订单</Text>
        <Text className='orders-empty__subtitle'>
          选购课程后，订单会显示在这里
        </Text>
        <View
          className='orders-empty__action'
          onClick={() => goCourseList()}
        >
          去课程广场
        </View>
      </View>
    )
  }

  const renderContent = () => {
    if (!token) {
      return (
        <View className='state-block'>
          <Text>登录后查看你的订单</Text>
          <Text
            className='state-block__action'
            onClick={() => openLogin('登录后查看你的订单')}
          >
            手机号快捷登录
          </Text>
        </View>
      )
    }

    if (isMockLogin) {
      return (
        <View className='orders-note'>
          测试模式不会请求真实订单；退出后使用手机号快捷登录即可查看订单。
        </View>
      )
    }

    if (loading && !items.length) {
      return <View className='loading-line'>正在加载订单…</View>
    }

    if (error && !items.length) {
      return (
        <View className='state-block'>
          <Text>{error}</Text>
          <Text
            className='state-block__action'
            onClick={() => {
              void loadOrders(1, false)
            }}
          >
            重新加载
          </Text>
        </View>
      )
    }

    if (!items.length) {
      return renderEmptyState()
    }

    return (
      <View>
        {items.map(renderOrderCard)}
        {loadingMore ? (
          <View className='loading-line'>正在加载更多订单…</View>
        ) : null}
        {!loadingMore && items.length >= total ? (
          <Text className='orders-end'>已展示全部 {total} 笔订单</Text>
        ) : null}
      </View>
    )
  }

  const showTabs = Boolean(token) && !isMockLogin

  return (
    <View className='page orders-page'>
      <MockModeBadge />

      <View className='orders-header section'>
        <Text className='orders-header__eyebrow'>MY ORDERS</Text>
        <Text className='orders-header__title'>我的订单</Text>
        <Text className='orders-header__subtitle'>
          课程购买记录、金额与支付状态
        </Text>
      </View>

      {showTabs ? (
        <View className='orders-tabs section'>
          {TABS.map((tab) => (
            <View
              key={tab.key}
              className={`orders-tabs__item ${
                activeTab === tab.key ? 'orders-tabs__item--active' : ''
              }`}
              onClick={() => handleTabChange(tab.key)}
            >
              {tab.label}
            </View>
          ))}
        </View>
      ) : null}

      <View className='section orders-list'>{renderContent()}</View>

      <WxAuthSheet />
    </View>
  )
}
