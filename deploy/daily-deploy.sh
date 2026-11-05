#!/usr/bin/env bash
# =============================================================================
# 禾下美学院｜日常发布（修完 bug 后一键更新）
#
# 在本地项目根目录执行：
#   bash deploy/daily-deploy.sh
#
# 流程：
#   打包代码 → 上传 → 清理服务器旧代码并解压 → 重建 admin-web 与后端镜像
#   → 启动 MySQL/Redis（不重建）→ Alembic upgrade head → 启动 FastAPI/Nginx
#   → 健康检查 → 失败自动回滚镜像与静态资源
#
# 日常发布的特点：
# - 跳过服务器初始化（SKIP_BOOTSTRAP=1），不重装 Docker/Node、不改 UFW
# - 不重新生成、不上传 deploy/.env.production，服务器 .env 保持不变
#   （显式 REFRESH_ENV=1 时才重新生成并覆盖服务器 .env）
# - 不重新导出测试数据、不导入 seed（生产库非空时 deploy.sh 会跳过）
# - MySQL/Redis 数据卷保持不变，业务数据不会丢失
# - 已删除的本地文件会从服务器删除，避免旧迁移/旧代码残留
#
# 以下场景请改用全量发布：
#   bash deploy/full-deploy.sh
# - 首次部署、换服务器
# - 本地 .env 密钥/COS/VOD/微信配置有变更
# - 服务器环境需要重装或重新初始化
# =============================================================================

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export SKIP_BOOTSTRAP="${SKIP_BOOTSTRAP:-1}"
export REFRESH_ENV="${REFRESH_ENV:-0}"
export REFRESH_SEED="${REFRESH_SEED:-0}"

exec bash "$ROOT_DIR/deploy/remote-deploy.sh" "$@"
