/** 金额、时间与表单值格式化工具。金额在接口与后端始终以「分」为单位。 */

export function formatMoney(cents: number): string {
  if (!Number.isFinite(cents)) {
    return '—'
  }
  return `¥${(cents / 100).toFixed(2)}`
}

export function centsToYuanInput(cents: number): string {
  if (!Number.isFinite(cents)) {
    return ''
  }
  return (cents / 100).toFixed(2)
}

/** 将「元」输入解析为整数分；非法或超过两位小数返回 null。 */
export function parseYuanToCents(value: string): number | null {
  const trimmed = value.trim()
  if (!/^\d+(?:\.\d{1,2})?$/.test(trimmed)) {
    return null
  }
  const [yuanPart, fractionPart = ''] = trimmed.split('.')
  const cents = Number(yuanPart) * 100 + Number(fractionPart.padEnd(2, '0'))
  return Number.isSafeInteger(cents) ? cents : null
}

/**
 * 后端时间列为 MySQL DATETIME（无可时区信息），按原样展示墙上时间，
 * 不做浏览器时区换算，避免后台与服务器出现 8 小时偏差。
 */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return '—'
  }
  const match = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(value)
  if (match) {
    return `${match[1]}-${match[2]}-${match[3]} ${match[4]}:${match[5]}`
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }
  return parsed.toLocaleString('zh-CN', { hour12: false })
}

/**
 * datetime-local 的值与服务器本地时间一致，直接发送 naive datetime，
 * 不附加时区，后端按 DATETIME 原值比较。
 */
export function toApiDateTime(value: string): string | undefined {
  const trimmed = value.trim()
  if (!trimmed) {
    return undefined
  }
  return trimmed.length === 16 ? `${trimmed}:00` : trimmed
}

const SHANGHAI_TIME_ZONE = 'Asia/Shanghai'

interface ShanghaiParts {
  year: string
  month: string
  day: string
  hour: string
  minute: string
}

/**
 * 后端有效期字段为 naive UTC。未带时区时补 Z，再统一换算到
 * Asia/Shanghai；带时区的 ISO 字符串直接解析。
 */
function parseServerUtc(value: string): Date | null {
  const trimmed = value.trim()
  if (!trimmed) {
    return null
  }
  const hasTimeZone = /(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(trimmed)
  const parsed = new Date(
    hasTimeZone ? trimmed : `${trimmed.replace(' ', 'T')}Z`
  )
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function toShanghaiParts(value: string): ShanghaiParts | null {
  const parsed = parseServerUtc(value)
  if (!parsed) {
    return null
  }
  const formatter = new Intl.DateTimeFormat('en-GB', {
    timeZone: SHANGHAI_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23'
  })
  const parts = Object.fromEntries(
    formatter
      .formatToParts(parsed)
      .filter((part) => part.type !== 'literal')
      .map((part) => [part.type, part.value])
  ) as Record<string, string>
  return {
    year: parts.year,
    month: parts.month,
    day: parts.day,
    hour: parts.hour,
    minute: parts.minute
  }
}

/** UTC 时间 → Asia/Shanghai 的 yyyy-mm-dd。 */
export function formatShanghaiDate(value: string | null | undefined): string {
  if (!value) {
    return '—'
  }
  const parts = toShanghaiParts(value)
  return parts ? `${parts.year}-${parts.month}-${parts.day}` : value
}

/** UTC 时间 → Asia/Shanghai 的 yyyy-mm-dd HH:mm。 */
export function formatShanghaiDateTime(
  value: string | null | undefined
): string {
  if (!value) {
    return '—'
  }
  const parts = toShanghaiParts(value)
  return parts
    ? `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`
    : value
}

/** 后台「有效期」列：起止均为空表示永久有效。 */
export function formatShanghaiDateRange(
  start: string | null | undefined,
  end: string | null | undefined
): string {
  if (!start && !end) {
    return '永久有效'
  }
  return `${formatShanghaiDate(start)} ~ ${formatShanghaiDate(end)}`
}

export function formatNumber(value: number): string {
  return Number.isFinite(value) ? value.toLocaleString('zh-CN') : '—'
}

/** 视频时长：不足 1 小时展示 mm:ss，否则展示 h:mm:ss。 */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return '—'
  }
  const total = Math.round(seconds)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const remainder = total % 60
  const pad = (value: number) => String(value).padStart(2, '0')
  return hours > 0
    ? `${hours}:${pad(minutes)}:${pad(remainder)}`
    : `${pad(minutes)}:${pad(remainder)}`
}

/** 文件大小（字节）→ 易读文本。 */
export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return '—'
  }
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }
  if (bytes >= 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`
  }
  return `${bytes} B`
}
