# 禾下美学院｜生产部署与第三方配置清单

本文档描述单域名 HTTPS 部署方式：管理后台挂在 `/admin/`，API 挂在 `/api/v1`，Nginx 统一入口，FastAPI、MySQL、Redis 只在 Docker 内网通信。所有配置均以仓库中 `deploy/` 目录和 `.env.example` 为准。

> 管理账号、全部配置项、密钥存放位置、访问地址与回调地址汇总见 [CONFIG.md](CONFIG.md)。

## 0. 当前服务器一键部署（124.220.162.138）

当前环境：

| 项 | 值 |
| --- | --- |
| 服务器 | `124.220.162.138`（Ubuntu 24.04，登录用户 `ubuntu`） |
| 域名 | `api.qinghebacademy.cn` |
| 证书 | 已放在服务器 `/home/ubuntu/ssl/`，文件名前缀 `api.qinghebacademy.cn` |
| API | `https://api.qinghebacademy.cn/api/v1/` |
| 管理后台 | `https://api.qinghebacademy.cn/admin/` |
| 部署目录 | `/opt/huahuo-spark` |

### 0.1 需要开放的端口

| 端口 | 用途 | 是否必须 |
| --- | --- | --- |
| `22/tcp` | SSH 部署与运维（建议在云控制台限制来源 IP） | 必须 |
| `80/tcp` | HTTP → HTTPS 301 跳转、证书续期校验 | 必须 |
| `443/tcp` | HTTPS（小程序、管理后台、API） | 必须 |

**不要开放** `3306`（MySQL）、`6379`（Redis）、`8000`、`18000`（FastAPI）。这些服务只在 Docker 内网通信。

云服务器需要在两个地方放行：腾讯云控制台「安全组」+ 服务器 UFW（`bootstrap-server.sh` 会自动配置 UFW）。

### 0.2 全量发布（首次部署 / 换服务器 / 密钥变更）

```bash
cd /d/project/xiaochengxu/beauty-course-mp

# 一键全量发布：生成生产 .env → 导出本地测试数据 → 初始化服务器 → 部署
bash deploy/full-deploy.sh
```

`full-deploy.sh` 等价于：

```bash
REFRESH_ENV=1 REFRESH_SEED=1 SKIP_BOOTSTRAP=0 bash deploy/remote-deploy.sh
```

它会依次：

1. 从本地 `.env` 生成 `deploy/.env.production`，并导出本地测试库为 `deploy/data/seed.sql`。
2. 打包项目（排除 `.git`、`node_modules`、`dist`、本地 `.env`、本地证书），上传到服务器 `/opt/huahuo-spark`。
3. 清理服务器旧代码（保留 `.env`、`deploy/secrets`、`deploy/data`、`deploy/nginx/certs`）并解压新版本。
4. 执行 `deploy/bootstrap-server.sh`：安装 Docker、Compose v2、Node.js 20、Node 构建依赖，配置 swap、镜像加速与 UFW。
5. 执行 `deploy/deploy.sh`：
   - 从 `/home/ubuntu/ssl/` 自动查找 `api.qinghebacademy.cn*` 证书并复制到 `deploy/nginx/certs/`；
   - 构建管理后台（`--base=/admin/`）与后端镜像；
   - 启动 MySQL/Redis；
   - **仅当生产库没有任何表时**导入 `deploy/data/seed.sql`；
   - 执行 `alembic upgrade head`；
   - 启动 FastAPI 与 Nginx；
   - 用 `curl --resolve api.qinghebacademy.cn:443:127.0.0.1` 做健康检查，不依赖 DNS 是否已生效。

可按需关闭其中步骤：

```bash
REFRESH_ENV=0 bash deploy/full-deploy.sh   # 不重新生成生产 .env
REFRESH_SEED=0 bash deploy/full-deploy.sh  # 不重新导出测试数据
SKIP_BOOTSTRAP=1 bash deploy/full-deploy.sh
```

SSH 默认使用 `D:/ssh/config` 中的 Host 别名 `beauty`（内含 `IdentityFile D:/ssh/id_ed25519` 与 `known_hosts`），无需再 `ssh-copy-id`。可用参数覆盖：

```bash
# 使用其他 config / 别名
SSH_CONFIG=D:/ssh/config SSH_ALIAS=beauty bash deploy/full-deploy.sh

# 不走 config，直接指定主机（config 里的 IdentityFile 不生效，需给 SSH_IDENTITY）
SSH_ALIAS= SERVER_USER=ubuntu SERVER_HOST=124.220.162.138 SSH_PORT=22 \
SSH_IDENTITY=D:/ssh/id_ed25519 \
APP_DIR=/opt/huahuo-spark DOMAIN=api.qinghebacademy.cn \
bash deploy/full-deploy.sh
```

> 当前服务器已验证：`D:/ssh/id_ed25519` 可免密登录 `ubuntu@124.220.162.138`，且 `sudo` 免密。首次执行会在服务器安装 Docker/Compose/Node 20 并配置 UFW。

### 0.3 证书自动导入

`deploy.sh` 会按以下顺序查找证书（已存在 `deploy/nginx/certs/fullchain.pem` 时跳过）：

```text
/home/ubuntu/ssl/api.qinghebacademy.cn_bundle.crt
/home/ubuntu/ssl/api.qinghebacademy.cn_bundle.pem
/home/ubuntu/ssl/api.qinghebacademy.cn.crt
/home/ubuntu/ssl/api.qinghebacademy.cn.pem
/home/ubuntu/ssl/api.qinghebacademy.cn.cer
```

私钥查找 `api.qinghebacademy.cn.key`、`api.qinghebacademy.cn_private.key`、`privkey.pem`、`private.key`。找到后用 `openssl` 校验公私钥是否匹配，再复制为：

```text
deploy/nginx/certs/fullchain.pem
deploy/nginx/certs/privkey.pem   # chmod 600
```

如需手工指定：

```bash
TLS_CERT_FILE=/home/ubuntu/ssl/api.qinghebacademy.cn_bundle.crt \
TLS_KEY_FILE=/home/ubuntu/ssl/api.qinghebacademy.cn.key \
bash deploy/deploy.sh
```

### 0.4 测试数据导入规则

- `deploy/export-local-db.sh` 使用本地 dev MySQL 容器导出，包含表结构、业务数据与 `alembic_version`。
- 生产库**只有 0 张表时**才导入；已有数据会跳过并打印表数量，不会覆盖线上数据。
- 导入后仍会执行 `alembic upgrade head`，补齐本地尚未应用的迁移。
- 测试数据自带 `admin_users`，后台登录请使用本地测试库中的管理员账号；`.env` 的 `ADMIN_INITIAL_USERNAME` / `ADMIN_INITIAL_PASSWORD` 只在管理员表为空时生效。
- `deploy/data/` 已加入 `.gitignore`，内含测试手机号等数据，不要提交。

### 0.5 小程序连接生产服务器

生产构建（API 地址在编译时注入）：

```bash
cd miniprogram
npm run build:weapp:online
```

该命令内置 `TARO_APP_API_BASE_URL=https://api.qinghebacademy.cn/api/v1`。

微信开发者工具对接服务器时：

1. 「详情 → 本地设置」勾选 **不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书**。
2. 域名未备案 / DNS 未生效时，可在本机 `C:\Windows\System32\drivers\etc\hosts` 增加：
   `124.220.162.138 api.qinghebacademy.cn`
3. 管理后台直接访问 `https://api.qinghebacademy.cn/admin/`。
4. 在 COS 控制台把 `https://api.qinghebacademy.cn` 加入桶 CORS 的 Origin，否则后台直传课程图片会被浏览器拦截。
5. 小程序正式发布前必须完成 ICP 备案，并在公众平台把 `https://api.qinghebacademy.cn` 配置为 request 合法域名。
6. 交易类小程序提交审核时，「小程序订单中心path」填 `pages/orders/index`（主路径，不拼参数）；该页对应个人中心「我的订单」。

> 当前 `.env` 中的微信支付是本地 mock 配置（测试商户号 + 本地私钥），部署后登录、课程、播放、后台功能可用，但**不能完成真实支付**。正式收款前替换 `WECHAT_PAY_MCH_ID`、`WECHAT_PAY_CERT_SERIAL_NO`、`WECHAT_PAY_API_V3_KEY` 与 `deploy/secrets/wechatpay_apiclient_key.pem`，再执行一次 `bash deploy/remote-deploy.sh`。

### 0.6 部署后验证

```bash
curl -fsS https://api.qinghebacademy.cn/api/v1/health
curl -fsS -o /dev/null -w '%{http_code}\n' https://api.qinghebacademy.cn/admin/
curl -s  -o /dev/null -w '%{http_code}\n' https://api.qinghebacademy.cn/docs   # 期望 404
```

服务器上查看：

```bash
cd /opt/huahuo-spark
sudo docker compose --env-file .env -f deploy/docker-compose.prod.yml ps
sudo docker compose --env-file .env -f deploy/docker-compose.prod.yml logs -f fastapi
```

### 0.7 日常发布（修完 bug 后一键更新）

```bash
cd /d/project/xiaochengxu/beauty-course-mp
bash deploy/daily-deploy.sh
```

| 行为 | 日常发布 | 全量发布 |
| --- | --- | --- |
| 服务器初始化（Docker/Node/UFW） | 跳过 | 执行 |
| 重新生成 `deploy/.env.production` | 否 | 是 |
| 上传并覆盖服务器 `.env` | 否（`REFRESH_ENV=1` 时是） | 是 |
| 重新导出并上传 `seed.sql` | 上传已有文件，不重新导出 | 重新导出 |
| 导入 seed | 生产库非空时自动跳过 | 同左 |
| 重建 admin-web 与后端镜像 | 是 | 是 |
| `alembic upgrade head` | 是 | 是 |
| MySQL / Redis 数据卷 | 保留 | 保留 |
| 失败自动回滚 | 是 | 是 |

日常发布额外说明：

- 服务器上已删除的本地文件会被清理，避免旧 Alembic 迁移、旧模块继续生效。
- 日常发布不动服务器 `/opt/huahuo-spark/.env`（线上可能手工改过）；若该文件不存在，脚本会在清理旧代码前直接报错退出，需先做一次全量发布。
- 修改了本地 `.env`（微信/COS/VOD/支付密钥等）时使用：`REFRESH_ENV=1 bash deploy/daily-deploy.sh`。
- 新增数据库迁移后直接日常发布即可；迁移失败不会自动回退 DDL，需要人工核对。
- 本次发布包含 `0011_phone_account_binding`（微信一键登录 / 手机号主账号）与 `0012_course_pregifts`（手机号预赠）。首次升级前，先在服务器执行只读预检与备份：

  ```bash
  cd /opt/huahuo-spark

  # 当前迁移版本
  sudo docker compose --env-file .env -f deploy/docker-compose.prod.yml \
    exec -T fastapi alembic current

  # 重复手机号检查：有输出则先人工合并，否则迁移会中止。
  # 尚未应用 0011 时列名是 mobile；已应用后改为 phone。
  sudo docker compose --env-file .env -f deploy/docker-compose.prod.yml \
    exec -T mysql sh -lc \
    'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" -N -e \
     "SELECT mobile, COUNT(*) FROM users WHERE mobile IS NOT NULL GROUP BY mobile HAVING COUNT(*) > 1;"'

  # 备份（不打印任何密钥）
  sudo docker compose --env-file .env -f deploy/docker-compose.prod.yml \
    exec -T mysql sh -lc \
    'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction "$MYSQL_DATABASE"' \
    | gzip > ~/huahuo-spark-$(date +%F-%H%M).sql.gz
  ```

  预检与备份通过后再执行日常发布。`0011` 会重命名 `mobile → phone`、建立唯一索引、新建 `user_bind_openid` / `user_merge_log` 并把历史 `openid` 迁入绑定表；`0012` 再创建 `course_pregifts` / `gift_claim_logs` 并为 `gift_logs` 补充 `user_id` / `pregift_id`，不修改历史赠课记录。
- 小程序代码不受影响，仍需 `cd miniprogram && npm run build:weapp:online` 后在微信开发者工具上传。
- 发布后验证：

  ```bash
  curl -fsS https://api.qinghebacademy.cn/api/v1/health
  curl -fsS -o /dev/null -w '%{http_code}\n' https://api.qinghebacademy.cn/admin/
  ```

- 手动回滚：

  ```bash
  ssh -F D:/ssh/config beauty
  cd /opt/huahuo-spark
  export RELEASE_TAG=rollback
  sudo docker compose --env-file .env -f deploy/docker-compose.prod.yml up -d --no-deps fastapi
  sudo docker compose --env-file .env -f deploy/docker-compose.prod.yml \
    up -d --no-deps --force-recreate nginx
  ```

脚本清单与更简短的速查见 [deploy/README.md](../deploy/README.md)。

## 1. 部署拓扑

```text
微信小程序 ─┐
            ├─ HTTPS 443 ─→ Nginx ─┬─ /api/   ─→ FastAPI :8000 ─→ MySQL / Redis
管理后台  ──┘                      └─ /admin/ ─→ admin-web/dist 静态文件
微信支付回调 ─→ HTTPS /api/v1/payments/wechat/notify ─→ FastAPI
```

| 组件 | 容器名 | 对外暴露 | 说明 |
| --- | --- | --- | --- |
| Nginx | `nginx` | `80`、`443` | 唯一公网入口，负责 TLS、静态后台、API 反代 |
| FastAPI | `fastapi` | 否，仅 `expose 8000` | 单实例；学习进度落库任务运行在进程内 |
| MySQL 8.0 | `mysql` | 否 | 数据卷 `mysql_prod_data` |
| Redis 7 | `redis` | 否 | AOF 开启，数据卷 `redis_prod_data` |

> 学习进度批量落库是一个 FastAPI 进程内后台协程，不是独立 Worker。**生产只能运行一个 FastAPI 实例**；多副本会重复执行落库任务。若未来需要水平扩展，必须先把该任务拆成独立单实例 Worker。

服务器建议：

- Linux x86_64，2 核 4 GB 起步；视频与图片存放在腾讯云 COS / VOD，不占本机磁盘。
- Docker Engine 24+、Docker Compose v2。
- 部署机还需要 `npm`、`node`（建议 Node 20 LTS）、`git`、`curl`、`awk`，因为 `deploy.sh` 在宿主机构建管理后台。
- 安全组/防火墙只放行 `22`（限制来源）、`80`、`443`；不要放行 `3306`、`6379`、`8000`。

## 2. 域名与 DNS

推荐使用一个已完成 ICP 备案的域名，例如：

| 用途 | 地址 |
| --- | --- |
| 管理后台 | `https://api.qinghebacademy.cn/admin/` |
| API | `https://api.qinghebacademy.cn/api/v1/` |
| 微信支付回调 | `https://api.qinghebacademy.cn/api/v1/payments/wechat/notify` |

要求：

1. DNS 添加 `A` 记录指向服务器公网 IP；如启用 IPv6，同步添加 `AAAA`。
2. 微信小程序要求 HTTPS、已备案域名，不能使用 IP 地址或带端口号。
3. 中国大陆服务器必须完成 ICP 备案；未备案域名会被云厂商拦截。
4. 首次切换 DNS 时把 TTL 调低（如 300 秒），确认稳定后再恢复。
5. 如果管理后台要独立域名，需要额外修改 Nginx、证书和 `CORS_ALLOW_ORIGINS`；当前交付按单域名同源设计，无需 CORS。

## 3. SSL 证书

### 3.1 文件位置

Nginx 固定读取以下两个文件：

```text
deploy/nginx/certs/fullchain.pem   # 服务器证书 + 中间证书完整链
deploy/nginx/certs/privkey.pem     # 私钥
```

权限建议：

```bash
chmod 700 deploy/nginx/certs
chmod 644 deploy/nginx/certs/fullchain.pem
chmod 600 deploy/nginx/certs/privkey.pem
```

证书必须与域名匹配。可用云厂商免费/付费证书，或 Let's Encrypt。导入后检查：

```bash
openssl x509 -in deploy/nginx/certs/fullchain.pem -noout -subject -issuer -dates
openssl crl2pkcs7 -nocrl -certfile deploy/nginx/certs/fullchain.pem \
  | openssl pkcs7 -print_certs -noout
```

如使用 RSA 证书，可再比对证书与私钥的 modulus：

```bash
openssl x509 -in deploy/nginx/certs/fullchain.pem -noout -modulus | openssl sha256
openssl rsa  -in deploy/nginx/certs/privkey.pem  -noout -modulus | openssl sha256
```

两条 `modulus` 哈希必须一致；ECDSA 证书不要使用上述 `openssl rsa` 命令。证书链必须完整，否则微信、iOS 等客户端可能报 TLS 错误。

### 3.2 Nginx TLS 配置

仓库 `deploy/nginx/nginx.conf` 已配置：

- 80 端口 301 跳转到 443。
- 仅启用 TLS 1.2 / 1.3。
- 证书路径 `/etc/nginx/certs/fullchain.pem`、`/etc/nginx/certs/privkey.pem`。
- `server_tokens off`，并设置 `X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`。
- 两个 server 块的 `server_name` 已配置为 `api.qinghebacademy.cn`；换域名时同步修改 `deploy/nginx/nginx.conf`：

```nginx
server_name api.qinghebacademy.cn;
```

修改 `deploy/nginx/nginx.conf` 后执行：

```bash
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  exec nginx nginx -t
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  exec nginx nginx -s reload
```

### 3.3 续期

Let's Encrypt 可用 DNS-01 或 `certbot certonly --standalone`（需要短暂停用占用 80 端口的 Nginx）。续期后把新文件覆盖到 `deploy/nginx/certs/`，再 reload Nginx：

```bash
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  exec nginx nginx -s reload
```

`deploy.sh` 只检查证书文件存在，不检查有效期。建议在到期前 30 天设置日历提醒或外部监控，并对 HTTPS 做定期探测。

## 4. 环境变量与密钥

### 4.1 初始化

```bash
cp .env.example .env
chmod 600 .env
```

`.env` 只放在服务器，禁止提交 Git、禁止打包进前端、禁止出现在日志或工单中。`.gitignore` 已忽略 `.env` 与密钥文件。

生成随机密钥：

```bash
openssl rand -hex 32   # USER_JWT_SECRET
openssl rand -hex 32   # ADMIN_JWT_SECRET（必须与上面不同）
openssl rand -hex 16   # 管理员初始密码（至少 12 位，≤72 字节）
```

### 4.2 必填变量清单

`deploy.sh` 会强制检查以下变量非空，且拒绝 `change_*`、`replace_with*`、`your_*` 占位值和 `example.com` URL。

| 分组 | 变量 | 说明 |
| --- | --- | --- |
| 基础 | `APP_ENV` | 生产为 `production`（Compose 会强制覆盖） |
| MySQL | `MYSQL_DATABASE` | 数据库名，默认 `huahuo_spark` |
| MySQL | `MYSQL_USER` / `MYSQL_PASSWORD` | 业务账号密码 |
| MySQL | `MYSQL_ROOT_PASSWORD` | root 密码，仅容器内使用 |
| Redis | `REDIS_URL` | 宿主机开发用；Compose 生产会覆盖为 `redis://redis:6379/0` |
| 进度 | `STUDY_PROGRESS_TTL_SECONDS` | 默认 604800（7 天） |
| 进度 | `STUDY_PROGRESS_FLUSH_INTERVAL_SECONDS` | 默认 60 秒，必须小于 TTL |
| 用户 JWT | `USER_JWT_SECRET` | ≥32 字符，与 Admin 不同 |
| 用户 JWT | `USER_JWT_EXPIRE_MINUTES` | 默认 10080（7 天） |
| 管理员 JWT | `ADMIN_JWT_SECRET` | ≥32 字符，与用户不同 |
| 管理员 JWT | `ADMIN_JWT_EXPIRE_MINUTES` | 默认 480（8 小时） |
| 初始管理员 | `ADMIN_INITIAL_USERNAME` | 首次启动创建 |
| 初始管理员 | `ADMIN_INITIAL_PASSWORD` | ≥12 字符、≤72 字节 |
| 微信 | `WECHAT_APP_ID` / `WECHAT_APP_SECRET` | 小程序 AppID / AppSecret |
| 微信支付 | `WECHAT_PAY_MCH_ID` | 商户号 |
| 微信支付 | `WECHAT_PAY_CERT_SERIAL_NO` | 商户 API 证书序列号 |
| 微信支付 | `WECHAT_PAY_PRIVATE_KEY_PATH` | 容器内路径，默认 `/run/secrets/wechatpay_apiclient_key.pem` |
| 微信支付 | `WECHAT_PAY_API_V3_KEY` | 恰好 32 字节 |
| 微信支付 | `WECHAT_PAY_PUBLIC_KEY_PATH` | 微信支付公钥容器内路径，默认 `/run/secrets/wechatpay_public_key.pem` |
| 微信支付 | `WECHAT_PAY_PUBLIC_KEY` | 可选：PEM 内容；与路径同时配置时优先使用内容 |
| 微信支付 | `WECHAT_PAY_PUBLIC_KEY_ID` | 微信支付公钥 ID（`PUB_KEY_ID_...`） |
| 微信支付 | `WECHAT_PAY_NOTIFY_URL` | 必须为 HTTPS 公网 URL |
| 支付 | `COURSE_VALID_DAY` | 支付成功后课程授权有效天数，默认 365 |
| 订单 | `ORDER_CLOSE_TIMEOUT_MINUTES` | 待支付订单超时自动关闭的分钟数，默认 30 |
| 订单 | `ORDER_CLOSE_SCAN_INTERVAL_SECONDS` | 超时关单扫描周期（秒），默认 300 |
| 订单 | `ORDER_RECONCILE_INTERVAL_SECONDS` | 每日对账周期（秒），默认 86400 |
| 订单 | `ORDER_RECONCILE_LOOKBACK_DAYS` | 对账回看天数，默认 7，允许 1–90 |
| COS | `TENCENTCLOUD_SECRET_ID` / `TENCENTCLOUD_SECRET_KEY` | 建议使用最小权限子账号 |
| COS | `COS_BUCKET` / `COS_REGION` | 存储桶与地域 |
| COS | `COS_PUBLIC_BASE_URL` | 图片公网/CDN 基础地址，不带结尾斜杠 |
| VOD | `VOD_APP_ID` | 点播应用 ID |
| VOD | `VOD_PLAY_KEY` | 点播 Key 防盗链密钥 |
| VOD | `VOD_PLAY_KEY_EXPIRE_SECONDS` | 默认 7200 秒 |
| 前端 | `TARO_APP_API_BASE_URL` | 小程序构建时注入，生产必须是公网 HTTPS API 地址 |

前端只能接触 `TARO_APP_API_BASE_URL` / `VITE_API_BASE_URL` 这类非敏感地址；其余密钥全部留在后端。

### 4.3 微信支付商户私钥

宿主机文件：

```text
deploy/secrets/wechatpay_apiclient_key.pem
```

```bash
chmod 700 deploy/secrets
chmod 600 deploy/secrets/wechatpay_apiclient_key.pem
```

Compose 会把它只读挂载到 FastAPI 容器的 `/run/secrets/wechatpay_apiclient_key.pem`。`deploy.sh` 根据 `WECHAT_PAY_PRIVATE_KEY_PATH` 的 basename 推导宿主机路径，因此**建议保持默认文件名**；改路径时宿主机文件名必须与容器路径 basename 一致。

生产 FastAPI 容器以 `1000:1000`（Ubuntu 默认用户 `ubuntu`）运行，因此密钥文件保持属主 `ubuntu`、权限 `600` 即可被非 root 应用读取。若改成其他属主导致 `Permission denied`，支付客户端会在初始化时报 `微信支付服务暂不可用`。

新版商户（无法申请平台证书）还需放置微信支付公钥：

```text
deploy/secrets/wechatpay_public_key.pem
```

```bash
chmod 600 deploy/secrets/wechatpay_public_key.pem
```

`.env` 同时设置 `WECHAT_PAY_PUBLIC_KEY_PATH=/run/secrets/wechatpay_public_key.pem` 与 `WECHAT_PAY_PUBLIC_KEY_ID=PUB_KEY_ID_...`。Compose 只读挂载到同一路径；两者缺一，后端会拒绝初始化支付客户端。`deploy/remote-deploy.sh` 已排除 `deploy/secrets`，密钥不会随代码包上传，需在服务器上单独放置。

## 5. 微信小程序配置

### 5.1 小程序账号与代码

1. 在微信公众平台注册小程序，主体、类目、认证状态需满足知识付费与相关插件要求。
2. 获取 AppID，替换 `miniprogram/project.config.json` 中的 `"appid": "touristappid"`。
3. AppSecret 只写入服务器 `.env` 的 `WECHAT_APP_SECRET`，不进入小程序代码。
4. 生产构建时注入 API 地址：

```bash
cd miniprogram
npm ci
npm run build:weapp:online   # 内置 https://api.qinghebacademy.cn/api/v1
```

5. 用微信开发者工具导入 `miniprogram` 目录，按 `project.config.json` 的 `miniprogramRoot: dist/` 读取产物；上传前把 `urlCheck` 恢复为平台默认，开发者工具中的「不校验合法域名」只用于本地调试。

### 5.2 服务器域名

在微信公众平台「开发管理 → 开发设置 → 服务器域名」配置：

- `request` 合法域名：`https://api.qinghebacademy.cn`
- `uploadFile` 合法域名：`https://api.qinghebacademy.cn`（个人中心头像经 `Taro.uploadFile` 上传到 `/client/user/avatar`）
- 不需要配置 `downloadFile` 域名：课程图片由浏览器后台直传 COS，视频由原生 video 组件加载服务端签发的 VOD 播放地址；COS 图片通过 `<Image>` 展示，不走 `wx.downloadFile`。
- 域名必须 HTTPS、已备案、证书有效，不能是 IP 或带端口。

### 5.3 手机号授权与隐私

- 在公众平台开通「手机号快速验证」能力，按平台当前规则完成认证、类目与权限申请。
- 在「用户隐私保护指引」中声明收集手机号用于账号绑定与课程权益发放。
- 后端只接收 `getPhoneNumber` 的动态 code，调用微信接口换取手机号；前端不上传明文手机号。
- 登录只保留「微信一键登录」：一次点击同时完成 openid 登录与手机号授权，不再提供短信验证码或单独的绑定手机号入口。
- 手机号是账号唯一信任基准：不同微信使用同一手机号会自动合并到同一账号，课程、订单、预约次数按 `user_id` 全部继承；跨手机号冲突返回 `ACCOUNT_CONFLICT`，不自动合并两个已有账号。
- 赠课只按手机号匹配：已注册手机号直接发放到对应 `user_id`；未注册手机号写入手机号预赠（`course_pregifts`），不创建账号、不归属任何用户。
- 用户首次用该手机号微信授权登录时，后端在同一事务内自动认领全部待认领预赠，课程与预约次数立即到账；认领后永久归属该用户，后续逻辑与普通赠课一致。
- 迁移 `0011_phone_account_binding` 会先检查 `users.phone` 重复值，发现重复会中止升级；执行前先备份数据库并确认无重复手机号（见 0.7 节）。
- 迁移 `0012_course_pregifts` 新增 `course_pregifts`、`gift_claim_logs`，并为 `gift_logs` 增加 `user_id` / `pregift_id`；属于纯增量 DDL，不修改历史赠课数据。
- 迁移 `0014_order_operation_logs` 新增订单取消 / 超时关单 / 对账日志表，纯增量 DDL，不修改历史订单数据；上线后定时任务会自动接管超时关单与每日对账。

### 5.4 视频播放域名

- 当前播放器使用原生 `<video>`，播放地址由后端解析；无需在公众平台申请点播插件。
- 若后续改用「云点播短视频播放器」插件（`wx116d0dd5e6a39ac7`），必须购买插件 License 并通过「微信小程序视频发布」审核，届时再申请插件权限并配置 `plugins`。
- `touristappid` 无法验证支付与真实视频播放，必须用正式 AppID 真机验证。

## 6. 微信支付配置

### 6.1 商户平台

1. 微信支付商户号完成主体认证，并绑定小程序 AppID（JSAPI 支付）。
2. 在商户平台「账户中心 → API 安全」申请 API 证书，得到：
   - 商户号：`WECHAT_PAY_MCH_ID`
   - 商户 API 证书序列号：`WECHAT_PAY_CERT_SERIAL_NO`
   - 商户私钥 `apiclient_key.pem`
3. 设置 32 字节 API v3 密钥：`WECHAT_PAY_API_V3_KEY`（用于回调报文解密，不是签名私钥）。
4. 在「账户中心 → API 安全 → 微信支付公钥」下载 `pub_key.pem`，记录页面上的公钥 ID，分别写入 `deploy/secrets/wechatpay_public_key.pem` 与 `WECHAT_PAY_PUBLIC_KEY_ID`，并设置 `WECHAT_PAY_PUBLIC_KEY_PATH`。
5. 支付回调地址：`https://api.qinghebacademy.cn/api/v1/payments/wechat/notify`，写入 `WECHAT_PAY_NOTIFY_URL`。
6. 在商户平台或小程序后台确认支付授权关系、经营类目、结算账户均已就绪。

### 6.2 回调要求

- 回调接口**不走 JWT 鉴权，仅校验微信支付签名**；不要给该路径加 Basic Auth、登录跳转或需要浏览器交互的 WAF 人机验证。
- Nginx 必须原样转发请求体，不能改写或截断；`/api/` 反代已满足。
- 回调成功返回 HTTP 200 + `{"code":"SUCCESS","message":"成功"}`；失败返回非 2xx，微信会重试。
- 幂等由服务端完成：订单行锁 + 已支付判断 + 课程授权唯一约束；重复回调不会重复发课。
- C 端订单状态只有待支付 / 已支付 / 已取消（`pending` / `paid` / `closed`）三种；后台订单只读，不提供退款接口。
- 待支付订单可由用户主动取消，或由后端定时任务在超时后自动关闭；取消前必须先向微信查单，微信已支付则转正常发课，不会退款、不会回收权益。

### 6.3 支付验收

使用测试商户号或预发布环境完成一笔真实支付。若必须在生产验证，建议创建最低价测试课程；**已产生订单的课程无法删除**（后端返回 `COURSE_IN_USE`），请提前规划。

验收点：

1. 小程序调起支付并成功扣款。
2. 订单状态从 `pending` 变为 `paid`。
3. `我的课程`出现该课程，全部课时解锁。
4. 重复发送同一回调或微信自动重试时，不重复发课。
5. 支付回调失败时有服务端日志，且后台仍为只读。

## 7. 腾讯云 COS 配置（课程图片）

### 7.1 基础参数

创建私有读写或公有读私有写的存储桶，建议仅用于课程图片：

| 变量 | 示例 | 说明 |
| --- | --- | --- |
| `COS_BUCKET` | `huahuo-spark-1250000000` | 存储桶名 |
| `COS_REGION` | `ap-guangzhou` | 地域 |
| `TENCENTCLOUD_SECRET_ID` | 子账号 SecretId | 仅用于生成预签名 |
| `TENCENTCLOUD_SECRET_KEY` | 子账号 SecretKey | 只存服务器 |
| `COS_PUBLIC_BASE_URL` | `https://cdn.example.com` | 图片公网/CDN 基础地址，不带结尾 `/` |

### 7.2 最小权限

为后端创建独立的 CAM 子用户，只授予：

- `cos:PutObject`：资源限定为 `qcs::cos:<region>:uid/<APPID>:<bucket>/courses/*`
- 如使用公有读，读取权限由存储桶策略/CDN 提供，不需要给子账号 `GetObject`。

不要授予 `DeleteObject`、`GetBucket`、跨桶权限或主账号密钥。

### 7.3 图片公开访问

后端返回的 `public_url` 会被小程序和后台直接展示，因此课程图片必须支持匿名 HTTPS GET：

- 方案 A：存储桶策略允许 `courses/*` 公有读。
- 方案 B：COS 绑定 CDN，CDN 回源公开，`COS_PUBLIC_BASE_URL` 填 CDN 域名。

当前代码不支持给图片生成临时 GET 签名，**不要使用私有读且无 CDN 公共访问的桶**，否则图片会 403。桶本身不要开放公有写；写入只能通过后台签发的短期 PUT URL。

### 7.4 CORS

在 COS 控制台为存储桶配置跨域规则：

| 项 | 值 |
| --- | --- |
| Origin | `https://api.qinghebacademy.cn`；开发环境再加 `http://127.0.0.1:5173`、`http://localhost:5173` |
| Methods | `PUT`、`GET`、`HEAD` |
| Allow Headers | `Content-Type`（以及预签名响应中实际要求的头） |
| Expose Headers | `ETag` |
| Max Age | `600` |

上传时浏览器使用原生 PUT，只带 `Content-Type`，**不携带 Admin Token**。不要配置 `Access-Control-Allow-Origin: *` 与允许凭据同时生效。

### 7.5 上限与类型

- 仅允许 `.jpg` / `.jpeg` / `.png` / `.webp`。
- 前端限制单张 10 MB；Nginx 上传上限已按视频中转需求调到 2048 MB，图片仍受前端 10 MB 限制。
- 三张图片（`cover_big`、`cover_small`、`icon_url`）分别上传、分别保存，均必须是可公开访问的 HTTP(S) URL。

## 8. 腾讯云 VOD 配置（课程视频）

### 8.1 基础参数

1. 在腾讯云点播控制台开通服务，获取 `VOD_APP_ID`。
2. 在「分发播放设置 → 防盗链」启用 **Key 防盗链**，生成 `VOD_PLAY_KEY`，不要泄露到前端。
3. 设置 `VOD_PLAY_KEY_EXPIRE_SECONDS`（默认 7200 秒），后端据此签发播放签名和防盗链 URL。
4. 上传视频并转码为 **H.264 MP4**（系统模板 100030 等），取得 FileId，填入后台课时管理的 `vod_file_id`。
5. 数据库只保存 FileId；播放地址由后端调用 VOD API 实时解析，不在数据库保存明文 URL。

### 8.2 播放鉴权链路

1. 小程序请求 `GET /client/lessons/{id}/play-auth`。
2. 后端校验 C 端 JWT 与 `user_course` 授权，未拥有返回 403。
3. 后端用 `VOD_PLAY_KEY` 签发 `psign`，并调用 VOD `DescribeMediaInfos` 解析播放地址；地址按 Key 防盗链规则附加 `t` / `us` / `sign` 后，作为 `play_url` 返回。
4. 出参包含 `file_id`、`app_id`、`signature`、`expire_at`、`play_url`、`last_position`；小程序把 `play_url` 交给原生 `<video>` 组件播放，播放中每 15 秒上报进度。
5. 播放地址有效期与签名一致，过期后必须重新请求；前端不得自行拼接 CDN 地址、缓存过期链接或关闭防盗链。
6. 播放器 `ended` 后调用 `POST /api/vod/finish-lesson`（**不带 `/v1`**，nginx 的 `/api/` 规则已覆盖）。接口再次校验 `user_course`，写入 `is_finished` / 首次 `finished_at`，把 `last_position` 归零并清理 Redis 缓冲；重复调用幂等。

### 8.3 官方插件方案说明

微信「云点播短视频播放器」插件（`wx116d0dd5e6a39ac7`）的官方参数表只有 `appid`、`fileid`、`playerid`，**不支持 psign**；使用该插件必须购买插件 License，并在 VOD 控制台对每个视频执行「微信小程序视频发布」审核（接口 `WeChatMiniProgramPublish`）。

当前实现不依赖该插件：后端解析并签名播放地址，小程序用原生 video 播放。上线前必须验证：

- 开启 Key 防盗链后，未签名地址返回 403，签名地址可正常播放；
- 非授权用户请求 `play-auth` 返回 403，拿不到播放地址；
- 播放地址过期后重新请求是否恢复；
- 续播位置是否生效；
- 播放/暂停、拖拽、当前/总时长、全屏是否可用；倍速（基础库 ≥ 2.13.0）是否生效；
- 视频加载/缓冲时 loading 是否出现，可播放后是否消失；
- 播完是否调用 `finish-lesson` 且 `is_finished=1`、`last_position=0`；
- HEVC 原片在目标机型上是否可解码，不能解码时先转码 H.264。

如果后续改用官方插件，需要先确认账号已购买插件 License 且视频「发布通过」，再切回插件播放；不得在未授权状态下把 `psign` 传给插件。

## 9. Nginx 路由说明

配置文件：`deploy/nginx/nginx.conf`。生产行为如下：

| 请求 | 行为 |
| --- | --- |
| `http://<host>/*` | 301 跳转到 `https://<host>/*` |
| `/api/` | 反代到 `http://fastapi:8000`，保留 `/api` 前缀，透传 Host、X-Real-IP、X-Forwarded-For、X-Forwarded-Proto |
| `/admin/assets/*` | 静态资源，浏览器缓存 1 年 |
| `/admin` | 301 到 `/admin/` |
| `/admin/*` | SPA History 回退到 `/admin/index.html`，HTML 不做长缓存 |
| `/` | 302 到 `/admin/` |
| 其他路径 | 404 |
| `/docs`、`/redoc`、`/openapi.json`（含 `/api`、`/api/v1` 前缀） | 404，Swagger / ReDoc / OpenAPI 不对外暴露 |
| 以 `.` 开头的隐藏路径 | 拒绝并返回 404 |

其他约束：

- `client_max_body_size 2048m`、`client_body_timeout 600s`；API 代理读/写超时 600 秒，并关闭 `proxy_request_buffering`，支持最大 2 GB 视频经后端中转上传（与 `VOD_UPLOAD_MAX_SIZE_MB` 对齐）。上传期间 FastAPI 会把视频流式写入容器内临时文件，请确保服务器磁盘至少预留 `VOD_UPLOAD_MAX_SIZE_MB` 的空间。
- gzip 已开启；`server_tokens off`。
- Nginx 使用 Docker 内置 DNS `127.0.0.11` 解析 `fastapi`，FastAPI 重建后无需手动重启 Nginx。
- `/admin/` 依赖 `admin-web/dist/index.html`。如果后台 404，先检查构建产物是否存在、Compose 卷是否挂载正确。
- 生产只开放 80/443；FastAPI、MySQL、Redis 不映射宿主机端口。

## 10. 构建与首次部署

### 10.1 前置清单

- [ ] 域名已解析到服务器，ICP 备案完成。
- [ ] `fullchain.pem`、`privkey.pem` 已放入 `deploy/nginx/certs/`。
- [ ] 微信支付商户私钥已放入 `deploy/secrets/wechatpay_apiclient_key.pem`。
- [ ] `.env` 已从模板创建，所有必填项为真实值。
- [ ] `USER_JWT_SECRET` 与 `ADMIN_JWT_SECRET` 不同且均 ≥32 字符。
- [ ] `ADMIN_INITIAL_PASSWORD` ≥12 字符。
- [ ] `WECHAT_PAY_NOTIFY_URL` 是真实 HTTPS 地址。
- [ ] COS 桶、CORS、公有读/CDN 已配置。
- [ ] VOD 已开通、Key 防盗链已配置、课程视频已有 FileId。
- [ ] 小程序 AppID、服务器 request 域名、手机号能力已配置。
- [ ] 服务器已安装 Docker、Compose v2、Node 20、npm、git、curl、awk。

### 10.2 首次部署

推荐在本地执行 `bash deploy/full-deploy.sh`（见第 0 节），它会完成上传、服务器初始化和部署；日常更新使用 `bash deploy/daily-deploy.sh`。若已在服务器上：

```bash
cd /opt/huahuo-spark
bash deploy/deploy.sh
```

健康检查默认使用 `https://api.qinghebacademy.cn/...` 并通过 `--resolve` 指向 `127.0.0.1`，无需等待 DNS 生效。如需自定义：

```bash
export DOMAIN=api.qinghebacademy.cn
export HEALTH_URL="https://api.qinghebacademy.cn/api/v1/health"
export ADMIN_CHECK_URL="https://api.qinghebacademy.cn/admin/"
export CURL_RESOLVE=            # 留空则按 DNS 解析
bash deploy/deploy.sh
```

脚本会：

1. 若目录是 Git 仓库则 `git pull --ff-only`。
2. 校验 `.env`、JWT 密钥、管理员密码、通知地址和商户私钥；从 `/home/ubuntu/ssl` 自动导入 TLS 证书。
3. 构建管理后台到 `admin-web/dist`，构建前备份旧 `dist`。
4. 将上一版后端镜像标记为 `huahuo-spark-fastapi:rollback`，构建新后端镜像。
5. 启动 MySQL/Redis。
6. 生产库为空时导入 `deploy/data/seed.sql`。
7. 执行 `alembic upgrade head`。
8. 启动 FastAPI，重建 Nginx，检查容器健康状态、API 与后台页面。
9. 成功则移除 `dist.prev`；失败则恢复上一版静态资源和后端镜像。

首次启动时后端会自动初始化：

- 默认系统配置（不存在时写入）。
- 初始管理员：`ADMIN_INITIAL_USERNAME` / `ADMIN_INITIAL_PASSWORD`。**该密码只在管理员不存在时创建，修改环境变量不会重置已有管理员密码**。
- 学习进度落库后台任务（随 FastAPI 生命周期启动）。

### 10.3 部署后验证

```bash
# API 健康检查
curl -fsS https://api.qinghebacademy.cn/api/v1/health

# 后台页面（应返回 200）
curl -fsS -o /dev/null -w '%{http_code}\n' https://api.qinghebacademy.cn/admin/

# Swagger 应返回 404
curl -s -o /dev/null -w '%{http_code}\n' https://api.qinghebacademy.cn/docs
curl -s -o /dev/null -w '%{http_code}\n' https://api.qinghebacademy.cn/api/v1/docs

# 公开配置
curl -fsS https://api.qinghebacademy.cn/api/v1/config

# 证书
openssl s_client -connect api.qinghebacademy.cn:443 -servername api.qinghebacademy.cn </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -dates
```

然后完成：

1. 后台登录，创建课程并上传三张图片，确认图片公网可访问。
2. 添加课时（VOD FileId），确认后台没有播放按钮。
3. 小程序点击「微信一键登录」并授权手机号，完成购买、播放、进度续播；用第二个微信授权同一手机号，确认落到同一账号且课程 / 订单继承。
4. 后台赠课同一手机号 + 课程两次，确认第二次 `gifted=false` 且日志只有一条。
5. 用一个未注册手机号创建预赠，确认后台预赠列表为「待认领」且不产生课程授权；用该手机号首次微信登录后确认课程到账、预赠变为「已认领」，再次登录不重复发放。
6. 订单页只读，确认没有下单/改状态入口。

## 11. 上线验收清单

### 基础设施

- [ ] `https://<域名>/` 302 到 `/admin/`，后台可正常刷新任意子路由。
- [ ] `/api/v1/health` 返回 `{"status":"ok"}`。
- [ ] HTTP 自动跳转 HTTPS，证书链完整、域名匹配、有效期充足。
- [ ] `/docs`、`/redoc`、`/openapi.json` 以及带 `/api`、`/api/v1` 前缀的路径均 404。
- [ ] MySQL、Redis、8000 端口未暴露公网。
- [ ] `.env`、证书私钥、支付私钥权限正确，未进入 Git。

### 小程序与账号

- [ ] 正式 AppID 已替换，开发者工具上传成功。
- [ ] request 合法域名配置为生产 HTTPS 域名。
- [ ] 无独立登录页；冷启动未登录时首页与课程广场公开渲染，不弹窗、不跳转。
- [ ] 点击受控入口（我的预约 / 全部课程 / 我的课程 / 个人中心）弹出半屏「微信一键登录」；点击一次同时完成 openid 登录与手机号授权；无短信验证码、无单独绑定入口。
- [ ] 拒绝手机号授权时提示「需授权手机号才能完成登录」并保留弹窗、停留当前页，不创建账号。
- [ ] 关闭弹窗中止原操作并停留当前页；登录成功后自动进入原目标页。
- [ ] 第二个微信授权同一手机号后落到同一账号，课程、订单、预约次数继承，`isMerged=true`。
- [ ] 跨手机号冲突返回 `ACCOUNT_CONFLICT`，两个账号不串数据。
- [ ] 主动退出后 `switchTab` 回首页且正常渲染；再冷启动仍为未登录；`/auth/token-check` 对失效 Token 返回 HTTP 200 `valid=false`，前端清理后停留当前页。
- [ ] 生产构建不包含模拟登录入口或测试凭据。
- [ ] 隐私指引声明了手机号用途。

### 支付

- [ ] 下单金额由服务端固化，前端传的金额不会生效。
- [ ] 支付成功后订单为 `paid`，课程全部课时解锁。
- [ ] 重复回调 / 重复轮询不会重复发课。
- [ ] 回调日志无验签失败、金额不匹配、付款人不匹配。
- [ ] 后台订单只读，无改状态、退款入口。

### 课程、图片与视频

- [ ] 三张图片分别上传成功，COS CORS 无报错，`public_url` 可公网访问。
- [ ] 课程删除受 `COURSE_IN_USE` 保护。
- [ ] 课时删除受 `LESSON_HAS_PROGRESS` 保护。
- [ ] 未购买用户播放鉴权返回 403，且响应不含视频信息。
- [ ] 已购买用户在真机通过原生 video 播放，`play_url` 可访问、过期后重新获取恢复。
- [ ] 开启 Key 防盗链后，未签名 `play_url` 返回 403，签名地址正常播放。
- [ ] 15 秒进度上报、退出补报、重新进入续播均正常。
- [ ] 原生控件（播放/暂停、拖拽、时间、全屏）与 0.5x～2x 倍速可用。
- [ ] 视频加载/缓冲展示 loading，可播放后消失。
- [ ] 播完调用 `POST /api/vod/finish-lesson` 返回 200，`is_finished=1`、`last_position=0`。
- [ ] 重复播完或重复点击“重新标记”不覆盖首次 `finished_at`。

### 赠课与配置

- [ ] 赠课只按手机号匹配且不支持 openid；同一手机号多微信已合并到同一账号。
- [ ] 已注册手机号赠课直接到账（`mode=direct` / `status=delivered`）；未注册手机号创建预赠（`mode=pre_gift` / `status=pending`），不创建账号或课程授权。
- [ ] 未注册手机号首次授权登录后，预赠自动认领并出现在我的课程；预约次数按快照到账；多条预赠一次认领；再次登录不重复认领。
- [ ] 预赠认领后永久归属，后台再次提交返回 `status=claimed`，不新增授权。
- [ ] 同一手机号 + 课程重复赠课返回 `gifted=false`，不新增日志。
- [ ] 赠课日志记录管理员、手机号、用户 ID、预赠 ID、课程、时间，筛选正常；后台预赠列表可看待认领 / 已认领、认领用户与来源 IP。
- [ ] 后台只能修改配置值，不能增删配置键。
- [ ] 底部固定两个 Tab，只更新两段文字。
- [ ] 配置保存后小程序 onShow 能拉到新文案，接口异常时有本地默认值兜底。
