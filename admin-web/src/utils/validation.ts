export const MOBILE_PATTERN = /^1[3-9]\d{9}$/

export function isValidMobile(value: string): boolean {
  return MOBILE_PATTERN.test(value.trim())
}

export function isHttpUrl(value: string): boolean {
  const trimmed = value.trim()
  if (!trimmed || trimmed.length > 1024) {
    return false
  }
  try {
    const url = new URL(trimmed)
    return (
      (url.protocol === 'http:' || url.protocol === 'https:') &&
      Boolean(url.hostname)
    )
  } catch {
    return false
  }
}

/** 正整数 ID 解析；空字符串返回 null。调用方需另行判断必填。 */
export function parsePositiveInt(value: string): number | null {
  const trimmed = value.trim()
  if (!/^\d+$/.test(trimmed)) {
    return null
  }
  const parsed = Number(trimmed)
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null
}

export function isBlank(value: string): boolean {
  return value.trim().length === 0
}
