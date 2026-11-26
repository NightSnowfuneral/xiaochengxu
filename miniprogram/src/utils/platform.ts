import Taro from '@tarojs/taro'

/** 虚拟支付环境按平台区分：iOS 无沙箱，只能走正式环境。 */
export type VirtualPayPlatform = 'ios' | 'android'

/**
 * 当前运行平台。
 *
 * 开发者工具返回 `devtools`、Windows / Mac 返回其它值，一律按安卓处理：
 * 非生产后端会为其选择沙箱环境；生产环境服务端会把两个平台都收敛到
 * env=0，因此这里不是安全边界，只用于展示与选择沙箱/正式。
 */
export function getVirtualPayPlatform(): VirtualPayPlatform {
  try {
    const platform = String(Taro.getSystemInfoSync().platform || '')
    return platform.toLowerCase() === 'ios' ? 'ios' : 'android'
  } catch {
    return 'android'
  }
}
