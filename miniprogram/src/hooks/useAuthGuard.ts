import { useEffect, useRef, useState } from 'react'
import { useDidShow } from '@tarojs/taro'

import { useAppSelector } from '../store/hooks'
import { ensureAuthenticated } from '../utils/auth'
import { openLoginModal } from '../utils/loginModal'

export interface AuthGuardState {
  checking: boolean
  allowed: boolean
}

/**
 * 需要在 onShow 时校验登录状态的页面使用。
 * 未登录时打开统一 LoginModal；登录成功后无需刷新页面即可解锁内容。
 */
export function useAuthGuard(): AuthGuardState {
  const token = useAppSelector((state) => state.user.token)
  const [checking, setChecking] = useState(true)
  const [allowed, setAllowed] = useState(false)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    if (token) {
      setAllowed(true)
      setChecking(false)
    } else {
      setAllowed(false)
    }
  }, [token])

  useDidShow(() => {
    if (token) {
      setAllowed(true)
      setChecking(false)
      return
    }

    setChecking(true)
    void ensureAuthenticated()
      .then((authenticated) => {
        if (!mountedRef.current) {
          return
        }
        setAllowed(authenticated)
        setChecking(false)
        if (!authenticated) {
          openLoginModal('登录后即可继续')
        }
      })
      .catch(() => {
        if (!mountedRef.current) {
          return
        }
        setAllowed(false)
        setChecking(false)
        openLoginModal('登录后即可继续')
      })
  })

  return { checking, allowed }
}
