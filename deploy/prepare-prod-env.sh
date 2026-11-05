#!/usr/bin/env bash
# =============================================================================
# 禾下美学院｜从本地 .env 生成生产环境变量
#
# 在本地项目根目录执行：
#   bash deploy/prepare-prod-env.sh
#
# 输出：deploy/.env.production（权限 600，已被 .gitignore 排除）
# 保留本地所有密钥 / 腾讯云配置，只覆盖生产域名相关项：
#   APP_ENV=production
#   CORS_ALLOW_ORIGINS=https://<DOMAIN>
#   WECHAT_PAY_NOTIFY_URL=https://<DOMAIN>/api/v1/payments/wechat/notify
#   TARO_APP_API_BASE_URL=https://<DOMAIN>/api/v1
#   VITE_API_BASE_URL=/api/v1
#
# 脚本不打印任何密钥值。
# =============================================================================

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_ENV="${SOURCE_ENV:-$ROOT_DIR/.env}"
TARGET_ENV="${TARGET_ENV:-$ROOT_DIR/deploy/.env.production}"
DOMAIN="${DOMAIN:-api.qinghebacademy.cn}"

log() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
warn() { printf '[%s] WARN: %s\n' "$(date '+%H:%M:%S')" "$*" >&2; }
die() { log "ERROR: $*" >&2; exit 1; }

[[ -f "$SOURCE_ENV" ]] || die "缺少本地环境变量文件：$SOURCE_ENV"

umask 077
TMP_FILE="$(mktemp "$ROOT_DIR/deploy/.env.production.XXXXXX")"
trap 'rm -f "$TMP_FILE"' EXIT

is_override() {
  case "$1" in
    APP_ENV|CORS_ALLOW_ORIGINS|WECHAT_PAY_NOTIFY_URL|TARO_APP_API_BASE_URL|VITE_API_BASE_URL)
      return 0 ;;
  esac
  return 1
}

log "读取本地环境：$SOURCE_ENV"
log "生产域名：https://$DOMAIN"

while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%$'\r'}"
  if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)= ]]; then
    key="${BASH_REMATCH[1]}"
    # 本地 mock 支付开关不允许带入生产
    [[ "$key" == "LOCAL_MOCK_PAYMENT" ]] && continue
    is_override "$key" && continue
    printf '%s\n' "$line" >> "$TMP_FILE"
  elif [[ -z "$line" || "$line" == \#* ]]; then
    printf '%s\n' "$line" >> "$TMP_FILE"
  fi
done < "$SOURCE_ENV"

{
  printf '\n# -----------------------------------------------------------------------------\n'
  printf '# 生产覆盖项（由 deploy/prepare-prod-env.sh 生成，请勿手工合并回本地 .env）\n'
  printf '# -----------------------------------------------------------------------------\n'
  printf 'APP_ENV=production\n'
  printf 'CORS_ALLOW_ORIGINS=https://%s\n' "$DOMAIN"
  printf 'WECHAT_PAY_NOTIFY_URL=https://%s/api/v1/payments/wechat/notify\n' "$DOMAIN"
  printf 'TARO_APP_API_BASE_URL=https://%s/api/v1\n' "$DOMAIN"
  printf 'VITE_API_BASE_URL=/api/v1\n'
} >> "$TMP_FILE"

mv -f "$TMP_FILE" "$TARGET_ENV"
trap - EXIT
chmod 600 "$TARGET_ENV"

# -----------------------------------------------------------------------------
# 生产前自检（只提示缺失/占位，不输出值）
# -----------------------------------------------------------------------------
read_env() {
  local key="$1" value
  value="$(awk -v key="$key" 'index($0, key "=") == 1 { value = substr($0, length(key) + 2) } END { print value }' "$TARGET_ENV")"
  printf '%s' "${value%$'\r'}"
}

for key in WECHAT_APP_ID WECHAT_APP_SECRET TENCENTCLOUD_SECRET_ID TENCENTCLOUD_SECRET_KEY COS_BUCKET COS_REGION COS_PUBLIC_BASE_URL VOD_APP_ID VOD_PLAY_KEY MYSQL_PASSWORD USER_JWT_SECRET ADMIN_JWT_SECRET; do
  [[ -n "$(read_env "$key")" ]] || warn "生产配置缺少 $key，部署会失败或对应功能不可用"
done

if [[ "$(read_env MYSQL_PASSWORD)" == *[@:/?\#]* ]]; then
  warn "MYSQL_PASSWORD 含 @ : / ? # 等字符，Compose 拼接 DATABASE_URL 时需要 URL 编码"
fi

if [[ "$(read_env USER_JWT_SECRET)" == "$(read_env ADMIN_JWT_SECRET)" ]]; then
  warn "USER_JWT_SECRET 与 ADMIN_JWT_SECRET 相同，生产部署脚本会拒绝启动"
fi

PAY_MCH="$(read_env WECHAT_PAY_MCH_ID)"
if [[ -z "$PAY_MCH" || "$PAY_MCH" == "1900000001" ]]; then
  warn "微信支付仍是本地 mock 配置（MCH_ID 为测试值或为空），正式收款前必须替换为真实商户号、证书序列号、APIv3 密钥与商户私钥"
fi

log "已生成：$TARGET_ENV（权限 600）"
log "下一步：bash deploy/export-local-db.sh && bash deploy/remote-deploy.sh"
