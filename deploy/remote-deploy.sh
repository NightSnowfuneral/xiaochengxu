#!/usr/bin/env bash
# =============================================================================
# 禾下美学院｜本地一键部署到腾讯云服务器
#
# 在本地项目根目录执行（Windows 用 Git Bash / WSL，macOS / Linux 用终端）：
#
#   bash deploy/prepare-prod-env.sh      # 首次：生成 deploy/.env.production
#   bash deploy/export-local-db.sh       # 首次：导出测试数据 deploy/data/seed.sql
#   bash deploy/remote-deploy.sh         # 打包上传 + 初始化 + 部署
#
# SSH 默认使用 D:/ssh/config 中的 Host 别名 beauty（内含私钥与 known_hosts）。
# 可覆盖的环境变量：
#   SSH_CONFIG=D:/ssh/config  SSH_ALIAS=beauty
#   SSH_ALIAS=  SERVER_USER=ubuntu  SERVER_HOST=124.220.162.138   # 不走 config 时
#   SSH_IDENTITY=D:/ssh/id_ed25519   # 不走 config 时显式指定私钥
#   APP_DIR=/opt/huahuo-spark  DOMAIN=api.qinghebacademy.cn
#   SKIP_BOOTSTRAP=1    跳过服务器初始化（已手动装好 Docker/Node）
#   REFRESH_ENV=1       重新生成并上传生产 .env（默认不覆盖服务器 .env）
#   REFRESH_SEED=1      重新导出本地测试数据（仅在空库时导入）
#
# 一般不需要直接执行本脚本：用 deploy/full-deploy.sh 或 deploy/daily-deploy.sh。
#
# 前提：
# - D:/ssh/config 中已配置：HostName、User、IdentityFile、UserKnownHostsFile
# - sudo 免密或允许交互输入密码（脚本使用 ssh -t 执行初始化）
# - 云服务器安全组放行 22、80、443
# =============================================================================

set -Eeuo pipefail
# Git Bash 下避免把 /tmp/xxx 改写成 Windows 路径
export MSYS_NO_PATHCONV=1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_USER="${SERVER_USER:-ubuntu}"
SERVER_HOST="${SERVER_HOST:-124.220.162.138}"
SSH_CONFIG="${SSH_CONFIG:-D:/ssh/config}"
# 不加冒号：SSH_ALIAS= 显式置空时表示不走 config 别名
SSH_ALIAS="${SSH_ALIAS-beauty}"
SSH_PORT="${SSH_PORT:-}"
SSH_IDENTITY="${SSH_IDENTITY:-}"
APP_DIR="${APP_DIR:-/opt/huahuo-spark}"
DOMAIN="${DOMAIN:-api.qinghebacademy.cn}"
SKIP_BOOTSTRAP="${SKIP_BOOTSTRAP:-0}"

# 使用 config 别名时由 config 决定 HostName/User/IdentityFile；
# SSH_ALIAS 置空则回退到 SERVER_USER@SERVER_HOST。
if [[ -n "$SSH_ALIAS" ]]; then
  [[ -f "$SSH_CONFIG" ]] || {
    printf '[%s] ERROR: 找不到 SSH 配置文件：%s\n' "$(date '+%H:%M:%S')" "$SSH_CONFIG" >&2
    exit 1
  }
  SSH_TARGET="$SSH_ALIAS"
else
  SSH_TARGET="$SERVER_USER@$SERVER_HOST"
fi

SSH_BASE_OPTS=()
if [[ -f "$SSH_CONFIG" ]]; then
  SSH_BASE_OPTS+=(-F "$SSH_CONFIG")
fi

SSH_PORT_OPTS=()
SCP_PORT_OPTS=()
if [[ -n "$SSH_PORT" ]]; then
  SSH_PORT_OPTS=(-p "$SSH_PORT")
  SCP_PORT_OPTS=(-P "$SSH_PORT")
fi

SSH_OPTS=("${SSH_BASE_OPTS[@]}" "${SSH_PORT_OPTS[@]}" -o ServerAliveInterval=30 -o StrictHostKeyChecking=accept-new)
SCP_OPTS=("${SSH_BASE_OPTS[@]}" "${SCP_PORT_OPTS[@]}" -o ServerAliveInterval=30 -o StrictHostKeyChecking=accept-new)
# 不走 config 别名时需要显式指定私钥（config 里的 IdentityFile 只对 Host beauty 生效）
if [[ -n "$SSH_IDENTITY" ]]; then
  SSH_OPTS+=(-i "$SSH_IDENTITY")
  SCP_OPTS+=(-i "$SSH_IDENTITY")
fi
REMOTE_ARCHIVE="/tmp/huahuo-spark-deploy.tar.gz"
REMOTE_ENV="/tmp/huahuo-spark.env"
REMOTE_SEED="/tmp/huahuo-spark-seed.sql"

log() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

[[ -f "$ROOT_DIR/.env" ]] || die "缺少本地 .env"
command -v ssh >/dev/null 2>&1 || die "缺少命令：ssh"
command -v scp >/dev/null 2>&1 || die "缺少命令：scp"
command -v tar >/dev/null 2>&1 || die "缺少命令：tar"

REFRESH_ENV="${REFRESH_ENV:-0}"
ENV_PROD="$ROOT_DIR/deploy/.env.production"
# 是否把 deploy/.env.production 上传并覆盖服务器 .env。
# 日常发布默认不动服务器 .env（线上可能手工改过）；REFRESH_ENV=1 时强制上传。
UPLOAD_ENV="${UPLOAD_ENV:-0}"
if [[ "$REFRESH_ENV" == "1" ]]; then
  log "生成生产环境变量（REFRESH_ENV=1）"
  DOMAIN="$DOMAIN" bash "$ROOT_DIR/deploy/prepare-prod-env.sh"
  UPLOAD_ENV=1
fi
[[ -s "$ENV_PROD" ]] || die "缺少 deploy/.env.production：首次部署请用 bash deploy/full-deploy.sh，或设置 REFRESH_ENV=1 重新生成"
if [[ "$UPLOAD_ENV" != "1" ]]; then
  log "沿用服务器已有 .env（不上传本地生产环境变量）"
fi

REFRESH_SEED="${REFRESH_SEED:-0}"
SEED_FILE="$ROOT_DIR/deploy/data/seed.sql"
if [[ "$REFRESH_SEED" == "1" || ! -s "$SEED_FILE" ]] && command -v docker >/dev/null 2>&1; then
  if docker inspect -f '{{.State.Running}}' "${MYSQL_CONTAINER:-huahuo-spark-dev-mysql-1}" 2>/dev/null | grep -qx true; then
    log "导出本地测试库：deploy/data/seed.sql"
    bash "$ROOT_DIR/deploy/export-local-db.sh" || log "WARN: 测试数据导出失败，将继续部署空库"
  fi
fi
if [[ -s "$SEED_FILE" ]]; then
  log "种子数据：deploy/data/seed.sql"
else
  log "WARN: 未找到 deploy/data/seed.sql，生产库将保持为空"
fi

ARCHIVE="$(mktemp -t huahuo-spark-deploy-XXXXXX.tar.gz)"
trap 'rm -f "$ARCHIVE"' EXIT

log "打包项目（排除 .git / node_modules / dist / 本地 .env / 证书）"
# 显式列出顶层条目，避免把根目录 .env 打进包
tar -czf "$ARCHIVE" -C "$ROOT_DIR" \
  --exclude='node_modules' \
  --exclude='dist' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache' \
  --exclude='.mypy_cache' \
  --exclude='.venv' \
  --exclude='*.venv' \
  --exclude='deploy/data' \
  --exclude='deploy/secrets' \
  --exclude='deploy/nginx/certs' \
  --exclude='deploy/.env.production' \
  README_DEV.md README_PROD.md .env.example .gitignore \
  admin-web backend deploy docs miniprogram

log "上传代码包到 $SSH_TARGET:/tmp"
scp "${SCP_OPTS[@]}" "$ARCHIVE" "$SSH_TARGET:$REMOTE_ARCHIVE"
REMOTE_ENV_ARG=""
if [[ "$UPLOAD_ENV" == "1" ]]; then
  log "上传生产环境变量"
  scp "${SCP_OPTS[@]}" "$ENV_PROD" "$SSH_TARGET:$REMOTE_ENV"
  REMOTE_ENV_ARG="$REMOTE_ENV"
fi
if [[ -s "$SEED_FILE" ]]; then
  scp "${SCP_OPTS[@]}" "$SEED_FILE" "$SSH_TARGET:$REMOTE_SEED"
fi

log "创建服务器目录：$APP_DIR"
ssh "${SSH_OPTS[@]}" -t "$SSH_TARGET" \
  "sudo mkdir -p '$APP_DIR' && sudo chown \$USER:\$USER '$APP_DIR'"

log "清理服务器旧代码并解压新版本"
# 删除会被新包完整覆盖的目录，避免本地已删除的文件残留在服务器上
# （例如已删除的 Alembic 版本文件仍会被扫描执行）。保留运行期数据：
# 根目录 .env、deploy/secrets、deploy/data、deploy/nginx/certs。
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" \
  "bash -s -- '$APP_DIR' '$REMOTE_ARCHIVE' '$REMOTE_ENV_ARG'" <<'REMOTE_SCRIPT'
set -Eeuo pipefail
APP_DIR="$1"
ARCHIVE="$2"
ENV_FILE="$3"

cd "$APP_DIR"

# 日常发布不上传 .env：清理旧代码前先确认服务器已有可用 .env
if [[ -z "$ENV_FILE" && ! -s "$APP_DIR/.env" ]]; then
  echo "ERROR: 服务器缺少 $APP_DIR/.env；首次部署请用 full-deploy.sh，或 REFRESH_ENV=1 发布" >&2
  exit 1
fi

# 先校验压缩包完整，避免清理旧代码后才发现包损坏
tar -tzf "$ARCHIVE" >/dev/null

# 暂存旧版后台静态资源，交给 deploy.sh 的 dist.prev 回滚机制接管
if [[ -d admin-web/dist ]]; then
  rm -rf /tmp/huahuo-admin-dist
  mv admin-web/dist /tmp/huahuo-admin-dist
fi

rm -rf admin-web backend docs miniprogram
find deploy -mindepth 1 -maxdepth 1 ! -name secrets ! -name data ! -name nginx -exec rm -rf {} +
find deploy/nginx -mindepth 1 -maxdepth 1 ! -name certs -exec rm -rf {} +

tar -xzf "$ARCHIVE" -C "$APP_DIR"

mkdir -p admin-web
if [[ -d /tmp/huahuo-admin-dist ]]; then
  mv /tmp/huahuo-admin-dist admin-web/dist
fi

if [[ -n "$ENV_FILE" ]]; then
  install -m 600 "$ENV_FILE" "$APP_DIR/.env"
  rm -f "$ENV_FILE"
fi
rm -f "$ARCHIVE"
REMOTE_SCRIPT
if [[ -s "$SEED_FILE" ]]; then
  ssh "${SSH_OPTS[@]}" "$SSH_TARGET" \
    "mkdir -p '$APP_DIR/deploy/data' && install -m 600 '$REMOTE_SEED' '$APP_DIR/deploy/data/seed.sql' && rm -f '$REMOTE_SEED'"
fi

log "规范化脚本换行符（避免 Windows CRLF 导致 bash 报错）"
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" \
  "find '$APP_DIR/deploy' -name '*.sh' -exec sed -i 's/\r\$//' {} +"

if [[ "$SKIP_BOOTSTRAP" != "1" ]]; then
  log "初始化服务器（Docker / Compose / Node 20 / swap / UFW）"
  ssh "${SSH_OPTS[@]}" -t "$SSH_TARGET" \
    "sudo bash '$APP_DIR/deploy/bootstrap-server.sh'"
fi

log "执行生产部署"
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" \
  "cd '$APP_DIR' && if id -nG | tr ' ' '\n' | grep -qx docker; then bash deploy/deploy.sh; else sg docker -c 'bash deploy/deploy.sh'; fi"

log "部署完成"
log "管理后台：https://$DOMAIN/admin/"
log "API 健康检查：https://$DOMAIN/api/v1/health"
