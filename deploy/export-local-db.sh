#!/usr/bin/env bash
# =============================================================================
# 禾下美学院｜导出本地开发库为生产种子数据
#
# 在本地项目根目录执行（需要本地 MySQL 容器正在运行）：
#   bash deploy/export-local-db.sh
#
# 默认读取本地 dev MySQL 容器 huahuo-spark-dev-mysql-1，导出到：
#   deploy/data/seed.sql
#
# deploy.sh 只会在生产库「一张表都没有」时导入该文件，不会覆盖线上数据。
# =============================================================================

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
MYSQL_CONTAINER="${MYSQL_CONTAINER:-huahuo-spark-dev-mysql-1}"
OUT_FILE="${OUT_FILE:-$ROOT_DIR/deploy/data/seed.sql}"

log() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

[[ -f "$ENV_FILE" ]] || die "缺少环境变量文件：$ENV_FILE"
command -v docker >/dev/null 2>&1 || die "缺少命令：docker"

docker inspect -f '{{.State.Running}}' "$MYSQL_CONTAINER" 2>/dev/null | grep -qx true \
  || die "本地 MySQL 容器未运行：$MYSQL_CONTAINER（请先启动 deploy/docker-compose.dev.yml）"

mkdir -p "$(dirname "$OUT_FILE")"
TMP_FILE="${OUT_FILE}.tmp"
trap 'rm -f "$TMP_FILE"' EXIT

log "从容器 $MYSQL_CONTAINER 导出数据库（单事务一致性快照）"
# MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE 由 Compose 注入容器环境，不在宿主机命令行暴露密码
docker exec "$MYSQL_CONTAINER" sh -c '
  MYSQL_PWD="$MYSQL_PASSWORD" mysqldump \
    --single-transaction \
    --quick \
    --routines \
    --triggers \
    --no-tablespaces \
    --set-gtid-purged=OFF \
    --default-character-set=utf8mb4 \
    -u"$MYSQL_USER" "$MYSQL_DATABASE"
' > "$TMP_FILE"

[[ -s "$TMP_FILE" ]] || die "导出结果为空，请检查数据库连接与权限"
grep -q 'CREATE TABLE' "$TMP_FILE" || die "导出文件不含建表语句，请检查数据库是否已完成迁移"

mv -f "$TMP_FILE" "$OUT_FILE"
trap - EXIT
chmod 600 "$OUT_FILE"

TABLE_COUNT="$(grep -c '^CREATE TABLE' "$OUT_FILE" || true)"
SIZE_HUMAN="$(du -h "$OUT_FILE" | awk '{print $1}')"
log "导出完成：$OUT_FILE（$TABLE_COUNT 张表，$SIZE_HUMAN）"
log "该文件含测试用户手机号等业务数据，已在 .gitignore 中排除，请勿提交"
