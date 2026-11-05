import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { App as AntdApp, ConfigProvider, type ThemeConfig } from 'antd'
import zhCN from 'antd/locale/zh_CN'

import AppRoutes from './router/AppRoutes'
import { useAppDispatch } from './store/hooks'
import {
  adminSessionInvalidated,
  adminSessionRestored
} from './store/slices/adminAuthSlice'
import {
  ADMIN_SESSION_EXPIRED_EVENT,
  ADMIN_SESSION_STORAGE_KEY,
  readAdminSession
} from './utils/session'

/** 全局主题：品牌金色 + 暖米色底 + 深色侧栏。 */
const theme: ThemeConfig = {
  token: {
    colorPrimary: '#a47436',
    colorSuccess: '#22c55e',
    colorWarning: '#f59e0b',
    colorError: '#ef4444',
    colorInfo: '#0ea5e9',
    borderRadius: 8,
    colorBgLayout: '#f4f1ea',
    colorLink: '#a47436',
    fontFamily:
      "'PingFang SC', 'Microsoft YaHei', 'Noto Sans SC', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
  },
  components: {
    Layout: {
      bodyBg: '#f4f1ea',
      headerBg: 'rgba(255, 255, 255, 0.88)',
      headerHeight: 64,
      headerPadding: '0 24px',
      siderBg: '#0d1526'
    },
    Menu: {
      darkItemBg: '#0d1526',
      darkSubMenuItemBg: '#0d1526',
      darkPopupBg: '#0d1526',
      darkItemColor: 'rgba(255, 255, 255, 0.68)',
      darkItemSelectedColor: '#ffffff',
      darkItemSelectedBg: 'rgba(255, 255, 255, 0.1)',
      darkItemHoverBg: 'rgba(255, 255, 255, 0.06)',
      darkGroupTitleColor: 'rgba(255, 255, 255, 0.4)',
      itemBorderRadius: 8,
      itemMarginInline: 12
    },
    Card: {
      borderRadiusLG: 12
    },
    Table: {
      headerBg: '#faf8f4',
      headerColor: '#57534e',
      rowHoverBg: '#fbf7ef'
    }
  }
}

/** 同步请求层 401、令牌自然过期和跨标签页登录/退出产生的会话变化。 */
function AuthSessionEvents() {
  const dispatch = useAppDispatch()
  const navigate = useNavigate()

  useEffect(() => {
    const handleExpired = (event: Event) => {
      const message =
        event instanceof CustomEvent && typeof event.detail === 'string'
          ? event.detail
          : '登录状态已过期，请重新登录'
      dispatch(adminSessionInvalidated(message))
      navigate('/login', { replace: true, state: { reason: message } })
    }

    const handleStorage = (event: StorageEvent) => {
      if (event.key !== ADMIN_SESSION_STORAGE_KEY) {
        return
      }

      if (event.newValue) {
        const session = readAdminSession()
        if (session) {
          dispatch(adminSessionRestored(session))
        }
        return
      }

      const message = '登录状态已退出，请重新登录'
      dispatch(adminSessionInvalidated(message))
      navigate('/login', { replace: true, state: { reason: message } })
    }

    window.addEventListener(ADMIN_SESSION_EXPIRED_EVENT, handleExpired)
    window.addEventListener('storage', handleStorage)
    return () => {
      window.removeEventListener(ADMIN_SESSION_EXPIRED_EVENT, handleExpired)
      window.removeEventListener('storage', handleStorage)
    }
  }, [dispatch, navigate])

  return null
}

export default function App() {
  return (
    <ConfigProvider locale={zhCN} theme={theme}>
      <AntdApp message={{ duration: 3.2, maxCount: 3 }}>
        <AuthSessionEvents />
        <AppRoutes />
      </AntdApp>
    </ConfigProvider>
  )
}
