#!/usr/bin/env bash
# =============================================================================
# 禾下美学院｜Ubuntu 服务器首次初始化
#
# 适用：Ubuntu 22.04 / 24.04（x86_64），以 root 或带 sudo 的 ubuntu 用户执行：
#   sudo bash deploy/bootstrap-server.sh
#
# 内容：
#   1. 安装基础工具（curl / git / openssl / ufw 等）
#   2. 安装 Docker Engine + Docker Compose v2，并把部署用户加入 docker 组
#   3. 安装 Node.js 20 LTS（deploy.sh 在宿主机构建 admin-web 需要 npm）
#   4. 小内存机器自动创建 2GB swap，避免 npm / Docker 构建 OOM
#   5. UFW 仅放行 22、80、443（云服务器还需在控制台安全组放行同样端口）
#
# 幂等：重复执行不会重复安装。
# =============================================================================

set -Eeuo pipefail

DEPLOY_USER="${DEPLOY_USER:-ubuntu}"
ADMIN_CIDR="${ADMIN_CIDR:-}"   # 可选：SSH 限制来源，如 1.2.3.4/32

log() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

if [[ $EUID -ne 0 ]]; then
  command -v sudo >/dev/null 2>&1 || die "需要 root 权限或 sudo"
  SUDO=(sudo)
else
  SUDO=()
fi

log "安装基础工具"
"${SUDO[@]}" apt-get update -y
DEBIAN_FRONTEND=noninteractive "${SUDO[@]}" apt-get install -y \
  ca-certificates curl gnupg git openssl tar gzip ufw jq

# -----------------------------------------------------------------------------
# Docker Engine + Compose v2
# -----------------------------------------------------------------------------
install_docker_from_aliyun() {
  local arch codename
  arch="$(dpkg --print-architecture)"
  codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"
  "${SUDO[@]}" install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg \
    | "${SUDO[@]}" gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
  "${SUDO[@]}" chmod a+r /etc/apt/keyrings/docker.gpg
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://mirrors.aliyun.com/docker-ce/linux/ubuntu %s stable\n' \
    "$arch" "$codename" | "${SUDO[@]}" tee /etc/apt/sources.list.d/docker.list >/dev/null
  "${SUDO[@]}" apt-get update -y
  DEBIAN_FRONTEND=noninteractive "${SUDO[@]}" apt-get install -y \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  log "Docker 与 Compose v2 已安装：$(docker --version)"
else
  log "安装 Docker Engine 与 Compose v2"
  if ! (curl -fsSL https://get.docker.com | "${SUDO[@]}" sh); then
    log "WARN: get.docker.com 安装失败，改用阿里云 Docker 镜像源"
    install_docker_from_aliyun
  fi
fi

"${SUDO[@]}" systemctl enable --now docker
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 不可用"

# 国内服务器拉取 Docker Hub 镜像经常超时：仅在 daemon.json 不存在/为空时写入加速地址
DAEMON_JSON=/etc/docker/daemon.json
if [[ ! -s "$DAEMON_JSON" ]]; then
  log "配置 Docker 镜像加速"
  "${SUDO[@]}" mkdir -p /etc/docker
  printf '{\n  "registry-mirrors": ["https://docker.1ms.run", "https://docker.m.daocloud.io"]\n}\n' \
    | "${SUDO[@]}" tee "$DAEMON_JSON" >/dev/null
  "${SUDO[@]}" systemctl restart docker
elif ! grep -q 'registry-mirrors' "$DAEMON_JSON"; then
  log "WARN: $DAEMON_JSON 已存在且未配置 registry-mirrors，保持原样；拉取镜像失败时请手工加镜像加速"
fi

if id "$DEPLOY_USER" >/dev/null 2>&1; then
  if ! id -nG "$DEPLOY_USER" | tr ' ' '\n' | grep -qx docker; then
    log "把 $DEPLOY_USER 加入 docker 组（重新登录后生效）"
    "${SUDO[@]}" usermod -aG docker "$DEPLOY_USER"
  fi
fi

# -----------------------------------------------------------------------------
# Node.js 20 LTS
# -----------------------------------------------------------------------------
NODE_MAJOR=0
if command -v node >/dev/null 2>&1; then
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
fi

install_node_binary() {
  local file
  file="$(curl -fsSL https://npmmirror.com/mirrors/node/latest-v20.x/SHASUMS256.txt \
    | awk '/linux-x64\.tar\.xz$/ { print $2; exit }')"
  [[ -n "$file" ]] || die "无法从 npmmirror 获取 Node 20 安装包"
  log "从 npmmirror 安装 $file"
  curl -fsSL "https://npmmirror.com/mirrors/node/latest-v20.x/$file" \
    | "${SUDO[@]}" tar -xJ -C /usr/local --strip-components=1
}

if (( NODE_MAJOR < 20 )); then
  log "安装 Node.js 20 LTS"
  if ! (curl -fsSL https://deb.nodesource.com/setup_20.x | "${SUDO[@]}" bash - \
      && DEBIAN_FRONTEND=noninteractive "${SUDO[@]}" apt-get install -y nodejs); then
    log "WARN: NodeSource 安装失败，改用 npmmirror 二进制包"
    install_node_binary
  fi
else
  log "Node.js 已满足要求：$(node --version)"
fi
command -v npm >/dev/null 2>&1 || die "npm 安装失败"
log "npm 版本：$(npm --version)"

# 国内服务器使用 npm 镜像源，加速 deploy.sh 构建 admin-web
if id "$DEPLOY_USER" >/dev/null 2>&1; then
  "${SUDO[@]}" -u "$DEPLOY_USER" npm config set registry https://registry.npmmirror.com 2>/dev/null || true
fi

# -----------------------------------------------------------------------------
# swap（内存 < 4GB 且无 swap 时创建 2GB）
# -----------------------------------------------------------------------------
MEM_MB="$(awk '/MemTotal/ { printf "%d", $2 / 1024 }' /proc/meminfo)"
HAS_SWAP="$(awk '/SwapTotal/ { printf "%d", $2 / 1024 }' /proc/meminfo)"
if (( MEM_MB < 4096 && HAS_SWAP == 0 )) && [[ ! -f /swapfile ]]; then
  log "内存 ${MEM_MB}MB 且无 swap，创建 /swapfile（2GB）"
  "${SUDO[@]}" fallocate -l 2G /swapfile || "${SUDO[@]}" dd if=/dev/zero of=/swapfile bs=1M count=2048
  "${SUDO[@]}" chmod 600 /swapfile
  "${SUDO[@]}" mkswap /swapfile
  "${SUDO[@]}" swapon /swapfile
  if ! grep -q '^/swapfile ' /etc/fstab; then
    echo '/swapfile none swap sw 0 0' | "${SUDO[@]}" tee -a /etc/fstab >/dev/null
  fi
fi

# -----------------------------------------------------------------------------
# UFW：仅放行 22 / 80 / 443（不暴露 MySQL 3306、Redis 6379、FastAPI 8000）
# -----------------------------------------------------------------------------
if command -v ufw >/dev/null 2>&1; then
  log "配置 UFW 防火墙"
  if [[ -n "$ADMIN_CIDR" ]]; then
    "${SUDO[@]}" ufw allow from "$ADMIN_CIDR" to any port 22 proto tcp
  else
    "${SUDO[@]}" ufw allow 22/tcp
  fi
  "${SUDO[@]}" ufw allow 80/tcp
  "${SUDO[@]}" ufw allow 443/tcp
  "${SUDO[@]}" ufw --force enable
fi

# -----------------------------------------------------------------------------
# 时区
# -----------------------------------------------------------------------------
if command -v timedatectl >/dev/null 2>&1; then
  "${SUDO[@]}" timedatectl set-timezone Asia/Shanghai 2>/dev/null || true
fi

log "服务器初始化完成"
log "Docker：$(docker --version)"
log "Compose：$(docker compose version --short 2>/dev/null || echo v2)"
log "Node：$(node --version) / npm：$(npm --version)"
log "防火墙：22、80、443（云服务器安全组请同步放行）"
log "提示：docker 组变更需重新登录 SSH 后生效；deploy.sh 会自动用 sg docker 兜底"
