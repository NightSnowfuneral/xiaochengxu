import { useEffect, useState } from 'react'
import { Button, Image, Input, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import CourseCard from '../../components/CourseCard'
import LoginModal from '../../components/LoginModal'
import MockModeBadge from '../../components/MockModeBadge'
import { useSystemConfig } from '../../hooks/useSystemConfig'
import { getErrorMessage } from '../../services/request'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { fetchMyCourses } from '../../store/slices/courseSlice'
import {
  bindPhoneWithCode,
  logout,
  refreshProfile,
  saveAvatar,
  saveNickname
} from '../../utils/auth'
import {
  avatarLetter,
  maskMobile
} from '../../utils/format'
import { openLoginModal } from '../../utils/loginModal'
import {
  goCourseDetail,
  goCourseList
} from '../../utils/navigation'

import './index.scss'

export default function ProfilePage() {
  const dispatch = useAppDispatch()
  useSystemConfig()
  const token = useAppSelector((state) => state.user.token)
  const profile = useAppSelector((state) => state.user.profile)
  const isMockLogin = useAppSelector((state) => state.user.isMockLogin)
  const mine = useAppSelector((state) => state.course.mine)
  const [binding, setBinding] = useState(false)
  const [avatarUploading, setAvatarUploading] = useState(false)
  const [editingNickname, setEditingNickname] = useState(false)
  const [nicknameDraft, setNicknameDraft] = useState('')
  const [savingNickname, setSavingNickname] = useState(false)

  useEffect(() => {
    if (!token) {
      return
    }
    if (!isMockLogin) {
      void refreshProfile().catch(() => undefined)
      void dispatch(fetchMyCourses({ page: 1, pageSize: 20 }))
    }
  }, [dispatch, isMockLogin, token])

  const handleBindPhone = async (event: any) => {
    const code = event?.detail?.code
    if (!code) {
      void Taro.showToast({
        title: '请在真机微信中完成手机号授权',
        icon: 'none'
      })
      return
    }
    setBinding(true)
    try {
      await bindPhoneWithCode(code)
      void Taro.showToast({ title: '手机号绑定成功', icon: 'success' })
    } catch (error) {
      void Taro.showToast({
        title: getErrorMessage(error),
        icon: 'none'
      })
    } finally {
      setBinding(false)
    }
  }

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
    logout()
    void Taro.showToast({ title: '已退出登录', icon: 'none' })
  }

  const renderCourses = () => {
    if (isMockLogin) {
      return (
        <View className='profile-inline-note'>
          测试模式不会请求真实课程列表；退出后使用微信登录即可查看已购课程。
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
                {profile ? profile.nickname || '微信用户' : '尚未登录'}
              </Text>
            )}
            <Text className='profile-card__mobile'>
              {profile ? maskMobile(profile.mobile) : '登录后同步学习课程'}
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

        {!profile ? (
          <Button
            className='profile-login-button'
            onClick={() => openLoginModal('登录后查看个人中心')}
          >
            微信登录
          </Button>
        ) : (
          <View className='profile-actions'>
            {!profile.mobile ? (
              <Button
                className='profile-bind-button'
                openType='getPhoneNumber'
                loading={binding}
                disabled={binding}
                onGetPhoneNumber={handleBindPhone}
              >
                绑定本机手机号
              </Button>
            ) : (
              <View className='profile-bound'>
                <Text className='profile-bound__dot'>✓</Text>
                <Text className='profile-bound__text'>手机号已绑定</Text>
              </View>
            )}
            <Button
              className='profile-logout-button'
              disabled={binding}
              onClick={() => {
                void handleLogout()
              }}
            >
              退出登录
            </Button>
          </View>
        )}

        <Text className='profile-hint'>
          后台赠课仅按已绑定手机号匹配；绑定手机号后才能接收赠课。
        </Text>
        {profile && !isMockLogin && !profile.mobile ? (
          <Text className='profile-hint profile-hint--device'>
            手机号授权需在真机微信中完成。
          </Text>
        ) : null}
      </View>

      <View className='section profile-courses'>
        <View className='section-head'>
          <Text className='section-title'>我的课程</Text>
          {profile ? (
            <Text
              className='section-more'
              onClick={() => goCourseList({ mode: 'mine' })}
            >
              全部
            </Text>
          ) : null}
        </View>

        {!profile ? (
          <View className='state-block'>
            <Text>登录后查看已购买或获赠的课程</Text>
            <Text
              className='state-block__action'
              onClick={() => openLoginModal('登录后查看我的课程')}
            >
              去登录
            </Text>
          </View>
        ) : (
          renderCourses()
        )}
      </View>

      <LoginModal />
    </View>
  )
}
