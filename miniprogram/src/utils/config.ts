import {
  CONFIG_KEY_ALIASES,
  DEFAULT_CONFIG_VALUES
} from '../constants'

function pickString(
  source: Record<string, string>,
  keys: string[],
  fallback: string
): string {
  for (const key of keys) {
    const value = source[key]
    if (typeof value === 'string') {
      return value
    }
  }
  return fallback
}

/**
 * 后端现有配置键与前端业务键不完全一致（例如 home_title / home_page_title）。
 * 优先使用新键；不存在时兼容旧键；两者都缺失时使用前端内置默认值。
 * 原始键全部保留，管理后台已经配置的旧键依然生效。
 */
export function normalizeConfigValues(
  rawConfigs: Record<string, string> | null | undefined
): Record<string, string> {
  const raw = rawConfigs || {}
  const normalized: Record<string, string> = {
    ...DEFAULT_CONFIG_VALUES,
    ...raw
  }

  Object.entries(CONFIG_KEY_ALIASES).forEach(([targetKey, sourceKeys]) => {
    normalized[targetKey] = pickString(
      raw,
      sourceKeys,
      DEFAULT_CONFIG_VALUES[targetKey] ?? ''
    )
  })

  return normalized
}

export function readConfig(
  values: Record<string, string>,
  key: string,
  fallback = ''
): string {
  const value = values[key]
  return typeof value === 'string' ? value : fallback
}
