const configuredBaseUrl =
  process.env.TARO_APP_API_BASE_URL || 'http://127.0.0.1:8000/api/v1'

export const API_BASE_URL = configuredBaseUrl.replace(/\/+$/, '')

/** API 根地址（去掉 /api/v1 版本段），用于 /api/vod 这类固定路径接口。 */
export const API_ORIGIN = API_BASE_URL.replace(/\/api\/v1$/, '')

/**
 * 【部署时需确认】播放器完成回调地址。
 *
 * 产品约定固定为 `<API_ORIGIN>/api/vod/finish-lesson`，不带 /v1；
 * 若网关改了路径，必须同步修改后端 `app/api/vod.py` 的挂载前缀
 * 以及这里的地址。该地址为绝对地址，request() 会跳过 baseURL。
 */
export const FINISH_LESSON_URL = `${API_ORIGIN}/api/vod/finish-lesson`

export const REQUEST_TIMEOUT_MS = 15_000

export const IS_DEV = process.env.NODE_ENV === 'development'
