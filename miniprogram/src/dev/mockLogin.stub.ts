/**
 * 生产环境替身：不包含模拟用户、模拟 Token 或任何测试凭据。
 * config/index.ts 在 production 构建时把 @mock-login 指向本文件。
 */
export const MOCK_LOGIN_ENABLED = false

export function getMockUser(): never {
  throw new Error('模拟登录在生产环境不可用')
}
