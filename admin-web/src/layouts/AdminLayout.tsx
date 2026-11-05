import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  App as AntdApp,
  Avatar,
  Breadcrumb,
  Button,
  Drawer,
  Dropdown,
  Flex,
  Grid,
  Layout,
  Menu,
  Typography
} from 'antd'
import type { MenuProps } from 'antd'
import {
  BookOutlined,
  FileTextOutlined,
  GiftOutlined,
  LogoutOutlined,
  MenuOutlined,
  PlaySquareOutlined,
  SettingOutlined,
  TeamOutlined,
  UserOutlined,
  VideoCameraOutlined
} from '@ant-design/icons'

import { useAppDispatch, useAppSelector } from '../store/hooks'
import { logoutAdmin, selectAdminAuth } from '../store/slices/adminAuthSlice'

const { Sider, Header, Content, Footer } = Layout

interface AdminNavItem {
  key: string
  label: string
  icon: ReactNode
}

interface AdminNavGroup {
  key: string
  label: string
  children: AdminNavItem[]
}

/** 侧边导航分组固定：兼容页 /user-courses 不进入导航。 */
export const ADMIN_NAV_GROUPS: AdminNavGroup[] = [
  {
    key: 'operations',
    label: '运营管理',
    children: [
      { key: '/courses', label: '课程管理', icon: <BookOutlined /> },
      { key: '/lessons', label: '课时管理', icon: <PlaySquareOutlined /> },
      { key: '/media', label: '媒资管理', icon: <VideoCameraOutlined /> },
      { key: '/gifts', label: '赠课管理', icon: <GiftOutlined /> },
      { key: '/user-course', label: '用户课程管理', icon: <TeamOutlined /> }
    ]
  },
  {
    key: 'business',
    label: '交易与系统',
    children: [
      { key: '/orders', label: '订单查询', icon: <FileTextOutlined /> },
      { key: '/config', label: '系统配置', icon: <SettingOutlined /> }
    ]
  }
]

const ROUTE_LABELS: Record<string, string> = {
  '/courses': '课程管理',
  '/lessons': '课时管理',
  '/media': '媒资管理',
  '/gifts': '赠课管理',
  '/user-course': '用户课程管理',
  '/user-courses': '用户课程（兼容只读）',
  '/orders': '订单查询',
  '/config': '系统配置'
}

const MENU_ITEMS: MenuProps['items'] = ADMIN_NAV_GROUPS.map((group) => ({
  key: group.key,
  type: 'group' as const,
  label: group.label,
  children: group.children.map((item) => ({
    key: item.key,
    icon: item.icon,
    label: item.label
  }))
}))

function BrandMark() {
  return (
    <div style={{ height: 64, padding: '0 20px' }}>
      <Flex align="center" gap={12} style={{ height: '100%' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 38,
            height: 38,
            borderRadius: 10,
            background: 'linear-gradient(135deg, #dbbd7d, #a47436 55%, #5c3e26)',
            color: '#0d1526',
            fontSize: 17,
            fontWeight: 700
          }}
        >
          火
        </div>
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              color: '#dbbd7d',
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: '0.22em'
            }}
          >
            SPARK ADMIN
          </div>
          <div
            style={{
              marginTop: 2,
              color: '#fff',
              fontSize: 15,
              fontWeight: 600
            }}
          >
            禾下美学院
          </div>
        </div>
      </Flex>
    </div>
  )
}

interface SideMenuProps {
  selectedKey: string
  onSelect: (key: string) => void
  onNavigate?: () => void
}

function SideMenu({ selectedKey, onSelect, onNavigate }: SideMenuProps) {
  return (
    <Flex
      vertical
      style={{ height: '100%', background: '#0d1526', overflow: 'hidden' }}
    >
      <BrandMark />

      <div style={{ flex: 1, overflowY: 'auto', paddingBottom: 12 }}>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={MENU_ITEMS}
          onClick={({ key }) => {
            onSelect(key)
            onNavigate?.()
          }}
          style={{ background: 'transparent', borderInlineEnd: 0 }}
        />
      </div>

      <div
        style={{
          margin: '0 20px 18px',
          paddingTop: 14,
          borderTop: '1px solid rgba(255,255,255,0.08)',
          color: 'rgba(255,255,255,0.4)',
          fontSize: 11,
          lineHeight: '18px'
        }}
      >
        仅用于课程运营与只读订单查询
        <br />
        不提供下单、支付或视频播放能力
      </div>
    </Flex>
  )
}

export default function AdminLayout() {
  const dispatch = useAppDispatch()
  const navigate = useNavigate()
  const location = useLocation()
  const screens = Grid.useBreakpoint()
  const auth = useAppSelector(selectAdminAuth)
  const { modal } = AntdApp.useApp()
  const [drawerOpen, setDrawerOpen] = useState(false)

  const isDesktop = Boolean(screens.lg)
  const platformPath = location.pathname.startsWith('/user-courses/')
    ? '/user-courses'
    : location.pathname
  const currentLabel = ROUTE_LABELS[platformPath] ?? '管理后台'
  const username = auth.admin?.username ?? '管理员'

  useEffect(() => {
    setDrawerOpen(false)
  }, [location.pathname])

  const breadcrumbItems = useMemo(() => {
    const group = ADMIN_NAV_GROUPS.find((item) =>
      item.children.some((child) => child.key === platformPath)
    )
    return [
      { title: '管理后台' },
      ...(group ? [{ title: group.label }] : []),
      { title: currentLabel }
    ]
  }, [platformPath, currentLabel])

  const handleLogout = () => {
    const token = auth.token ?? undefined
    void dispatch(logoutAdmin(token))
    navigate('/login', { replace: true })
  }

  const confirmLogout = () => {
    modal.confirm({
      title: '退出登录？',
      content:
        '退出后将清除本浏览器中的管理员令牌与 Redux 状态，需要重新输入账号密码。',
      okText: '退出登录',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: handleLogout
    })
  }

  const userMenu: MenuProps = {
    items: [
      {
        key: 'role',
        label: (
          <div>
            <div style={{ fontWeight: 600 }}>{username}</div>
            <div style={{ fontSize: 12, color: '#8c8c8c' }}>
              {auth.admin?.role === 'super'
                ? '超级管理员'
                : '普通管理员 · 只读'}
            </div>
          </div>
        ),
        disabled: true,
        icon: <UserOutlined />
      },
      { type: 'divider' },
      {
        key: 'logout',
        label: '退出登录',
        icon: <LogoutOutlined />,
        danger: true
      }
    ],
    onClick: ({ key }) => {
      if (key === 'logout') {
        confirmLogout()
      }
    }
  }

  return (
    <Layout style={{ minHeight: '100vh', background: '#f4f1ea' }}>
      {isDesktop ? (
        <Sider
          width={256}
          style={{
            position: 'fixed',
            insetInlineStart: 0,
            top: 0,
            bottom: 0,
            height: '100vh',
            overflow: 'hidden',
            zIndex: 30
          }}
        >
          <SideMenu
            selectedKey={platformPath}
            onSelect={(key) => navigate(key)}
          />
        </Sider>
      ) : (
        <Drawer
          placement="left"
          width={288}
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          closable={false}
          styles={{ body: { padding: 0, background: '#0d1526' } }}
        >
          <SideMenu
            selectedKey={platformPath}
            onSelect={(key) => navigate(key)}
            onNavigate={() => setDrawerOpen(false)}
          />
        </Drawer>
      )}

      <Layout
        style={{
          minWidth: 0,
          minHeight: '100vh',
          marginInlineStart: isDesktop ? 256 : 0,
          background: '#f4f1ea'
        }}
      >
        <Header
          style={{
            position: 'sticky',
            top: 0,
            zIndex: 20,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 16,
            borderBottom: '1px solid #e7e2d8',
            backdropFilter: 'blur(12px)',
            boxShadow: '0 1px 2px rgba(15, 23, 42, 0.03)'
          }}
        >
          <Flex align="center" gap={12} style={{ minWidth: 0 }}>
            {!isDesktop ? (
              <Button
                type="text"
                icon={<MenuOutlined />}
                onClick={() => setDrawerOpen(true)}
                aria-label="打开菜单"
              />
            ) : null}
            <Breadcrumb items={breadcrumbItems} />
          </Flex>

          <Dropdown menu={userMenu} trigger={['click']}>
            <Flex
              align="center"
              gap={10}
              style={{ cursor: 'pointer', padding: '4px 6px' }}
            >
              <Avatar
                size={34}
                style={{ background: '#0d1526', color: '#e8d4ab' }}
              >
                {username.slice(0, 1).toUpperCase()}
              </Avatar>
              <div
                className="hidden sm:block"
                style={{ lineHeight: '18px', minWidth: 0 }}
              >
                <Typography.Text strong style={{ fontSize: 13 }}>
                  {username}
                </Typography.Text>
                <div style={{ fontSize: 11, color: '#a8a29e' }}>
                  {auth.admin?.role === 'super'
                    ? '超级管理员'
                    : '普通管理员 · 只读'}
                </div>
              </div>
            </Flex>
          </Dropdown>
        </Header>

        <Content style={{ minWidth: 0 }}>
          <div
            style={{
              width: '100%',
              maxWidth: 1500,
              minWidth: 0,
              margin: '0 auto',
              padding: 24
            }}
          >
            <Outlet />
          </div>
        </Content>

        <Footer
          style={{
            width: '100%',
            maxWidth: 1500,
            margin: '0 auto',
            padding: '0 24px 24px',
            background: 'transparent',
            color: '#a8a29e',
            fontSize: 11
          }}
        >
          禾下美学院 · 管理后台仅用于课程运营与只读订单查询，不提供下单、支付或视频播放能力。
        </Footer>
      </Layout>
    </Layout>
  )
}
