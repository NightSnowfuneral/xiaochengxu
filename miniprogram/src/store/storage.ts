import Taro from '@tarojs/taro'

/**
 * redux-persist 适配微信同步 Storage。
 * 只持久化 user / config；课程列表与订单状态不落本地。
 */
export const taroStorage = {
  async getItem(key: string): Promise<string | null> {
    try {
      const value = Taro.getStorageSync(key)
      return typeof value === 'string' && value.length > 0 ? value : null
    } catch {
      return null
    }
  },
  async setItem(key: string, value: string): Promise<string> {
    try {
      Taro.setStorageSync(key, value)
    } catch {
      // 存储空间不足时不影响当前会话使用。
    }
    return value
  },
  async removeItem(key: string): Promise<void> {
    try {
      Taro.removeStorageSync(key)
    } catch {
      // 忽略存储清理失败。
    }
  }
}
