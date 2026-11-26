import { useCallback } from 'react'

import { useAppSelector } from '../store/hooks'
import { openLogin, requestAuth } from '../utils/authGate'

type AuthAction = () => void | Promise<void>

/**
 * 惰性登录入口。
 *
 * requireAuth(action)：需要身份的动作，未登录时先打开弹窗，成功后自动执行；
 * openLogin()：只要求登录并停留在当前页，页面通过 token 变化自行刷新。
 *
 * 约束：只能在用户主动点击事件中调用，禁止在 onLoad / onShow / useEffect
 * 等页面加载或渲染生命周期里自动调用，避免进入页面就强制授权。
 */
export function useRequireAuth() {
  const isLoggedIn = useAppSelector((state) => Boolean(state.user.token))

  const requireAuth = useCallback(
    (action: AuthAction, reason?: string) => requestAuth(action, reason),
    []
  )

  const login = useCallback((reason?: string) => {
    openLogin(reason)
  }, [])

  return { isLoggedIn, requireAuth, openLogin: login }
}
