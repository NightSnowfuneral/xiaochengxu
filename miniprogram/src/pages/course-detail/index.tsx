import { useEffect, useRef, useState } from 'react'
import { Button, Image, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'

import LoginModal from '../../components/LoginModal'
import MockModeBadge from '../../components/MockModeBadge'
import PurchaseModal from '../../components/PurchaseModal'
import { useAuthGuard } from '../../hooks/useAuthGuard'
import { useSystemConfig } from '../../hooks/useSystemConfig'
import {
  createOrder,
  isPaymentCancelled,
  requestWeChatPayment
} from '../../services/orderApi'
import { getErrorMessage } from '../../services/request'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  clearOrder,
  orderCreated,
  paymentFailed,
  paymentSucceeded,
  startPayment
} from '../../store/slices/orderSlice'
import {
  fetchCourseDetail,
  selectCourseDetailEntry
} from '../../store/slices/courseSlice'
import type { LessonBrief } from '../../types'
import { formatPrice, parsePositiveInt } from '../../utils/format'
import { openLoginModal } from '../../utils/loginModal'
import { goPlayer, ROUTES } from '../../utils/navigation'

import './index.scss'

export default function CourseDetailPage() {
  const router = useRouter()
  const dispatch = useAppDispatch()
  const config = useSystemConfig()
  const { checking, allowed } = useAuthGuard()
  const courseId = parsePositiveInt(router.params.id)
  const detailEntry = useAppSelector((state) =>
    courseId ? selectCourseDetailEntry(state, courseId) : undefined
  )
  const detail = detailEntry?.data || null
  const order = useAppSelector((state) => state.order)
  const token = useAppSelector((state) => state.user.token)
  const isMockLogin = useAppSelector((state) => state.user.isMockLogin)
  const [purchaseVisible, setPurchaseVisible] = useState(false)
  const mountedRef = useRef(true)
  /** 播放页过期弹窗跳转而来时，仅自动打开一次购买弹窗。 */
  const autoRepurchaseRef = useRef(false)
  const repurchaseRequested = router.params.repurchase === '1'

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    if (allowed && token && courseId) {
      void dispatch(fetchCourseDetail(courseId))
    }
  }, [allowed, courseId, dispatch, token])

  useEffect(() => {
    if (!token) {
      setPurchaseVisible(false)
    }
  }, [token])

  useEffect(() => {
    if (detail?.title) {
      void Taro.setNavigationBarTitle({ title: detail.title })
    }
  }, [detail?.title])

  const retry = () => {
    if (courseId) {
      void dispatch(fetchCourseDetail(courseId))
    }
  }

  const openPurchase = () => {
    if (!token) {
      openLoginModal('登录后即可购买课程')
      return
    }
    dispatch(clearOrder())
    setPurchaseVisible(true)
  }

  useEffect(() => {
    if (!repurchaseRequested || autoRepurchaseRef.current) {
      return
    }
    if (!allowed || !token || !detail) {
      return
    }
    autoRepurchaseRef.current = true
    dispatch(clearOrder())
    setPurchaseVisible(true)
  }, [allowed, detail, dispatch, repurchaseRequested, token])

  const closePurchase = () => {
    if (order.paying) {
      return
    }
    setPurchaseVisible(false)
    dispatch(clearOrder())
  }

  const handleConfirmPurchase = async () => {
    if (!detail || order.paying) {
      return
    }
    if (!token) {
      setPurchaseVisible(false)
      openLoginModal('登录后即可购买课程')
      return
    }

    dispatch(startPayment())
    try {
      const createdOrder = await createOrder(detail.id)
      dispatch(orderCreated(createdOrder))
      await requestWeChatPayment(createdOrder.payment)

      if (!mountedRef.current) {
        return
      }
      // 支付面板关闭即视为用户已完成付款；订单最终状态由支付成功页
      // 轮询 query-order 确认（后端会主动向微信查单作为回调兜底）。
      dispatch(paymentSucceeded())
      setPurchaseVisible(false)
      dispatch(clearOrder())
      void Taro.navigateTo({
        url: `${ROUTES.paymentSuccess}?orderNo=${encodeURIComponent(
          createdOrder.order_no
        )}&courseId=${detail.id}&title=${encodeURIComponent(detail.title)}`
      })
    } catch (error) {
      if (!mountedRef.current) {
        return
      }
      dispatch(
        paymentFailed(
          isPaymentCancelled(error)
            ? '支付已取消，可稍后重新发起'
            : getErrorMessage(error)
        )
      )
    }
  }

  const handleLesson = (lesson: LessonBrief) => {
    if (!detail?.is_owned) {
      void Taro.showToast({
        title: '购买课程后解锁全部课时',
        icon: 'none'
      })
      return
    }
    goPlayer(lesson.id, detail.id, lesson.title)
  }

  const startLearning = () => {
    const firstLesson = detail?.lessons[0]
    if (detail?.is_owned && firstLesson) {
      goPlayer(firstLesson.id, detail.id, firstLesson.title)
    }
  }

  const renderBody = () => {
    if (checking) {
      return <View className='loading-line'>正在确认登录状态…</View>
    }
    if (!allowed) {
      return (
        <View className='section'>
          <View className='state-block'>
            <Text>登录后即可查看课程详情</Text>
            <Text
              className='state-block__action'
              onClick={() => openLoginModal('登录后即可查看课程')}
            >
              去登录
            </Text>
          </View>
        </View>
      )
    }
    if (!courseId) {
      return (
        <View className='section'>
          <View className='state-block'>课程参数有误</View>
        </View>
      )
    }
    if (detailEntry?.status === 'loading' && !detail) {
      return <View className='loading-line'>正在加载课程详情…</View>
    }
    if (!detail) {
      return (
        <View className='section'>
          <View className='state-block'>
            <Text>
              {isMockLogin
                ? '测试模式下课程详情接口可能返回 401'
                : detailEntry?.error || '课程详情加载失败'}
            </Text>
            <Text className='state-block__action' onClick={retry}>
              重新加载
            </Text>
          </View>
        </View>
      )
    }

    return (
      <>
        <View className='course-detail__cover-wrap'>
          <Image
            className='course-detail__cover'
            src={detail.cover_big || detail.cover_small}
            mode='aspectFill'
          />
          <View className='course-detail__cover-shade' />
          <View className='course-detail__cover-content'>
            <View className='course-detail__tags'>
              {detail.is_hot_topic ? (
                <Text className='course-detail__tag'>热门课程</Text>
              ) : null}
              <Text
                className={`course-detail__tag ${
                  detail.is_owned ? 'course-detail__tag--owned' : ''
                }`}
              >
                {detail.is_owned ? '已解锁' : '完整课程'}
              </Text>
            </View>
            <Text className='course-detail__title'>{detail.title}</Text>
            <Text className='course-detail__lecturer'>
              主讲 · {detail.lecturer}
            </Text>
          </View>
        </View>

        <View className='section course-detail__meta-card'>
          <View className='course-detail__price-group'>
            <Text className='course-detail__price-label'>课程价格</Text>
            <Text className='course-detail__price'>
              {formatPrice(detail.price)}
            </Text>
          </View>
          <View className='course-detail__meta-divider' />
          <View className='course-detail__meta-item'>
            <Text className='course-detail__meta-value'>
              {detail.lessons.length}
            </Text>
            <Text className='course-detail__meta-label'>全部课时</Text>
          </View>
          <View className='course-detail__meta-item'>
            <Text className='course-detail__meta-value'>
              {detail.is_owned ? '已解锁' : '购买后'}
            </Text>
            <Text className='course-detail__meta-label'>学习权限</Text>
          </View>
        </View>

        <View className='section course-detail__section'>
          <Text className='section-title'>课程介绍</Text>
          <Text className='course-detail__description'>
            {detail.description}
          </Text>
        </View>

        <View className='section course-detail__section'>
          <View className='section-head'>
            <Text className='section-title'>课程目录</Text>
            <Text className='course-detail__lesson-count'>
              {detail.lessons.length} 课时
            </Text>
          </View>

          {detail.lessons.length ? (
            <View className='course-detail__lessons'>
              {detail.lessons.map((lesson, index) => (
                <View
                  key={lesson.id}
                  className={`course-detail__lesson ${
                    detail.is_owned ? '' : 'course-detail__lesson--locked'
                  }`}
                  onClick={() => handleLesson(lesson)}
                >
                  <Text className='course-detail__lesson-index'>
                    {String(index + 1).padStart(2, '0')}
                  </Text>
                  <Text className='course-detail__lesson-title'>
                    {lesson.title}
                  </Text>
                  <Text className='course-detail__lesson-state'>
                    {detail.is_owned ? '播放 ›' : '🔒 购买后解锁'}
                  </Text>
                </View>
              ))}
            </View>
          ) : (
            <View className='state-block'>课程正在准备中</View>
          )}
        </View>

        <View className='course-detail__footer-spacer' />

        <View className='course-detail__footer'>
          <View className='course-detail__footer-price'>
            {detail.is_owned ? (
              <>
                <Text className='course-detail__footer-label'>已解锁</Text>
                <Text className='course-detail__footer-value'>全部课时</Text>
              </>
            ) : (
              <>
                <Text className='course-detail__footer-label'>课程价格</Text>
                <Text className='course-detail__footer-value'>
                  {formatPrice(detail.price)}
                </Text>
              </>
            )}
          </View>
          {detail.is_owned ? (
            <Button
              className={`course-detail__footer-button ${
                detail.lessons.length
                  ? ''
                  : 'course-detail__footer-button--disabled'
              }`}
              disabled={!detail.lessons.length}
              onClick={startLearning}
            >
              {detail.lessons.length ? '开始学习' : '暂无课时'}
            </Button>
          ) : (
            <Button
              className='course-detail__footer-button'
              onClick={openPurchase}
            >
              {config.buy_btn_text || '立即购买'}
            </Button>
          )}
        </View>
      </>
    )
  }

  return (
    <View className='page course-detail-page'>
      <MockModeBadge />
      {renderBody()}

      <PurchaseModal
        visible={purchaseVisible && Boolean(detail)}
        courseTitle={detail?.title || ''}
        amount={detail?.price || 0}
        paying={order.paying}
        error={order.error}
        onClose={closePurchase}
        onConfirm={() => {
          void handleConfirmPurchase()
        }}
      />

      <LoginModal />
    </View>
  )
}
