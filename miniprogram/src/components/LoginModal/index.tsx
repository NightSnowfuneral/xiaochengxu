import { useEffect, useState } from 'react'
import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { MOCK_LOGIN_ENABLED } from '@mock-login'

import { IS_DEV } from '../../config'
import { DEFAULT_CONFIG_VALUES } from '../../constants'
import { getErrorMessage } from '../../services/request'
import { useAppSelector } from '../../store/hooks'
import {
  bindPhoneWithCode,
  loginAsMock,
  loginWithWeChat
} from '../../utils/auth'
import { closeLoginModal, useLoginModalState } from '../../utils/loginModal'

import './index.scss'

type LoginAction = 'wechat' | 'phone' | 'mock' | null

export default function LoginModal() {
  const modal = useLoginModalState()
  const configuredTitle = useAppSelector(
    (state) => state.config.values.login_modal_title
  )
  const title = configuredTitle || DEFAULT_CONFIG_VALUES.login_modal_title
  const [action, setAction] = useState<LoginAction>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (modal.visible) {
      setAction(null)
      setError(null)
    }
  }, [modal.visible])

  if (!modal.visible) {
    return null
  }

  const busy = action !== null

  const close = () => {
    if (!busy) {
      closeLoginModal()
    }
  }

  const handleWechatLogin = async () => {
    if (busy) {
      return
    }
    setError(null)
    setAction('wechat')
    try {
      await loginWithWeChat()
      closeLoginModal()
      void Taro.showToast({ title: '登录成功', icon: 'success' })
    } catch (loginError) {
      setError(getErrorMessage(loginError))
    } finally {
      setAction(null)
    }
  }

  const handlePhoneNumber = async (event: any) => {
    if (busy) {
      return
    }
    const code = event?.detail?.code
    if (!code) {
      setError('未获取到手机号授权，请在真机微信中重试')
      return
    }
    setError(null)
    setAction('phone')
    try {
      await bindPhoneWithCode(code)
      closeLoginModal()
      void Taro.showToast({ title: '手机号绑定成功', icon: 'success' })
    } catch (bindError) {
      setError(getErrorMessage(bindError))
    } finally {
      setAction(null)
    }
  }

  const handleMockLogin = async () => {
    if (busy) {
      return
    }
    setError(null)
    setAction('mock')
    try {
      await loginAsMock()
      closeLoginModal()
    } catch (mockError) {
      setError(getErrorMessage(mockError))
    } finally {
      setAction(null)
    }
  }

  return (
    <View className='login-modal'>
      <View className='login-modal__backdrop' onClick={close} />
      <View className='login-modal__panel'>
        <Text className='login-modal__close' onClick={close}>
          ×
        </Text>
        <View className='login-modal__brand'>
          <Text className='login-modal__brand-text'>禾下</Text>
        </View>
        <Text className='login-modal__title'>{title}</Text>
        {modal.reason ? (
          <Text className='login-modal__reason'>{modal.reason}</Text>
        ) : null}

        <Button
          className='login-modal__button login-modal__button--primary'
          loading={action === 'wechat'}
          disabled={busy}
          onClick={handleWechatLogin}
        >
          微信一键登录
        </Button>

        <Button
          className='login-modal__button login-modal__button--secondary'
          openType='getPhoneNumber'
          loading={action === 'phone'}
          disabled={busy}
          onGetPhoneNumber={handlePhoneNumber}
        >
          绑定本机手机号
        </Button>

        <Text className='login-modal__note'>
          绑定手机号后才能接收后台赠课；手机号仅由微信授权，本小程序不收集明文。
        </Text>
        <Text className='login-modal__note login-modal__note--device'>
          手机号授权需在真机微信中完成，开发者工具不支持该能力。
        </Text>

        {error ? <Text className='login-modal__error'>{error}</Text> : null}

        {IS_DEV && MOCK_LOGIN_ENABLED ? (
          <Button
            className='login-modal__mock'
            loading={action === 'mock'}
            disabled={busy}
            onClick={handleMockLogin}
          >
            🔧 模拟登录（开发测试）
          </Button>
        ) : null}
      </View>
    </View>
  )
}
