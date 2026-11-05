import type { AuthUser } from '../types'

/** 仅开发环境模块；生产构建会通过 Taro alias 替换为 mockLogin.stub.ts。 */
export const MOCK_LOGIN_ENABLED = process.env.NODE_ENV === 'development'

export const MOCK_USER_TOKEN = 'mock_test_token_123456'

export function getMockUser(): AuthUser {
  if (!MOCK_LOGIN_ENABLED) {
    throw new Error('模拟登录仅在开发环境可用')
  }
  return {
    id: 999999,
    nickname: '测试用户',
    mobile: '13800138000',
    avatar: '',
    token: 'mock_test_token_123456'
  }
}
