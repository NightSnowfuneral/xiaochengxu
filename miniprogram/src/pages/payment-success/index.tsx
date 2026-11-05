import { useEffect, useRef, useState } from 'react'
import { Button, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'

import MockModeBadge from '../../components/MockModeBadge'
import { DEFAULT_PAGE_SIZE } from '../../constants'
import { useAuthGuard } from '../../hooks/useAuthGuard'
import {
  OrderClosedError,
  OrderPollTimeoutError,
  pollOrderUntilPaid
} from '../../services/orderApi'
import { getErrorMessage } from '../../services/request'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  fetchCourseDetail,
  fetchMyCourses
} from '../../store/slices/courseSlice'
import { parsePositiveInt, safeDecode } from '../../utils/format'
import { ROUTES } from '../../utils/navigation'

import './index.scss'

type PaymentPageState = 'polling' | 'paid' | 'timeout' | 'closed' | 'error'

/**
 * 支付成功页：
 * 1. 轮询 query-order 确认最终支付结果（后端会主动向微信查单）；
 * 2. 确认已支付后停止轮询，刷新课程详情与我的课程；
 * 3. 不在 C 端展示任何课程有效期信息。
 */
export default function PaymentSuccessPage() {
  const router = useRouter()
  const dispatch = useAppDispatch()
  const { checking, allowed } = useAuthGuard()
  const token = useAppSelector((state) => state.user.token)
  const orderNo = (router.params.orderNo || '').trim()
  const courseId = parsePositiveInt(router.params.courseId)
  const courseTitle = safeDecode(router.params.title)
  const [state, setState] = useState<PaymentPageState>('polling')
  const [message, setMessage] = useState('正在与微信确认支付结果…')
  const [retryKey, setRetryKey] = useState(0)
  const mountedRef = useRef(true)
  const pollingRef = useRef(false)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    if (!allowed || !token || !orderNo || pollingRef.current) {
      return
    }

    let cancelled = false
    pollingRef.current = true
    setState('polling')
    setMessage('正在与微信确认支付结果…')

    const run = async () => {
      try {
        const paidOrder = await pollOrderUntilPaid(orderNo, {
          shouldContinue: () => mountedRef.current && !cancelled,
          onStatus: (order) => {
            if (!mountedRef.current || cancelled) {
              return
            }
            if (order.status === 'pending') {
              setMessage('支付结果确认中，请稍候…')
            }
          }
        })

        if (!mountedRef.current || cancelled) {
          return
        }
        setState('paid')
        setMessage('已购买课程，可去学习')
        await Promise.allSettled([
          courseId
            ? dispatch(fetchCourseDetail(courseId)).unwrap()
            : Promise.resolve(),
          dispatch(
            fetchMyCourses({ page: 1, pageSize: DEFAULT_PAGE_SIZE })
          ).unwrap()
        ])
        void paidOrder
      } catch (error) {
        if (!mountedRef.current || cancelled) {
          return
        }
        if (error instanceof OrderClosedError) {
          setState('closed')
          setMessage(error.message)
          return
        }
        if (error instanceof OrderPollTimeoutError) {
          setState('timeout')
          setMessage('支付结果确认中，请稍后在“我的课程”中查看')
          return
        }
        setState('error')
        setMessage(getErrorMessage(error))
      } finally {
        pollingRef.current = false
      }
    }

    void run()
    return () => {
      cancelled = true
    }
  }, [allowed, courseId, dispatch, orderNo, retryKey, token])

  const backToCourse = () => {
    const pages = Taro.getCurrentPages()
    if (pages.length > 1) {
      void Taro.navigateBack()
      return
    }
    if (courseId) {
      void Taro.redirectTo({
        url: `${ROUTES.courseDetail}?id=${courseId}`
      })
    }
  }

  const retry = () => {
    if (pollingRef.current) {
      return
    }
    setRetryKey((value) => value + 1)
  }

  const renderContent = () => {
    if (checking) {
      return (
        <View className='payment-success__card'>
          <View className='payment-success__mark'>
            <Text className='payment-success__mark-text'>…</Text>
          </View>
          <Text className='payment-success__title'>正在确认登录状态</Text>
        </View>
      )
    }

    if (!allowed) {
      return (
        <View className='payment-success__card'>
          <View className='payment-success__mark'>
            <Text className='payment-success__mark-text'>禾</Text>
          </View>
          <Text className='payment-success__title'>登录后查看支付结果</Text>
        </View>
      )
    }

    if (!orderNo) {
      return (
        <View className='payment-success__card'>
          <View className='payment-success__mark'>
            <Text className='payment-success__mark-text'>!</Text>
          </View>
          <Text className='payment-success__title'>订单参数有误</Text>
          <Text className='payment-success__message'>
            请返回课程详情重新发起支付
          </Text>
          <Button className='primary-action' onClick={backToCourse}>
            返回课程
          </Button>
        </View>
      )
    }

    const isPaid = state === 'paid'
    const isPolling = state === 'polling'
    const title =
      state === 'paid'
        ? '支付成功'
        : state === 'closed'
          ? '订单已关闭'
          : state === 'timeout'
            ? '支付结果确认中'
            : state === 'error'
              ? '确认支付结果失败'
              : '正在确认支付结果'

    return (
      <View className='payment-success__card'>
        <View
          className={`payment-success__mark ${
            isPaid ? 'payment-success__mark--paid' : ''
          }`}
        >
          <Text className='payment-success__mark-text'>
            {isPaid ? '✓' : isPolling ? '…' : '!'}
          </Text>
        </View>
        <Text className='payment-success__title'>{title}</Text>
        {courseTitle ? (
          <Text className='payment-success__course'>{courseTitle}</Text>
        ) : null}
        <Text className='payment-success__message'>{message}</Text>
        <Text className='payment-success__order'>订单号 {orderNo}</Text>

        {isPaid ? (
          <>
            <Button className='primary-action' onClick={backToCourse}>
              去学习
            </Button>
            <Button className='ghost-action' onClick={backToCourse}>
              返回课程
            </Button>
          </>
        ) : null}

        {isPolling ? (
          <Button className='primary-action primary-action--disabled' disabled>
            正在确认支付结果…
          </Button>
        ) : null}

        {state === 'timeout' || state === 'error' ? (
          <>
            <Button className='primary-action' onClick={retry}>
              重新确认
            </Button>
            <Button className='ghost-action' onClick={backToCourse}>
              返回课程
            </Button>
          </>
        ) : null}

        {state === 'closed' ? (
          <>
            <Button className='primary-action' onClick={backToCourse}>
              返回课程重新购买
            </Button>
          </>
        ) : null}
      </View>
    )
  }

  return (
    <View className='page payment-success-page'>
      <MockModeBadge />
      <View className='payment-success__hero'>
        <Text className='payment-success__eyebrow'>PAYMENT</Text>
        <Text className='payment-success__hero-title'>购买结果</Text>
      </View>
      <View className='section'>{renderContent()}</View>
    </View>
  )
}
