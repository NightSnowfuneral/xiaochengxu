#!/usr/bin/env bash
# =============================================================================
# 禾下美学院｜生产部署脚本
#
# 流程：
#   1. git pull
#   2. 环境变量校验 + 从 /home/ubuntu/ssl 自动导入证书
#   3. 构建 admin-web 静态资源
#   4. 构建后端镜像
#   5. 启动 MySQL/Redis
#   6. 空库时导入测试种子数据（deploy/data/seed.sql）
#   7. Alembic 数据库迁移
#   8. 启动 FastAPI 与 Nginx
#   9. 健康检查
#  10. 失败时回滚后端镜像与后台静态资源
#
# 注意：
# - 数据库迁移默认只前进不自动回退；失败回滚会给出人工处理提示。
# - 当前为单 API 实例，服务级滚动更新会有一个短暂的 FastAPI 重建窗口。
# - 健康检查默认走域名并通过 --resolve 指向 127.0.0.1，不依赖 DNS 是否已生效。
# =============================================================================

set -Eeuo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$ROOT_DIR/deploy"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.prod.yml"
ADMIN_DIR="$ROOT_DIR/admin-web"
ADMIN_DIST="$ADMIN_DIR/dist"
ADMIN_BACKUP="$ADMIN_DIR/dist.prev"
ROLLBACK_IMAGE="huahuo-spark-fastapi:rollback"
SEED_SQL="${SEED_SQL:-$DEPLOY_DIR/data/seed.sql}"

DOMAIN="${DOMAIN:-api.qinghebacademy.cn}"
SSL_DIR="${SSL_DIR:-/home/ubuntu/ssl}"
TLS_CERT_FILE="${TLS_CERT_FILE:-}"
TLS_KEY_FILE="${TLS_KEY_FILE:-}"

HEALTH_URL="${HEALTH_URL:-https://$DOMAIN/api/v1/health}"
ADMIN_CHECK_URL="${ADMIN_CHECK_URL:-https://$DOMAIN/admin/}"
# 设为空字符串可关闭 --resolve（例如健康检查指向外部地址）
CURL_RESOLVE="${CURL_RESOLVE-$DOMAIN:443:127.0.0.1}"
CURL_INSECURE="${CURL_INSECURE:-0}"

CHANGED=0
DEPLOY_OK=0

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

die() {
  log "ERROR: $*" >&2
  exit 1
}

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

# 从 .env 读取最后一个同名键的值，不执行文件内容
read_env() {
  local key="$1" value
  value="$(awk -v key="$key" 'index($0, key "=") == 1 { value = substr($0, length(key) + 2) } END { print value }' "$ENV_FILE")"
  value="${value%$'\r'}"
  if [[ ${#value} -ge 2 ]]; then
    case "$value" in
      \"*\") value="${value:1:${#value}-2}" ;;
      \'*\') value="${value:1:${#value}-2}" ;;
    esac
  fi
  printf '%s' "$value"
}

wait_for_health() {
  local service="$1" timeout="${2:-120}" elapsed=0 cid status
  while (( elapsed < timeout )); do
    cid="$(compose ps -q "$service" 2>/dev/null || true)"
    if [[ -n "$cid" ]]; then
      status="$(docker inspect \
        --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "$cid" 2>/dev/null || true)"
      case "$status" in
        healthy) return 0 ;;
        exited|dead) return 1 ;;
      esac
    fi
    sleep 3
    elapsed=$((elapsed + 3))
  done
  return 1
}

check_http() {
  local url="$1" timeout="${2:-30}" elapsed=0
  local curl_args=(--fail --silent --show-error --max-time 5)
  [[ -n "$CURL_RESOLVE" ]] && curl_args+=(--resolve "$CURL_RESOLVE")
  [[ "$CURL_INSECURE" == "1" ]] && curl_args+=(--insecure)
  while (( elapsed < timeout )); do
    if curl "${curl_args[@]}" "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  return 1
}

# 域名证书默认从 /home/ubuntu/ssl 自动导入；已存在 deploy/nginx/certs/ 时不会覆盖。
# 可通过 TLS_CERT_FILE / TLS_KEY_FILE 显式指定文件。
install_certificates() {
  local cert_target="$DEPLOY_DIR/nginx/certs/fullchain.pem"
  local key_target="$DEPLOY_DIR/nginx/certs/privkey.pem"
  local cert_src="$TLS_CERT_FILE" key_src="$TLS_KEY_FILE"
  local candidate

  mkdir -p "$DEPLOY_DIR/nginx/certs"

  if [[ -s "$cert_target" && -s "$key_target" ]]; then
    log "已存在部署证书，跳过导入：$cert_target"
    return 0
  fi

  if [[ -z "$cert_src" ]]; then
    for candidate in \
      "$SSL_DIR/${DOMAIN}_bundle.crt" \
      "$SSL_DIR/${DOMAIN}_bundle.pem" \
      "$SSL_DIR/${DOMAIN}.crt" \
      "$SSL_DIR/${DOMAIN}.pem" \
      "$SSL_DIR/${DOMAIN}.cer"; do
      if [[ -s "$candidate" ]]; then
        cert_src="$candidate"
        break
      fi
    done
  fi
  if [[ -z "$key_src" ]]; then
    for candidate in \
      "$SSL_DIR/${DOMAIN}.key" \
      "$SSL_DIR/${DOMAIN}_private.key" \
      "$SSL_DIR/privkey.pem" \
      "$SSL_DIR/private.key"; do
      if [[ -s "$candidate" ]]; then
        key_src="$candidate"
        break
      fi
    done
  fi
  if [[ -z "$key_src" ]] && [[ -d "$SSL_DIR" ]]; then
    key_src="$(find "$SSL_DIR" -maxdepth 1 -type f \( -name '*.key' -o -name 'privkey*.pem' -o -name 'private*.pem' \) -print 2>/dev/null | sort | head -n 1 || true)"
  fi

  [[ -n "$cert_src" && -s "$cert_src" ]] || die "未找到证书公钥：请把 ${DOMAIN} 证书放到 $SSL_DIR，或设置 TLS_CERT_FILE"
  [[ -n "$key_src" && -s "$key_src" ]] || die "未找到证书私钥：请把 ${DOMAIN} 私钥放到 $SSL_DIR，或设置 TLS_KEY_FILE"

  if command -v openssl >/dev/null 2>&1; then
    local cert_pub key_pub
    cert_pub="$(openssl x509 -in "$cert_src" -noout -pubkey 2>/dev/null | openssl sha256 2>/dev/null || true)"
    key_pub="$(openssl pkey -in "$key_src" -pubout 2>/dev/null | openssl sha256 2>/dev/null || true)"
    if [[ -n "$cert_pub" && -n "$key_pub" && "$cert_pub" != "$key_pub" ]]; then
      die "证书与私钥不匹配：$cert_src / $key_src"
    fi
  fi

  cp -f "$cert_src" "$cert_target"
  cp -f "$key_src" "$key_target"
  chmod 600 "$cert_target" "$key_target"
  log "已导入证书：$cert_src -> $cert_target"
}

# 仅当生产库没有任何表时导入种子数据，避免覆盖线上数据。
import_seed_if_empty() {
  if [[ ! -s "$SEED_SQL" ]]; then
    log "未提供种子数据（$SEED_SQL），跳过"
    return 0
  fi

  local table_count
  table_count="$(compose exec -T mysql sh -c \
    'MYSQL_PWD="$MYSQL_PASSWORD" mysql -N -B -u"$MYSQL_USER" "$MYSQL_DATABASE" -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE();"' \
    2>/dev/null | tr -d '[:space:]' || true)"

  [[ -n "$table_count" ]] || die "无法查询生产库表数量，种子数据未导入"

  if [[ "$table_count" != "0" ]]; then
    log "生产库已有 $table_count 张表，跳过种子数据导入"
    return 0
  fi

  log "生产库为空，导入种子数据：$SEED_SQL"
  if ! compose exec -T mysql sh -c \
    'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u"$MYSQL_USER" "$MYSQL_DATABASE"' < "$SEED_SQL"; then
    die "种子数据导入失败。首次部署可先清理空库卷后重试：docker compose --env-file \"$ENV_FILE\" -f \"$COMPOSE_FILE\" down -v"
  fi
  log "种子数据导入完成"
}

rollback() {
  # 回滚过程中的失败不应再次触发 ERR trap，避免中断回滚
  trap - ERR
  set +e
  log "部署失败，开始回滚..."

  if [[ -d "$ADMIN_BACKUP" ]]; then
    rm -rf "$ADMIN_DIST"
    mv "$ADMIN_BACKUP" "$ADMIN_DIST"
    log "已恢复上一版后台静态资源"
  fi

  if docker image inspect "$ROLLBACK_IMAGE" >/dev/null 2>&1; then
    export RELEASE_TAG="rollback"
    compose up -d --no-deps fastapi
    # 静态目录回滚后 inode 已变化，必须强制重建 Nginx 才能看到恢复后的文件
    compose up -d --no-deps --force-recreate nginx
    wait_for_health fastapi 120
    wait_for_health nginx 120
    log "已回滚到上一版后端镜像与静态资源"
    log "数据库迁移不会自动回退，请人工核对迁移脚本与数据状态"
  else
    log "未找到可回滚镜像（首次部署或镜像已清理），请人工处理"
  fi
}

on_exit() {
  local rc=$?
  if (( rc != 0 && CHANGED == 1 && DEPLOY_OK == 0 )); then
    rollback
  fi
  exit "$rc"
}

trap on_exit EXIT
trap 'log "ERROR: 命令执行失败（第 $LINENO 行）"; exit 1' ERR

# -----------------------------------------------------------------------------
# 0. 基础依赖检查
# -----------------------------------------------------------------------------
[[ -f "$ENV_FILE" ]] || die "缺少环境变量文件：$ENV_FILE"
[[ -f "$COMPOSE_FILE" ]] || die "缺少生产 Compose 文件：$COMPOSE_FILE"
[[ -f "$ADMIN_DIR/package.json" ]] || die "缺少 admin-web/package.json，后台尚未初始化"

for cmd in docker curl npm node awk; do
  command -v "$cmd" >/dev/null 2>&1 || die "缺少命令：$cmd"
done
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 不可用"
docker info >/dev/null 2>&1 || die "Docker daemon 不可用"

# -----------------------------------------------------------------------------
# 1. 拉取最新代码
# -----------------------------------------------------------------------------
if [[ -d "$ROOT_DIR/.git" ]]; then
  log "拉取最新代码"
  git -C "$ROOT_DIR" pull --ff-only
else
  log "当前目录不是 Git 仓库，跳过 git pull"
fi

SHORT_SHA="$(git -C "$ROOT_DIR" rev-parse --short HEAD 2>/dev/null || printf 'nogit')"
export RELEASE_TAG="${RELEASE_TAG:-$(date '+%Y%m%d%H%M%S')-${SHORT_SHA}}"

# -----------------------------------------------------------------------------
# 2. 环境变量与证书校验
# -----------------------------------------------------------------------------
log "校验环境变量"

REQUIRED_VARS=(
  MYSQL_ROOT_PASSWORD
  MYSQL_DATABASE
  MYSQL_USER
  MYSQL_PASSWORD
  REDIS_URL
  USER_JWT_SECRET
  ADMIN_JWT_SECRET
  ADMIN_INITIAL_USERNAME
  ADMIN_INITIAL_PASSWORD
  WECHAT_APP_ID
  WECHAT_APP_SECRET
  WECHAT_PAY_MCH_ID
  WECHAT_PAY_CERT_SERIAL_NO
  WECHAT_PAY_PRIVATE_KEY_PATH
  WECHAT_PAY_API_V3_KEY
  WECHAT_PAY_NOTIFY_URL
  TENCENTCLOUD_SECRET_ID
  TENCENTCLOUD_SECRET_KEY
  COS_BUCKET
  COS_REGION
  COS_PUBLIC_BASE_URL
  VOD_APP_ID
  VOD_PLAY_KEY
)

for key in "${REQUIRED_VARS[@]}"; do
  value="$(read_env "$key")"
  [[ -n "$value" ]] || die ".env 缺少必填项：$key"
  case "$value" in
    change_*|replace_with*|your_*)
      die ".env 中 $key 仍为占位值，请先替换"
      ;;
  esac
  if [[ "$key" == *URL* && "$value" == *example.com* ]]; then
    die ".env 中 $key 不能使用 example.com 占位域名"
  fi
done

USER_JWT_SECRET_VALUE="$(read_env USER_JWT_SECRET)"
ADMIN_JWT_SECRET_VALUE="$(read_env ADMIN_JWT_SECRET)"
[[ ${#USER_JWT_SECRET_VALUE} -ge 32 ]] || die "USER_JWT_SECRET 长度至少 32 位"
[[ ${#ADMIN_JWT_SECRET_VALUE} -ge 32 ]] || die "ADMIN_JWT_SECRET 长度至少 32 位"
[[ "$USER_JWT_SECRET_VALUE" != "$ADMIN_JWT_SECRET_VALUE" ]] || die "C 端与 B 端 JWT 密钥必须不同"

ADMIN_INITIAL_PASSWORD_VALUE="$(read_env ADMIN_INITIAL_PASSWORD)"
[[ ${#ADMIN_INITIAL_PASSWORD_VALUE} -ge 12 ]] || die "ADMIN_INITIAL_PASSWORD 长度至少 12 位"

WECHAT_PAY_NOTIFY_URL_VALUE="$(read_env WECHAT_PAY_NOTIFY_URL)"
[[ "$WECHAT_PAY_NOTIFY_URL_VALUE" == https://* ]] || die "WECHAT_PAY_NOTIFY_URL 必须是 HTTPS 地址"

install_certificates
for cert in "$DEPLOY_DIR/nginx/certs/fullchain.pem" "$DEPLOY_DIR/nginx/certs/privkey.pem"; do
  [[ -s "$cert" ]] || die "缺少 TLS 证书文件：$cert"
done

PAY_KEY_CONTAINER_PATH="$(read_env WECHAT_PAY_PRIVATE_KEY_PATH)"
PAY_KEY_HOST_PATH="$DEPLOY_DIR/secrets/$(basename "$PAY_KEY_CONTAINER_PATH")"
[[ -s "$PAY_KEY_HOST_PATH" ]] || die "缺少微信支付商户私钥：$PAY_KEY_HOST_PATH"

# 新版商户没有平台证书，必须使用「微信支付公钥」验签；
# 公钥文件与公钥 ID 必须同时配置，Compose 也会只读挂载该文件。
PAY_PUBLIC_KEY_PATH="$(read_env WECHAT_PAY_PUBLIC_KEY_PATH)"
PAY_PUBLIC_KEY_ID="$(read_env WECHAT_PAY_PUBLIC_KEY_ID)"
if [[ -n "$PAY_PUBLIC_KEY_PATH" || -n "$PAY_PUBLIC_KEY_ID" ]]; then
  [[ -n "$PAY_PUBLIC_KEY_PATH" && -n "$PAY_PUBLIC_KEY_ID" ]] \
    || die "WECHAT_PAY_PUBLIC_KEY_PATH 与 WECHAT_PAY_PUBLIC_KEY_ID 必须同时配置"
  PAY_PUBLIC_KEY_HOST_PATH="$DEPLOY_DIR/secrets/$(basename "$PAY_PUBLIC_KEY_PATH")"
  [[ -s "$PAY_PUBLIC_KEY_HOST_PATH" ]] \
    || die "缺少微信支付公钥：$PAY_PUBLIC_KEY_HOST_PATH"
fi

compose config -q || die "docker-compose.prod.yml 校验失败"

# -----------------------------------------------------------------------------
# 3. 构建 admin-web 静态资源
# -----------------------------------------------------------------------------
log "备份现有后台静态资源"
rm -rf "$ADMIN_BACKUP"
if [[ -d "$ADMIN_DIST" ]]; then
  cp -a "$ADMIN_DIST" "$ADMIN_BACKUP"
fi

CHANGED=1

log "安装并构建 admin-web"
cd "$ADMIN_DIR"
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmmirror.com}"
if [[ -f package-lock.json ]]; then
  npm ci --registry "$NPM_REGISTRY"
else
  log "未发现 package-lock.json，使用 npm install（$NPM_REGISTRY）"
  npm install --registry "$NPM_REGISTRY"
fi

VITE_API_BASE_URL="/api/v1" \
VITE_BASE_PATH="/admin/" \
PUBLIC_URL="/admin/" \
npm run build -- --base=/admin/

[[ -s "$ADMIN_DIST/index.html" ]] || die "admin-web 构建产物缺少 dist/index.html"
log "admin-web 构建完成"

# -----------------------------------------------------------------------------
# 4. 构建后端镜像
# -----------------------------------------------------------------------------
cd "$ROOT_DIR"

CURRENT_CONTAINER="$(compose ps -q fastapi 2>/dev/null | tr -d '\r' || true)"
if [[ -n "$CURRENT_CONTAINER" ]]; then
  PREVIOUS_IMAGE_ID="$(docker inspect --format '{{.Image}}' "$CURRENT_CONTAINER")"
  docker tag "$PREVIOUS_IMAGE_ID" "$ROLLBACK_IMAGE"
  log "已备份当前后端镜像为 $ROLLBACK_IMAGE"
fi

log "构建后端镜像：$RELEASE_TAG"
compose build --pull fastapi

# -----------------------------------------------------------------------------
# 5. 启动基础设施
# -----------------------------------------------------------------------------
log "启动基础设施"
compose up -d --no-deps mysql redis
wait_for_health mysql 180 || die "MySQL 未通过健康检查"
wait_for_health redis 60 || die "Redis 未通过健康检查"

# -----------------------------------------------------------------------------
# 6. 首次部署导入测试数据（仅空库）
# -----------------------------------------------------------------------------
import_seed_if_empty

# -----------------------------------------------------------------------------
# 7. 数据库迁移
# -----------------------------------------------------------------------------
log "执行数据库迁移"
compose run --rm --no-deps fastapi alembic upgrade head

log "启动 FastAPI 服务"
compose up -d --no-deps fastapi
wait_for_health fastapi 180 || die "FastAPI 未通过健康检查"

log "拉取并校验 Nginx 配置"
compose pull nginx
compose run --rm --no-deps --entrypoint nginx nginx -t

log "更新 Nginx 服务"
compose up -d --no-deps --force-recreate nginx

# -----------------------------------------------------------------------------
# 8. 健康检查
# -----------------------------------------------------------------------------
wait_for_health nginx 120 || die "Nginx 未通过容器健康检查"
check_http "$HEALTH_URL" 60 || die "API 健康检查失败：$HEALTH_URL"
check_http "$ADMIN_CHECK_URL" 30 || die "后台页面健康检查失败：$ADMIN_CHECK_URL"

DEPLOY_OK=1
rm -rf "$ADMIN_BACKUP"

log "部署成功，当前版本：$RELEASE_TAG"
log "API 健康检查：$HEALTH_URL"
log "后台地址：$ADMIN_CHECK_URL"
