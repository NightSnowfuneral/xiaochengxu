# 禾下美学院｜部署脚本速查

服务器：`124.220.162.138`（Ubuntu，用户 `ubuntu`）
域名：`api.qinghebacademy.cn`
部署目录：`/opt/huahuo-spark`

完整配置清单见 [docs/DEPLOY.md](../docs/DEPLOY.md)，生产运维见 [README_PROD.md](../README_PROD.md)。

## 1. 两种发布方式

| 场景 | 命令 | 服务器初始化 | 重新生成生产 .env | 重新导出测试数据 |
| --- | --- | --- | --- | --- |
| **全量发布**：首次部署、换服务器、密钥/域名变更 | `bash deploy/full-deploy.sh` | 执行 | 是 | 是 |
| **日常发布**：修完 bug 后更新代码 | `bash deploy/daily-deploy.sh` | 跳过 | 否 | 否 |

两个脚本都调用 [remote-deploy.sh](remote-deploy.sh) 的同一套发布流程：

```text
本地打包 → scp 上传 → 清理服务器旧代码并解压
→ bootstrap（仅全量） → deploy.sh：
   构建 admin-web（--base=/admin/）
   构建后端镜像并备份上一版为 huahuo-spark-fastapi:rollback
   启动 MySQL/Redis（已有数据卷不动）
   空库时导入 seed.sql → alembic upgrade head
   启动 FastAPI → 重建 Nginx
   HTTPS 健康检查（--resolve 指向 127.0.0.1）
   失败自动回滚镜像与后台静态资源
```

## 2. 前置条件

1. 本地已配置 `D:/ssh/config`，包含：

   ```sshconfig
   Host beauty
     HostName 124.220.162.138
     User ubuntu
     IdentityFile D:/ssh/id_ed25519
     UserKnownHostsFile /d/ssh/known_hosts
   ```

   换机器时可用 `SSH_CONFIG=... SSH_ALIAS=...` 覆盖；也可以 `SSH_ALIAS=` 后直接指定 `SERVER_USER` / `SERVER_HOST` / `SSH_IDENTITY`（此时 config 里的 IdentityFile 不生效，需显式给出私钥）。

2. 本地项目根目录有 `.env`（含真实 COS / VOD / 微信配置）。
3. 本地 dev MySQL 容器 `huahuo-spark-dev-mysql-1` 正在运行（仅全量发布导出测试数据时需要）。
4. 云服务器安全组放行 `22`、`80`、`443`，不要放行 `3306`、`6379`、`8000`、`18000`。

## 3. 全量发布

```bash
cd /d/project/xiaochengxu/beauty-course-mp
bash deploy/full-deploy.sh
```

- 会执行 `prepare-prod-env.sh`（从本地 `.env` 生成 `deploy/.env.production`）
- 会执行 `export-local-db.sh`（导出本地测试库为 `deploy/data/seed.sql`）
- 会在服务器安装 Docker、Compose v2、Node.js 20，配置 swap、UFW、镜像加速
- `seed.sql` **只在生产库 0 张表时导入**，已有数据自动跳过
- 首次部署后台账号来自测试库的 `admin_users`；`.env` 的 `ADMIN_INITIAL_PASSWORD` 仅对空管理员表生效

只做部分刷新：

```bash
REFRESH_ENV=0 bash deploy/full-deploy.sh   # 不重新生成生产 .env
REFRESH_SEED=0 bash deploy/full-deploy.sh  # 不重新导出测试数据
SKIP_BOOTSTRAP=1 bash deploy/full-deploy.sh
```

## 4. 日常发布（修完 bug）

```bash
cd /d/project/xiaochengxu/beauty-course-mp
bash deploy/daily-deploy.sh
```

- 不上传本地 `.env`，不覆盖服务器 `/opt/huahuo-spark/.env`（服务器 `.env` 缺失会直接报错退出，需先用全量发布）
- 不重装 Docker/Node，不改 UFW
- 不导入 seed，MySQL / Redis 数据卷保持不变
- 自动执行 `alembic upgrade head`；新增迁移会被应用
- 服务器上已删除的本地文件会被清理，避免旧迁移、旧模块残留
- 部署失败自动回滚到上一版镜像与后台静态资源（数据库迁移不会自动回退）

### 4.1 修改了本地 .env（密钥、COS/VOD、微信支付等）

```bash
REFRESH_ENV=1 bash deploy/daily-deploy.sh
```

脚本会重新生成 `deploy/.env.production`、上传并覆盖服务器 `.env`（权限 600），然后重启服务。

### 4.2 修改了数据库结构

在 `backend/alembic/versions/` 新增迁移后直接执行日常发布即可。要求：

- 迁移必须只向前、可重复执行（幂等或带存在性检查）
- 先在本地/预发验证，再发布生产
- 发布失败时脚本回滚代码与镜像，但**不会回滚已执行的 DDL**，需人工核对

### 4.3 修改了小程序代码

小程序不经过服务器发布，需本地构建后上传微信：

```bash
cd miniprogram
npm run build:weapp:online          # 注入 https://api.qinghebacademy.cn/api/v1
```

然后用微信开发者工具「上传」→ 公众平台「提交审核」→「发布」。详见 [docs/DEPLOY.md](../docs/DEPLOY.md) 第 0.5 节。

### 4.4 只想改数据 / 热修 SQL

无需发布，直接进服务器执行：

```bash
ssh -F D:/ssh/config beauty
cd /opt/huahuo-spark
sudo docker compose --env-file .env -f deploy/docker-compose.prod.yml exec mysql \
  sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u"$MYSQL_USER" "$MYSQL_DATABASE"'
```

## 5. 发布后验证

```bash
curl -fsS https://api.qinghebacademy.cn/api/v1/health
curl -fsS -o /dev/null -w '%{http_code}\n' https://api.qinghebacademy.cn/admin/
```

服务器上：

```bash
cd /opt/huahuo-spark
sudo docker compose --env-file .env -f deploy/docker-compose.prod.yml ps
sudo docker compose --env-file .env -f deploy/docker-compose.prod.yml logs --tail=100 fastapi
```

## 6. 回滚

日常发布失败会自动回滚。需要手动回滚时：

```bash
ssh -F D:/ssh/config beauty
cd /opt/huahuo-spark
export RELEASE_TAG=rollback
sudo docker compose --env-file .env -f deploy/docker-compose.prod.yml up -d --no-deps fastapi
sudo docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  up -d --no-deps --force-recreate nginx
```

详见 [README_PROD.md](../README_PROD.md) 第 7 节。

## 7. 脚本清单

| 文件 | 用途 |
| --- | --- |
| [full-deploy.sh](full-deploy.sh) | 全量发布入口 |
| [daily-deploy.sh](daily-deploy.sh) | 日常发布入口 |
| [remote-deploy.sh](remote-deploy.sh) | 共用实现：打包、上传、远程执行 |
| [bootstrap-server.sh](bootstrap-server.sh) | 服务器初始化：Docker/Compose/Node/swap/UFW |
| [deploy.sh](deploy.sh) | 服务器端发布：构建、迁移、健康检查、回滚 |
| [prepare-prod-env.sh](prepare-prod-env.sh) | 从本地 .env 生成生产 .env |
| [export-local-db.sh](export-local-db.sh) | 导出本地测试库为 seed.sql |

## 8. 国内网络与首次构建速度

首次全量发布慢主要来自镜像拉取与 apt / pip / npm 下载，脚本已默认使用国内源：

| 环节 | 默认源 | 覆盖方式 |
| --- | --- | --- |
| Debian apt（后端镜像） | `mirrors.cloud.tencent.com` | 服务器 `.env` 设置 `APT_MIRROR=deb.debian.org` |
| PyPI（后端依赖） | `https://mirrors.cloud.tencent.com/pypi/simple` | 服务器 `.env` 设置 `PIP_INDEX_URL=https://pypi.org/simple` |
| npm（后台构建） | `https://registry.npmmirror.com` | 服务器上 `NPM_REGISTRY=... bash deploy/deploy.sh` |
| Docker 镜像 | `bootstrap-server.sh` 写入 `docker.1ms.run` / `docker.m.daocloud.io` 加速 | 修改 `/etc/docker/daemon.json` 后 `sudo systemctl restart docker` |

`backend/Dockerfile` 会在 `apt-get update` 前把 Debian 源替换为 `APT_MIRROR`（同时兼容 `debian.sources` 与 `sources.list`），pip 通过 `PIP_INDEX_URL` 下载依赖。镜像层会缓存，首次构建完成后，日常发布只重建代码层。

若腾讯云镜像源不可用（例如部署到海外服务器），在服务器 `.env` 中改回官方源后重新发布即可。
