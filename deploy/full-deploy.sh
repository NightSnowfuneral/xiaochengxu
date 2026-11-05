#!/usr/bin/env bash
# =============================================================================
# 禾下美学院｜全量发布（首次部署 / 服务器重建 / 重大变更）
#
# 在本地项目根目录执行：
#   bash deploy/full-deploy.sh
#
# 与日常发布的区别：
# - 重新生成 deploy/.env.production（REFRESH_ENV=1）
# - 重新导出本地测试库 deploy/data/seed.sql（REFRESH_SEED=1）
# - 执行服务器初始化 bootstrap-server.sh（Docker / Compose / Node 20 / swap / UFW）
# - 其余与日常发布一致：上传 → 重建后台与后端镜像 → Alembic → 健康检查 → 失败回滚
#
# 生产库已有表时 seed.sql 不会被导入（deploy.sh 内置空库检查），不会覆盖线上数据。
# 日常修 bug 请使用：bash deploy/daily-deploy.sh
# =============================================================================

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export SKIP_BOOTSTRAP="${SKIP_BOOTSTRAP:-0}"
export REFRESH_ENV="${REFRESH_ENV:-1}"
export REFRESH_SEED="${REFRESH_SEED:-1}"

exec bash "$ROOT_DIR/deploy/remote-deploy.sh" "$@"
