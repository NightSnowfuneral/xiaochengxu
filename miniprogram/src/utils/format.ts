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
