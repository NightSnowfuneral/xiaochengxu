import { useEffect, useRef, useState } from 'react'
import { Button, Image, Input, Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'

import CourseCard from '../../components/CourseCard'
import MockModeBadge from '../../components/MockModeBadge'
import WxAuthSheet from '../../components/WxAuthSheet'
import orderWalletIcon from '../../assets/icons/order-wallet.png'
import { useRequireAuth } from '../../hooks/useRequireAuth'
import { useSystemConfig } from '../../hooks/useSystemConfig'
import { getAppointmentOverview } from '../../services/appointmentApi'
import { getErrorMessage } from '../../services/request'
import type { AppointmentOverview } from '../../types'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { fetchMyCourses } from '../../store/slices/courseSlice'
import {
  logout,
  refreshProfile,
  saveAvatar,
  saveNickname
} from '../../utils/auth'
import {
  avatarLetter,
  maskMobile
} from '../../utils/format'
import {
  goAppointment,
  goCourseDetail,
  goCourseList,
  goOrders
} from '../../utils/navigation'

import './index.scss'

export default function ProfilePage() {
  const dispatch = useAppDispatch()
  useSystemConfig()
  const { openLogin } = useRequireAuth()
  const token = useAppSelector((state) => state.user.token)
  const profile = useAppSelector((state) => state.user.profile)
  const isMockLogin = useAppSelector((state) => state.user.isMockLogin)
  const mine = useAppSelector((state) => state.course.mine)
  const [avatarUploading, setAvatarUploading] = useState(false)
  const [editingNickname, setEditingNickname] = useState(false)
  const [nicknameDraft, setNicknameDraft] = useState('')
  const [savingNickname, setSavingNickname] = useState(false)
  const [quotaOverview, setQuotaOverview] =
    useState<AppointmentOverview | null>(null)
  const [quotaLoading, setQuotaLoading] = useState(false)
  const quotaSeq = useRef(0)
  const quotaShownOnce = useRef(false)

  const loadQuotaOverview = async () => {
    if (!token || isMockLogin) {
      quotaSeq.current += 1
      setQuotaOverview(null)
      setQuotaLoading(false)
      return
    }
    const seq = quotaSeq.current + 1
    quotaSeq.current = seq
    setQuotaLoading(true)
    try {
      const overview = await getAppointmentOverview()
      if (seq === quotaSeq.current) {
        setQuotaOverview(overview)
      }
    } catch {
      // 概览失败不阻塞个人中心其他内容，保留上一次成功的数据。
    } finally {
      if (seq === quotaSeq.current) {
        setQuotaLoading(false)
      }
    }
  }

  useEffect(() => {
    if (!token) {
      return
    }
    if (!isMockLogin) {
      void refreshProfile().catch(() => undefined)
      void dispatch(fetchMyCourses({ page: 1, pageSize: 20 }))
    }
  }, [dispatch, isMockLogin, token])

  useEffect(() => {
    void loadQuotaOverview()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, isMockLogin])

  useDidShow(() => {
    // 首次展示由 useEffect 负责，避免进入页面时重复请求两次概览。
    if (!quotaShownOnce.current) {
      quotaShownOnce.current = true
      return
    }
    void loadQuotaOverview()
  })

  const handleChooseAvatar = async (event: any) => {
    const avatarUrl = event?.detail?.avatarUrl
    if (!avatarUrl) {
      return
    }
    setAvatarUploading(true)
    try {
      await saveAvatar(avatarUrl)
      void Taro.showToast({ title: '头像已更新', icon: 'success' })
    } catch (error) {
      void Taro.showToast({
        title: getErrorMessage(error),
        icon: 'none'
      })
    } finally {
      setAvatarUploading(false)
    }
  }

  const startEditNickname = () => {
    setNicknameDraft(profile?.nickname ?? '')
    setEditingNickname(true)
  }

  const cancelEditNickname = () => {
    setEditingNickname(false)
    setNicknameDraft('')
  }

  const handleSaveNickname = async () => {
    if (!nicknameDraft.trim()) {
      void Taro.showToast({ title: '昵称不能为空', icon: 'none' })
      return
    }
    setSavingNickname(true)
    try {
      await saveNickname(nicknameDraft)
      setEditingNickname(false)
      setNicknameDraft('')
      void Taro.showToast({ title: '昵称已更新', icon: 'success' })
    } catch (error) {
      void Taro.showToast({
        title: getErrorMessage(error),
        icon: 'none'
      })
    } finally {
      setSavingNickname(false)
    }
  }

  const handleLogout = async () => {
    const result = await Taro.showModal({
      title: '退出登录',
      content: '退出后将清除本机登录信息，且不会自动重新登录。',
      confirmText: '退出',
      confirmColor: '#a37632'
    })
    if (!result.confirm) {
      return
    }
    // logout 内部会调用后端作废 Token、清理本地缓存并切回首页。
    void Taro.showToast({ title: '已退出登录', icon: 'none' })
    await logout()
  }

  const renderCourses = () => {
    if (isMockLogin) {
      return (
        <View className='profile-inline-note'>
          测试模式不会请求真实课程列表；退出后使用手机号快捷登录即可查看已购课程。
        </View>
      )
    }
    if (mine.status === 'loading' && !mine.items.length) {
      return <View className='loading-line'>正在加载我的课程…</View>
    }
    if (mine.status === 'error' && !mine.items.length) {
      return (
        <View className='state-block'>
          <Text>{mine.error || '我的课程加载失败'}</Text>
          <Text
            className='state-block__action'
            onClick={() => {
              void dispatch(fetchMyCourses({ page: 1, pageSize: 20 }))
            }}
          >
            重新加载
          </Text>
        </View>
      )
    }
    if (!mine.items.length) {
      return (
        <View className='state-block'>
          <Text>还没有已购课程</Text>
          <Text
            className='state-block__action'
            onClick={() => goCourseList()}
          >
            去课程广场
          </Text>
        </View>
      )
    }

    return (
      <View>
        {mine.items.map((course) => (
          <CourseCard
            key={course.id}
            course={course}
            owned
            onTap={() => goCourseDetail(course.id)}
          />
        ))}
        {mine.total > mine.items.length ? (
          <Text
            className='profile-more'
            onClick={() => goCourseList({ mode: 'mine' })}
          >
            查看全部 {mine.total} 门课程 →
          </Text>
        ) : null}
      </View>
    )
  }

  return (
    <View className='page profile-page'>
      <MockModeBadge />

      <View className='profile-hero section'>
        <Text className='profile-hero__eyebrow'>MY SPACE</Text>
        <View className='profile-card'>
          {profile ? (
            <Button
              className='profile-card__avatar profile-card__avatar--picker'
              openType='chooseAvatar'
              disabled={avatarUploading}
              onChooseAvatar={handleChooseAvatar}
            >
              {profile.avatar ? (
                <Image
                  className='profile-card__avatar-image'
                  src={profile.avatar}
                  mode='aspectFill'
                />
              ) : (
                <Text className='profile-card__avatar-text'>
                  {avatarLetter(profile.nickname)}
                </Text>
              )}
              <Text className='profile-card__avatar-badge'>
                {avatarUploading ? '上传中' : '换头像'}
              </Text>
            </Button>
          ) : (
            <View className='profile-card__avatar'>
              <Text className='profile-card__avatar-text'>花</Text>
            </View>
          )}
          <View className='profile-card__main'>
            {editingNickname ? (
              <View className='profile-nickname-editor'>
                <Input
                  className='profile-nickname-editor__input'
                  type='nickname'
                  value={nicknameDraft}
                  maxlength={32}
                  placeholder='点击输入微信昵称'
                  placeholderClass='profile-nickname-editor__placeholder'
                  onInput={(event) => setNicknameDraft(event.detail.value)}
                />
                <View className='profile-nickname-editor__actions'>
                  <Text
                    className='profile-nickname-editor__save'
                    onClick={() => {
                      if (!savingNickname) {
                        void handleSaveNickname()
                      }
                    }}
                  >
                    {savingNickname ? '保存中…' : '保存'}
                  </Text>
                  <Text
                    className='profile-nickname-editor__cancel'
                    onClick={cancelEditNickname}
                  >
                    取消
                  </Text>
                </View>
              </View>
            ) : (
              <Text className='profile-card__name'>
                {profile
                  ? profile.nickname || '微信用户'
                  : token
                    ? '正在同步资料…'
                    : '未登录'}
              </Text>
            )}
            <Text className='profile-card__mobile'>
              {profile
                ? maskMobile(profile.mobile)
                : token
                  ? '正在同步资料…'
                  : '登录查看课程、预约记录'}
            </Text>
            {profile && !editingNickname ? (
              <Text className='profile-card__edit' onClick={startEditNickname}>
                {profile.nickname ? '修改昵称' : '设置微信昵称'}
              </Text>
            ) : null}
          </View>
          {isMockLogin ? (
            <Text className='profile-card__mock'>MOCK</Text>
          ) : null}
        </View>
        {profile && (!profile.nickname || !profile.avatar) ? (
          <Text className='profile-hint profile-hint--profile'>
            点击头像和昵称，使用你的微信资料
          </Text>
        ) : null}

        {!token ? (
          <Button
            className='profile-login-button'
            onClick={() => openLogin('登录后查看个人中心')}
          >
            手机号快捷登录
          </Button>
        ) : (
          <View className='profile-actions'>
            <View className='profile-bound'>
              <Text className='profile-bound__dot'>✓</Text>
              <Text className='profile-bound__text'>手机号已绑定</Text>
            </View>
            <Button
              className='profile-logout-button'
              onClick={() => {
                void handleLogout()
              }}
            >
              退出登录
            </Button>
          </View>
        )}

        <Text className='profile-hint'>
          后台赠课按绑定手机号匹配，同一手机号下的课程与预约次数自动同步。
        </Text>
      </View>

      <View className='section profile-orders-entry'>
        <View className='profile-entry' onClick={() => goOrders()}>
          <Image
            className='profile-entry__badge'
            src={orderWalletIcon}
            mode='aspectFit'
          />
          <View className='profile-entry__main'>
            <Text className='profile-entry__title'>我的订单</Text>
            <Text className='profile-entry__subtitle'>
              课程订单、金额与支付状态
            </Text>
          </View>
          <Text className='profile-entry__arrow'>›</Text>
        </View>
      </View>

      {profile && !isMockLogin ? (
        <View className='section'>
          <View className='profile-appointment'>
            <View className='profile-appointment__main'>
              <Text className='profile-appointment__title'>专项指导</Text>
              <View className='profile-appointment__body'>
                <Text className='profile-appointment__value'>
                  {quotaOverview
                    ? quotaOverview.remaining_total
                    : quotaLoading
                      ? '…'
                      : '--'}
                </Text>
                <Text className='profile-appointment__unit'>次可预约</Text>
              </View>
            </View>
            <View
              className='profile-appointment__button'
              onClick={() => goAppointment()}
            >
              去预约
            </View>
          </View>
        </View>
      ) : null}

      <View className='section profile-courses'>
        <View className='section-head'>
          <Text className='section-title'>我的课程</Text>
          {token ? (
            <Text
              className='section-more'
              onClick={() => goCourseList({ mode: 'mine' })}
            >
              全部
            </Text>
          ) : null}
        </View>

        {!token ? (
          <View className='state-block'>
            <Text>登录后查看你的课程与预约</Text>
            <Text
              className='state-block__action'
              onClick={() => openLogin('登录后查看你的课程与预约')}
            >
              手机号快捷登录
            </Text>
          </View>
        ) : (
          renderCourses()
        )}
      </View>

      <WxAuthSheet />
    </View>
  )
}
