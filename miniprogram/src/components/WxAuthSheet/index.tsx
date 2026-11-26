import { useEffect, useRef, useState } from 'react'
import { Button, Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { MOCK_LOGIN_ENABLED } from '@mock-login'

import { IS_DEV } from '../../config'
import { getErrorMessage } from '../../services/request'
import { useAppSelector } from '../../store/hooks'
import { loginAsMock, loginWithPhone } from '../../utils/auth'
import {
  cancelAuthSheet,
  cancelAuthSheetIfStale,
  completeAuthSheet
} from '../../utils/authGate'
import {
  agreePrivacy,
  disagreePrivacy,
  isPrivacyPending,
  openPrivacyContract,
  subscribePrivacy
} from '../../utils/privacy'

import './index.scss'

const PHONE_DENIED_TIP = '需授权手机号才能完成登录'
const PRIVACY_AGREE_BUTTON_ID = 'auth-sheet-agree-privacy'

/**
 * getPhoneNumber 拿不到 code 时，微信会在 detail 里给出 errMsg / errno。
 * 这些信息不包含手机号或凭证，可以安全展示 / 打印，用于区分：
 * 用户取消、隐私协议未同意、未开通手机号能力、调用超限等。
 */
function describePhoneAuthError(errMsg: string, errno?: number | string) {
  const message = errMsg || ''
  const code = Number(errno)

  if (code === 112 || /api scope is not declared/i.test(message)) {
    return '小程序隐私指引未声明手机号用途，暂时无法登录，请联系客服'
  }
  if (/privacy permission is not authorized|privacy.*not authorized/i.test(message)) {
    return '请先同意《用户隐私保护指引》，再重新点击登录'
  }
  if (/user deny|user cancel|auth deny|platform auth deny/i.test(message)) {
    return '已取消手机号授权，可再次点击登录'
  }
  if (/no permission|jsapi has no permission/i.test(message)) {
    return '小程序暂未开通手机号快捷登录，请联系客服'
  }
  if (/quota|frequency|limit|too many/i.test(message)) {
    return '登录次数过多，请稍后再试'
  }
  if (/not login/i.test(message)) {
    return '微信登录状态异常，请重启小程序后重试'
  }
  return message ? `手机号授权失败（${message}）` : PHONE_DENIED_TIP
}

export default function WxAuthSheet() {
  const visible = useAppSelector((state) => state.authSheet.visible)
  const reason = useAppSelector((state) => state.authSheet.reason)
  const [submitting, setSubmitting] = useState(false)
  const [mockSubmitting, setMockSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [privacyPending, setPrivacyPending] = useState(isPrivacyPending())
  const mountedRef = useRef(true)
  const busy = submitting || mockSubmitting

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    if (visible) {
      setError('')
    } else {
      setSubmitting(false)
      setMockSubmitting(false)
    }
  }, [visible])

  // app 启动时已注册 wx.onNeedPrivacyAuthorization；这里只订阅状态，
  // 避免页面栈中多个 WxAuthSheet 重复注册监听。
  useEffect(() => {
    const sync = () => setPrivacyPending(isPrivacyPending())
    sync()
    return subscribePrivacy(sync)
  }, [])

  useDidShow(() => {
    cancelAuthSheetIfStale()
  })

  if (!visible && !privacyPending) {
    return null
  }

  const handleClose = () => {
    // 提交中禁止关闭，避免登录请求成功后仍执行已中止的动作。
    if (busy) {
      return
    }
    if (privacyPending) {
      disagreePrivacy()
    }
    cancelAuthSheet()
  }

  const handleAgreePrivacy = () => {
    // 必须在 open-type=agreePrivacyAuthorization 按钮的点击回调里 resolve，
    // 微信校验通过后隐私接口才会继续执行。
    agreePrivacy(PRIVACY_AGREE_BUTTON_ID)
  }

  const handleDisagreePrivacy = () => {
    disagreePrivacy()
    setError('需同意隐私保护指引后才能使用手机号登录')
  }

  const handleGetPhoneNumber = async (event: any) => {
    if (busy) {
      return
    }
    const detail = event?.detail ?? {}
    const phoneCode = detail?.code
    if (!phoneCode) {
      // 仅打印微信返回的 errMsg / errno，不含手机号、code、token。
      console.warn('[getPhoneNumber] 未获取到手机号凭证', {
        errMsg: detail?.errMsg || '',
        errno: detail?.errno
      })
      const message = describePhoneAuthError(
        String(detail?.errMsg || ''),
        detail?.errno
      )
      setError(message)
      return
    }

    setError('')
    setSubmitting(true)
    try {
      const loginResult = await Taro.login()
      if (!loginResult.code) {
        throw new Error('登录失败，请重新尝试')
      }
      await loginWithPhone(loginResult.code, phoneCode)
      if (!mountedRef.current) {
        return
      }
      void Taro.showToast({ title: '登录成功', icon: 'none' })
      completeAuthSheet()
    } catch (loginError) {
      if (mountedRef.current) {
        const message = getErrorMessage(loginError)
        setError(message)
        void Taro.showToast({ title: message, icon: 'none' })
      }
    } finally {
      if (mountedRef.current) {
        setSubmitting(false)
      }
    }
  }

  const handleMockLogin = async () => {
    if (busy) {
      return
    }
    setError('')
    setMockSubmitting(true)
    try {
      await loginAsMock()
      if (!mountedRef.current) {
        return
      }
      completeAuthSheet()
    } catch (loginError) {
      if (mountedRef.current) {
        const message = getErrorMessage(loginError)
        setError(message)
        void Taro.showToast({ title: message, icon: 'none' })
      }
    } finally {
      if (mountedRef.current) {
        setMockSubmitting(false)
      }
    }
  }

  return (
    <>
      {visible ? (
        <View className='auth-sheet'>
          <View className='auth-sheet__backdrop' onClick={handleClose} />
          <View className='auth-sheet__panel'>
            <Text className='auth-sheet__close' onClick={handleClose}>
              ×
            </Text>
            <View className='auth-sheet__logo'>
              <Text className='auth-sheet__logo-text'>禾</Text>
            </View>
            <Text className='auth-sheet__title'>手机号快捷登录</Text>
            <Text className='auth-sheet__subtitle'>
              授权手机号，记录你的课程与预约记录
            </Text>
            {reason ? (
              <Text className='auth-sheet__reason'>{reason}</Text>
            ) : null}
            {error ? <Text className='auth-sheet__error'>{error}</Text> : null}
            <Button
              className='auth-sheet__button'
              openType='getPhoneNumber'
              loading={submitting}
              disabled={busy}
              onGetPhoneNumber={handleGetPhoneNumber}
            >
              {submitting ? '登录中…' : '手机号快捷登录'}
            </Button>
            <Text className='auth-sheet__note'>
              手机号仅用于账号识别与课程归属，本小程序不收集明文手机号
            </Text>
            {IS_DEV && MOCK_LOGIN_ENABLED ? (
              <Text
                className='auth-sheet__mock'
                onClick={() => void handleMockLogin()}
              >
                {mockSubmitting ? '模拟登录中…' : '模拟登录（仅开发环境）'}
              </Text>
            ) : null}
          </View>
        </View>
      ) : null}
      {privacyPending ? (
        <View className='privacy-consent'>
          <View className='privacy-consent__panel'>
            <Text className='privacy-consent__title'>用户隐私保护提示</Text>
            <Text className='privacy-consent__content'>
              登录需要使用你的手机号完成账号验证。请阅读并同意
              <Text
                className='privacy-consent__link'
                onClick={openPrivacyContract}
              >
                《用户隐私保护指引》
              </Text>
              后继续。
            </Text>
            <View className='privacy-consent__actions'>
              <Button
                className='privacy-consent__btn privacy-consent__btn--ghost'
                onClick={handleDisagreePrivacy}
              >
                拒绝
              </Button>
              <Button
                id={PRIVACY_AGREE_BUTTON_ID}
                className='privacy-consent__btn privacy-consent__btn--primary'
                openType='agreePrivacyAuthorization'
                onAgreePrivacyAuthorization={handleAgreePrivacy}
              >
                同意并继续
              </Button>
            </View>
          </View>
        </View>
      ) : null}
    </>
  )
}
