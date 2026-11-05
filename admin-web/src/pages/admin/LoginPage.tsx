import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Alert, Button, Card, Divider, Form, Input, Typography } from 'antd'
import { LockOutlined, UserOutlined } from '@ant-design/icons'

import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  clearLoginError,
  loginAdmin,
  selectAdminAuth,
  selectIsAdminAuthenticated
} from '../../store/slices/adminAuthSlice'

interface LoginLocationState {
  from?: string
  reason?: string
}

interface LoginFormValues {
  username: string
  password: string
}

const HIGHLIGHTS = [
  {
    index: '01',
    title: '双 JWT 权限隔离',
    text: 'Admin Token 与 C 端用户 JWT 使用不同密钥，互不通用。'
  },
  {
    index: '02',
    title: '赠课幂等留痕',
    text: '只匹配已绑手机号用户，同手机号 + 课程不重复发放。'
  },
  {
    index: '03',
    title: '明确的运营边界',
    text: '后台不下单、不支付、不播放视频，订单仅做只读查询。'
  }
]

function resolveRedirectTarget(rawFrom: string | undefined): string {
  if (
    !rawFrom ||
    !rawFrom.startsWith('/') ||
    rawFrom.startsWith('//') ||
    rawFrom.startsWith('/login')
  ) {
    return '/courses'
  }
  return rawFrom
}

export default function LoginPage() {
  const dispatch = useAppDispatch()
  const navigate = useNavigate()
  const location = useLocation()
  const auth = useAppSelector(selectAdminAuth)
  const isAuthenticated = useAppSelector(selectIsAdminAuthenticated)
  const [form] = Form.useForm<LoginFormValues>()
  const [submitting, setSubmitting] = useState(false)

  const locationState = (location.state as LoginLocationState | null) ?? null
  const target = resolveRedirectTarget(locationState?.from)
  const loading = auth.status === 'loading' || submitting

  if (isAuthenticated) {
    return <Navigate to={target} replace />
  }

  const handleFinish = async (values: LoginFormValues) => {
    setSubmitting(true)
    try {
      await dispatch(
        loginAdmin({ username: values.username, password: values.password })
      ).unwrap()
      navigate(target, { replace: true })
    } catch {
      // 登录失败信息由 adminAuthSlice 统一展示。
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[1.08fr_0.92fr]">
      <section
        className="login-brand-grid relative hidden flex-col justify-between overflow-hidden px-12 py-12 text-white lg:flex xl:px-16"
        style={{
          background:
            'radial-gradient(900px 520px at 12% 8%, rgba(164,116,54,0.34), transparent 62%), radial-gradient(700px 460px at 88% 92%, rgba(30,58,95,0.55), transparent 66%), #0d1526'
        }}
      >
        <div className="relative z-10 flex items-center gap-3">
          <div
            className="flex h-11 w-11 items-center justify-center rounded-xl text-lg font-bold"
            style={{
              background:
                'linear-gradient(135deg, #dbbd7d, #a47436 55%, #5c3e26)',
              color: '#0d1526',
              boxShadow: '0 10px 30px rgba(164,116,54,0.35)'
            }}
          >
            火
          </div>
          <div>
            <p
              className="m-0 text-[10px] font-semibold"
              style={{ color: '#dbbd7d', letterSpacing: '0.3em' }}
            >
              SPARK ADMIN
            </p>
            <p className="m-0 mt-0.5 text-lg font-semibold">禾下美学院</p>
          </div>
        </div>

        <div className="relative z-10 max-w-xl py-14">
          <p
            className="m-0 text-xs font-semibold"
            style={{ color: '#dbbd7d', letterSpacing: '0.26em' }}
          >
            KNOWLEDGE COMMERCE · OPERATIONS
          </p>
          <h1 className="mt-5 text-4xl font-semibold leading-tight tracking-tight xl:text-[2.85rem]">
            把课程运营，
            <br />
            交给一套清晰的系统。
          </h1>
          <p className="mt-5 max-w-lg text-sm leading-7 text-slate-300">
            课程与课时维护、手机号赠课、订单只读查询、展示文案配置——
            所有后台操作集中在独立站点，与学员端小程序完全隔离。
          </p>

          <div className="mt-10 grid gap-3">
            {HIGHLIGHTS.map((item) => (
              <div
                key={item.index}
                className="flex gap-4 rounded-xl border px-4 py-3.5"
                style={{
                  borderColor: 'rgba(255,255,255,0.1)',
                  background: 'rgba(255,255,255,0.035)'
                }}
              >
                <span
                  className="mt-0.5 text-xs font-semibold"
                  style={{ color: '#dbbd7d' }}
                >
                  {item.index}
                </span>
                <div>
                  <p className="m-0 text-sm font-medium text-white">
                    {item.title}
                  </p>
                  <p className="m-0 mt-1 text-xs leading-5 text-slate-400">
                    {item.text}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="relative z-10 flex items-center justify-between text-[11px] text-slate-500">
          <span>HEXIA ACADEMY · ADMIN CONSOLE</span>
          <span>管理员专属入口</span>
        </div>
      </section>

      <section className="flex min-h-screen items-center justify-center bg-[#f4f1ea] px-4 py-10 sm:px-8">
        <div className="w-full max-w-[440px]">
          <div className="mb-6 flex items-center gap-3 lg:hidden">
            <div
              className="flex h-10 w-10 items-center justify-center rounded-xl text-base font-bold"
              style={{ background: '#0d1526', color: '#dbbd7d' }}
            >
              火
            </div>
            <div>
              <p
                className="m-0 text-[10px] font-semibold"
                style={{ color: '#a47436', letterSpacing: '0.25em' }}
              >
                SPARK ADMIN
              </p>
              <p className="m-0 text-base font-semibold text-slate-900">
                禾下美学院
              </p>
            </div>
          </div>

          <Card
            style={{
              borderRadius: 16,
              boxShadow: '0 18px 50px -28px rgba(15, 23, 42, 0.35)'
            }}
            styles={{ body: { padding: 32 } }}
          >
            <Typography.Text
              style={{
                display: 'inline-block',
                padding: '2px 10px',
                borderRadius: 999,
                background: '#f4f1ea',
                color: '#6f4a2a',
                fontSize: 11,
                fontWeight: 600
              }}
            >
              管理员登录
            </Typography.Text>
            <Typography.Title level={2} style={{ margin: '14px 0 6px' }}>
              登录管理后台
            </Typography.Title>
            <Typography.Paragraph
              type="secondary"
              style={{ margin: 0, fontSize: 13 }}
            >
              使用管理员账号与密码登录。系统不提供注册、短信验证码或微信登录。
            </Typography.Paragraph>

            {locationState?.reason ? (
              <Alert
                type="warning"
                showIcon
                message={locationState.reason}
                style={{ marginTop: 16 }}
              />
            ) : null}
            {auth.error && auth.error !== locationState?.reason ? (
              <Alert
                type="error"
                showIcon
                message={auth.error}
                style={{ marginTop: 12 }}
              />
            ) : null}

            <Form<LoginFormValues>
              form={form}
              layout="vertical"
              size="large"
              requiredMark={false}
              onFinish={handleFinish}
              onValuesChange={() => {
                if (auth.error) {
                  dispatch(clearLoginError())
                }
              }}
              style={{ marginTop: 22 }}
            >
              <Form.Item
                name="username"
                label="管理员账号"
                rules={[
                  { required: true, whitespace: true, message: '请输入管理员账号' },
                  { max: 64, message: '账号不能超过 64 个字符' }
                ]}
              >
                <Input
                  prefix={<UserOutlined style={{ color: '#bfbfbf' }} />}
                  placeholder="请输入管理员账号"
                  autoComplete="username"
                  maxLength={64}
                  autoFocus
                  disabled={loading}
                />
              </Form.Item>

              <Form.Item
                name="password"
                label="密码"
                rules={[
                  { required: true, message: '请输入密码' },
                  { max: 128, message: '密码不能超过 128 个字符' }
                ]}
              >
                <Input.Password
                  prefix={<LockOutlined style={{ color: '#bfbfbf' }} />}
                  placeholder="请输入密码"
                  autoComplete="current-password"
                  maxLength={128}
                  disabled={loading}
                />
              </Form.Item>

              <Form.Item style={{ marginBottom: 0, marginTop: 4 }}>
                <Button
                  type="primary"
                  htmlType="submit"
                  block
                  loading={loading}
                  style={{ height: 44 }}
                >
                  登录
                </Button>
              </Form.Item>
            </Form>

            <Divider style={{ margin: '22px 0 14px' }} />
            <Typography.Paragraph
              type="secondary"
              style={{ margin: 0, fontSize: 11, lineHeight: '18px' }}
            >
              登录即表示你已获得管理员授权。令牌在到期或退出后会从浏览器
              localStorage 中清除。账号问题请联系系统部署人员。
            </Typography.Paragraph>
          </Card>

          <p className="mt-5 text-center text-[11px] text-slate-400">
            禾下美学院 · 知识付费 · 管理后台
          </p>
        </div>
      </section>
    </div>
  )
}
