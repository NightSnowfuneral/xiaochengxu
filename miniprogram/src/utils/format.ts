export function formatPrice(priceInCents: number): string {
  if (!Number.isFinite(priceInCents) || priceInCents <= 0) {
    return '¥0'
  }
  const yuan = priceInCents / 100
  return Number.isInteger(yuan) ? `¥${yuan}` : `¥${yuan.toFixed(2)}`
}

export function formatPlayTime(totalSeconds: number): string {
  const safeSeconds = Number.isFinite(totalSeconds)
    ? Math.max(0, Math.floor(totalSeconds))
    : 0
  const minutes = Math.floor(safeSeconds / 60)
  const seconds = safeSeconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

/**
 * 订单时间展示。
 *
 * orders.created_at 由 MySQL server_default 写入本地墙钟时间（Asia/Shanghai），
 * 直接截取日期与时分即可，不再按 UTC 二次换算，避免多显示 8 小时。
 */
export function formatOrderTime(value: string | null | undefined): string {
  if (!value) {
    return '--'
  }
  const match = value.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/)
  return match ? `${match[1]} ${match[2]}` : value
}

export function maskMobile(mobile: string | null | undefined): string {
  if (!mobile) {
    return '未绑定手机号'
  }
  if (mobile.length < 7) {
    return mobile
  }
  return `${mobile.slice(0, 3)}****${mobile.slice(-4)}`
}

export function parsePositiveInt(value: string | undefined): number | null {
  if (!value) {
    return null
  }
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

export function safeDecode(value: string | undefined): string {
  if (!value) {
    return ''
  }
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

export function avatarLetter(nickname: string): string {
  const trimmed = nickname.trim()
  return trimmed ? trimmed.slice(0, 1) : '花'
}
