import { useEffect, useRef, useState } from 'react'
import { Button, Image, Text, View } from '@tarojs/components'
import Taro, { useDidShow, useRouter } from '@tarojs/taro'

import MockModeBadge from '../../components/MockModeBadge'
import PurchaseModal from '../../components/PurchaseModal'
import WxAuthSheet from '../../components/WxAuthSheet'
import { useRequireAuth } from '../../hooks/useRequireAuth'
import { useSystemConfig } from '../../hooks/useSystemConfig'
import {
  createVirtualOrder,
  describeVirtualPayError,
  isVirtualPayConfigurationError,
  isVirtualPaySupported,
  requestWeChatVirtualPayment
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
import { goAppointment, goPlayer, ROUTES } from '../../utils/navigation'
import { getVirtualPayPlatform } from '../../utils/platform'

import './index.scss'

export default function CourseDetailPage() {
  const router = useRouter()
  const dispatch = useAppDispatch()
  const config = useSystemConfig()
  const { requireAuth } = useRequireAuth()
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
  const shownOnceRef = useRef(false)
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
    // 课程详情公开只读；登录/登出后重新拉取以刷新 is_owned。
    if (courseId) {
      void dispatch(fetchCourseDetail(courseId))
    }
  }, [courseId, dispatch, token])

  useEffect(() => {
    if (!token) {
      setPurchaseVisible(false)
    }
  }, [token])

  useDidShow(() => {
    // 返回本页时刷新归属状态：后台收回课程后不再显示已解锁。
    if (!shownOnceRef.current) {
      shownOnceRef.current = true
      return
    }
    if (!courseId || !token) {
      return
    }
    void dispatch(fetchCourseDetail(courseId))
  })

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

  /** 打开购买面板前重新拉详情：预赠课程可能刚随登录自动领取，避免重复购买。 */
  const preparePurchase = async () => {
    if (!courseId) {
      return
    }
    try {
      const fresh = await dispatch(fetchCourseDetail(courseId)).unwrap()
      if (fresh.is_owned) {
        void Taro.showToast({ title: '课程已解锁', icon: 'none' })
        return
      }
      // 虚拟商品只能通过「小程序虚拟支付」售卖：没有可用道具映射的
      // 付费课程一律不开放购买，绝不回退普通微信支付。
      if (fresh.price > 0 && !fresh.vpay_product_id) {
        void Taro.showToast({
          title: '该课程暂未开放购买，请稍后再试',
          icon: 'none'
        })
        return
      }
      dispatch(clearOrder())
      setPurchaseVisible(true)
    } catch (error) {
      void Taro.showToast({ title: getErrorMessage(error), icon: 'none' })
    }
  }

  const openPurchase = () => {
    requireAuth(() => preparePurchase(), '登录后即可购买课程')
  }

  /** 归属刷新为已解锁时，关闭未支付的购买面板。 */
  useEffect(() => {
    if (detail?.is_owned && purchaseVisible && !order.paying) {
      setPurchaseVisible(false)
      dispatch(clearOrder())
    }
  }, [detail?.is_owned, dispatch, order.paying, purchaseVisible])

  useEffect(() => {
    if (!repurchaseRequested || autoRepurchaseRef.current) {
      return
    }
    if (!token || !detail) {
      return
    }
    autoRepurchaseRef.current = true
    void preparePurchase()
    // preparePurchase 依赖当前课程与 dispatch，只需在触发条件就绪时执行一次。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail, dispatch, repurchaseRequested, token])

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
      dispatch(clearOrder())
      requireAuth(() => preparePurchase(), '登录后即可购买课程')
      return
    }

    const vpayProductId = detail.vpay_product_id
    if (!vpayProductId) {
      void Taro.showToast({
        title: '该课程暂未开放购买，请稍后再试',
        icon: 'none'
      })
      return
    }

    dispatch(startPayment())
    try {
      // 虚拟商品只能走官方「小程序虚拟支付」；每次购买重新取
      // wx.login code，服务端用完即弃，避免 session_key 过期。
      if (!isVirtualPaySupported()) {
        throw new Error('当前微信版本不支持虚拟支付，请升级微信后重试')
      }
      const loginResult = await Taro.login()
      if (!loginResult.code) {
        throw new Error('微信登录失败，请重试')
      }
      const createdVpayOrder = await createVirtualOrder(
        vpayProductId,
        getVirtualPayPlatform(),
        loginResult.code
      )
      if (createdVpayOrder.course_id !== detail.id) {
        throw new Error('商品信息有误，请返回重试')
      }
      dispatch(orderCreated(createdVpayOrder))
      await requestWeChatVirtualPayment(createdVpayOrder)

      if (!mountedRef.current) {
        return
      }
      // 支付面板成功只代表用户完成付款；课程权限以服务端 xpay 推送
      // 发货为准，支付成功页轮询订单状态确认。
      dispatch(paymentSucceeded())
      setPurchaseVisible(false)
      dispatch(clearOrder())
      void Taro.navigateTo({
        url: `${ROUTES.paymentSuccess}?orderNo=${encodeURIComponent(
          createdVpayOrder.out_trade_no
        )}&courseId=${detail.id}&title=${encodeURIComponent(detail.title)}`
      })
    } catch (error) {
      if (!mountedRef.current) {
        return
      }
      const message = describeVirtualPayError(error)
      dispatch(paymentFailed(message))
      if (isVirtualPayConfigurationError(error)) {
        void Taro.showModal({
          title: '暂时无法支付',
          content: message,
          showCancel: false
        })
      }
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
    // 仅在用户主动点课时时检查登录，进入详情页本身不弹授权。
    requireAuth(
      () => goPlayer(lesson.id, detail.id, lesson.title),
      '登录后即可开始学习'
    )
  }

  const startLearning = () => {
    const firstLesson = detail?.lessons[0]
    if (detail?.is_owned && firstLesson) {
      requireAuth(
        () => goPlayer(firstLesson.id, detail.id, firstLesson.title),
        '登录后即可开始学习'
      )
    }
  }

  const openAppointment = () => {
    requireAuth(goAppointment, '登录后即可预约专项指导')
  }

  const renderBody = () => {
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

        {detail.is_owned && detail.appointment_quota > 0 ? (
          <View className='section'>
            <View
              className='course-detail__quota'
              onClick={openAppointment}
            >
              <View className='course-detail__quota-main'>
                <Text className='course-detail__quota-label'>
                  含专项指导预约
                </Text>
                <Text className='course-detail__quota-value'>
                  {detail.appointment_quota} 次
                </Text>
              </View>
              <Text className='course-detail__quota-action'>去预约 ›</Text>
            </View>
          </View>
        ) : null}

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

      <WxAuthSheet />
    </View>
  )
}
