# 禾下美学院｜生产运维手册

本文面向生产环境运维与值班人员，覆盖拓扑约束、首次上线、日常发布、日志与监控、备份恢复、回滚、常见故障与安全操作。

相关文档：

- [docs/DEPLOY.md](docs/DEPLOY.md)：域名、DNS、SSL、微信小程序/支付、COS/VOD、Nginx 路由的配置清单
- [docs/API.md](docs/API.md)：接口、鉴权、入参与出参
- [docs/TEST_CASE.md](docs/TEST_CASE.md)：C 端与 B 端测试用例
- [README_DEV.md](README_DEV.md)：本地开发启动顺序

> 本手册中的命令默认项目部署在 `/opt/huahuo-spark`，请替换成实际路径。
> 所有示例只包含变量名或占位符，不要把真实密码、密钥、Token 写入文档、工单或聊天记录。

---

## 1. 生产拓扑与硬性约束

### 1.1 拓扑

```text
微信小程序 ──HTTPS──┐
                    ├──> Nginx（80/443，唯一公网入口）
管理后台浏览器 ─────┘         │
                             ├── /api/     ──> FastAPI（单实例，容器内 8000）
                             └── /admin/   ──> admin-web 静态资源

FastAPI ──> MySQL 8.0（仅内网）
        └─> Redis 7（仅内网）
        └─> 微信登录 / 微信支付 / 腾讯云 COS / 腾讯云 VOD
```

生产 Compose 只把 Nginx 的 80/443 暴露到宿主机；MySQL、Redis、FastAPI 不映射宿主端口。

### 1.2 必须遵守的约束

| 约束 | 原因 |
| --- | --- |
| **生产只能运行一个 FastAPI 实例** | 学习进度落库任务是 FastAPI 进程内的 lifespan 协程，不是独立 Worker。多实例会重复扫描并落库同一批进度。 |
| 不要执行 `docker compose ... up --scale fastapi=2` | 同上。若未来需要横向扩容，必须先把进度落库拆成单实例 Worker 或加入分布式锁。 |
| 数据库迁移只允许向前执行 | `deploy.sh` 不会自动 `alembic downgrade`；回滚代码不等于回滚数据结构。 |
| 学习进度以 MySQL 为最终结果 | Redis 只做缓冲，TTL 默认 7 天；Redis 故障期间新上报的进度会丢失，但不会影响播放主流程。 |
| 支付回调不校验 JWT | `/api/v1/payments/wechat/notify` 只校验微信支付签名。不要给该路由加后台鉴权，也不要用浏览器登录态测试它。 |
| 图片直传 COS，视频走 VOD | Nginx/FastAPI 不代理大文件；不要改为后端中转视频或返回明文播放地址。 |
| 管理后台不支持下单与视频播放 | 后台只做课程/课时、赠课、订单查询、系统配置。 |

### 1.3 目录与持久化

```text
/opt/huahuo-spark/
├─ .env                          # 生产密钥，仅服务器保存
├─ admin-web/dist/               # 管理后台静态资源（Nginx 只读挂载）
├─ deploy/
│  ├─ docker-compose.prod.yml
│  ├─ deploy.sh
│  ├─ nginx/nginx.conf
│  ├─ nginx/certs/fullchain.pem  # TLS 证书链
│  ├─ nginx/certs/privkey.pem    # TLS 私钥
│  └─ secrets/wechatpay_apiclient_key.pem
└─ backups/                      # 建议放独立磁盘或远端存储
```

持久化卷：

- `huahuo-spark-prod_mysql_prod_data`：MySQL 数据目录；
- `huahuo-spark-prod_redis_prod_data`：Redis AOF 数据。

**不要用 `docker compose down -v`**，该命令会删除生产数据卷。也不要手工 `rm -rf` 卷目录。

---

## 2. 服务器准备与首次上线

### 2.1 宿主机要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | 主流 Linux（Ubuntu 22.04 LTS / Debian 12 / Rocky Linux 9 等） |
| Docker | 24+，Docker Compose v2 |
| 部署脚本依赖 | `git`、`curl`、`node`、`npm`、`awk`、`bash` |
| Node.js | 20 LTS（`deploy.sh` 在宿主机构建 admin-web） |
| 公网端口 | 80、443；SSH 仅对运维白名单开放 |
| 时间同步 | 启用 NTP/chrony；支付签名与证书校验依赖准确时间 |
| 磁盘 | 至少预留 20 GB 给镜像、Docker 日志、MySQL 与本地备份；备份应另存远端 |

`deploy.sh` 会检查 `docker`、`curl`、`npm`、`node`、`awk` 是否存在。`npm ci` 需要 `admin-web/package-lock.json`；没有锁文件时脚本退回 `npm install`。

### 2.2 首次准备

```bash
sudo mkdir -p /opt/huahuo-spark
sudo chown "$USER":"$USER" /opt/huahuo-spark
cd /opt/huahuo-spark

# 从仓库获取代码（生产分支）
# git clone <repo-url> .

cp .env.example .env
chmod 600 .env

mkdir -p deploy/nginx/certs deploy/secrets backups
chmod 700 deploy/nginx/certs deploy/secrets
```

放置文件：

- `deploy/nginx/certs/fullchain.pem`：完整证书链（叶子证书 + 中间证书）；
- `deploy/nginx/certs/privkey.pem`：证书私钥；
- `deploy/secrets/wechatpay_apiclient_key.pem`：微信支付 API 证书私钥（apiclient_key.pem）。

两者都必须是 PEM 格式，且 Nginx/后端容器以只读方式挂载。建议：

```bash
chmod 600 deploy/nginx/certs/privkey.pem deploy/secrets/wechatpay_apiclient_key.pem
```

### 2.3 生产 `.env`

必须逐项替换 `.env.example`（账号、所有配置项与访问/回调地址汇总见 [docs/CONFIG.md](docs/CONFIG.md)）：

```dotenv
APP_ENV=production
API_PREFIX=/api/v1
CORS_ALLOW_ORIGINS=https://<你的域名>

MYSQL_DATABASE=huahuo_spark
MYSQL_USER=spark
MYSQL_PASSWORD=<强随机密码>
MYSQL_ROOT_PASSWORD=<另一个强随机密码>

USER_JWT_SECRET=<至少 32 字节随机值，与 Admin 不同>
ADMIN_JWT_SECRET=<至少 32 字节随机值>
USER_JWT_EXPIRE_MINUTES=10080
ADMIN_JWT_EXPIRE_MINUTES=480

ADMIN_INITIAL_USERNAME=admin
ADMIN_INITIAL_PASSWORD=<至少 12 字符，≤72 字节>

WECHAT_APP_ID=<小程序 AppID>
WECHAT_APP_SECRET=<小程序 AppSecret>
WECHAT_PAY_MCH_ID=<微信支付商户号>
WECHAT_PAY_CERT_SERIAL_NO=<API 证书序列号>
WECHAT_PAY_PRIVATE_KEY_PATH=/run/secrets/wechatpay_apiclient_key.pem
WECHAT_PAY_API_V3_KEY=<恰好 32 字节>
WECHAT_PAY_PUBLIC_KEY_PATH=/run/secrets/wechatpay_public_key.pem
WECHAT_PAY_PUBLIC_KEY_ID=<PUB_KEY_ID_...>
WECHAT_PAY_NOTIFY_URL=https://<你的域名>/api/v1/payments/wechat/notify

TENCENTCLOUD_SECRET_ID=<腾讯云 SecretId>
TENCENTCLOUD_SECRET_KEY=<腾讯云 SecretKey>
COS_BUCKET=<bucket>-<appid>
COS_REGION=ap-guangzhou
COS_PUBLIC_BASE_URL=https://<CDN 或桶域名>

VOD_APP_ID=<VOD AppId>
VOD_PLAY_KEY=<VOD 播放密钥>
VOD_PLAY_KEY_EXPIRE_SECONDS=7200

STUDY_PROGRESS_TTL_SECONDS=604800
STUDY_PROGRESS_FLUSH_INTERVAL_SECONDS=60
```

注意：

- 后端启动时会校验两套 JWT 密钥长度 ≥32、互不相同；`ADMIN_INITIAL_PASSWORD` ≥12；`WECHAT_PAY_API_V3_KEY` 恰好 32 字节；回调地址必须是 HTTPS；进度落库周期必须小于 Redis TTL。
- 后端会校验 `CORS_ALLOW_ORIGINS`。生产同源部署时建议显式写成 `https://<你的域名>`，不要保留 `http://127.0.0.1:5173` 等开发来源；小程序请求不受浏览器 CORS 限制，同源后台也不需要跨域。
- `ADMIN_INITIAL_PASSWORD` 只在管理员用户名不存在时生效。已有管理员后修改该变量**不会重置密码**。
- `WECHAT_PAY_PRIVATE_KEY_PATH` 是**容器内路径**。`deploy.sh` 会读取该值并检查宿主机 `deploy/secrets/$(basename <值>)` 是否存在。
- 新版商户没有平台证书，必须配置 `WECHAT_PAY_PUBLIC_KEY_PATH` 与 `WECHAT_PAY_PUBLIC_KEY_ID`（两者同时配置或同时留空），并将商户平台下载的 `pub_key.pem` 放到 `deploy/secrets/wechatpay_public_key.pem`；否则支付客户端初始化失败。
- `.env`、`deploy/secrets/`、证书私钥必须被 `.gitignore` 排除，禁止进入 Git 或前端构建产物。

生成随机值：

```bash
openssl rand -hex 32
openssl rand -hex 32
openssl rand -base64 32 | head -c 32; echo   # API v3 密钥需恰好 32 字节
```

### 2.4 域名与证书

1. 域名 A 记录指向服务器公网 IP；
2. 申请受信任 TLS 证书（或使用企业 CA / ACME 合法证书）；
3. 将 `fullchain.pem` 与 `privkey.pem` 放入 `deploy/nginx/certs/`；
4. 用 `openssl x509 -noout -subject -dates -in deploy/nginx/certs/fullchain.pem` 检查有效期与域名；
5. 确认证书链包含服务器证书与中间证书：

```bash
openssl crl2pkcs7 -nocrl -certfile deploy/nginx/certs/fullchain.pem \
  | openssl pkcs7 -print_certs -noout
```

上线后用客户端验证完整握手与域名匹配（见 2.7、7.11 节），不要只用 `openssl x509` 检查叶子证书。

生产 Nginx 只接受 443；80 端口会把请求重定向到 HTTPS。小程序后台需配置 request 合法域名，详见 [docs/DEPLOY.md](docs/DEPLOY.md)。

### 2.5 微信小程序与支付配置

以下配置必须在微信公众平台/商户平台完成，代码仓库无法代劳：

- 小程序：AppID、AppSecret、request 合法域名（`https://<域名>`）、业务域名（如需要）、隐私协议与用户信息授权；
- 微信支付：商户号与小程序 AppID 绑定、API v3 密钥、API 证书序列号、商户私钥、支付回调地址；
- 回调地址必须与 `WECHAT_PAY_NOTIFY_URL` 完全一致，且公网 HTTPS 可达；
- VOD 插件与 COS 权限/CORS 按 [docs/DEPLOY.md](docs/DEPLOY.md) 配置。

**上线前必须在真机验证**：微信登录、手机号授权、支付拉起、支付回调、VOD 播放。`touristappid` 和模拟登录不能证明支付/VOD 可用。

### 2.6 首次部署命令

推荐在本地项目根目录一键全量发布（详见 [docs/DEPLOY.md](docs/DEPLOY.md) 第 0 节）：

```bash
bash deploy/full-deploy.sh   # 生成生产 .env + 导出测试数据 + 服务器初始化 + 部署
```

后续修完 bug 的日常发布：

```bash
bash deploy/daily-deploy.sh  # 跳过服务器初始化，重建镜像/迁移/健康检查/失败回滚
```

> SSH 默认读取 `D:/ssh/config` 的 Host 别名 `beauty`（私钥 `D:/ssh/id_ed25519`）；换机器时用 `SSH_CONFIG` / `SSH_ALIAS` 覆盖，或设置 `SSH_ALIAS=` 后直接指定 `SERVER_USER@SERVER_HOST`（此时需用 `SSH_IDENTITY` 显式给出私钥）。脚本速查见 [deploy/README.md](deploy/README.md)。

服务器上手工部署：

```bash
cd /opt/huahuo-spark
bash deploy/deploy.sh
```

`deploy.sh` 的实际顺序：

1. 若目录是 Git 仓库，执行 `git pull --ff-only`；否则跳过；
2. 校验 `.env` 必填项、占位值、JWT 密钥、管理员密码、回调 HTTPS 与支付私钥；从 `/home/ubuntu/ssl` 自动导入 TLS 证书（已存在则跳过）；
3. 备份现有 `admin-web/dist` 到 `admin-web/dist.prev`；
4. 在宿主机执行 `npm ci`/`npm install` 与 `npm run build -- --base=/admin/`；
5. 备份当前 FastAPI 镜像为 `huahuo-spark-fastapi:rollback`；
6. 构建并标记新镜像 `huahuo-spark-fastapi:<RELEASE_TAG>`；
7. 启动 MySQL/Redis 并等待健康检查；
8. 生产库为空时导入 `deploy/data/seed.sql`；
9. 执行 `alembic upgrade head`，启动 FastAPI 并等待健康；
10. 校验并重建 Nginx；
11. 用 `--resolve <域名>:443:127.0.0.1` 请求 API 与后台地址，不依赖 DNS；
12. 成功后删除 `admin-web/dist.prev`。

> `deploy.sh` 构建 admin-web 时会注入 `VITE_API_BASE_URL=/api/v1` 和 `--base=/admin/`。不要用本地默认 base 的产物替换生产静态资源。

**首次部署的特殊性**：MySQL 首次初始化需要几十秒；如果部署失败但日志显示 MySQL 仍在初始化，先确认容器状态与 `docker compose logs mysql`，再决定是否重跑。首次部署时没有 `dist.prev` 和 `rollback` 镜像，自动回滚只能提示人工处理。

### 2.7 上线后验收

```bash
cd /opt/huahuo-spark
COMPOSE_FILE=deploy/docker-compose.prod.yml

docker compose --env-file .env -f "$COMPOSE_FILE" ps
curl -fsS "https://<你的域名>/api/v1/health"
curl -fsS -o /dev/null -w '%{http_code}\n' "https://<你的域名>/admin/"
curl -s -o /dev/null -w '%{http_code}\n' "https://<你的域名>/api/v1/docs"
```

期望：

- `mysql`、`redis`、`fastapi`、`nginx` 均为 `healthy`；
- `/api/v1/health` 返回 200；
- `/admin/` 返回 200，登录后能进入后台；
- `/api/v1/docs`、`/api/v1/redoc`、`/api/v1/openapi.json` 返回 404；
- 小程序能完成微信登录；未购买课程不能播放；支付回调能使订单变为 `paid`；
- 后台能上传课程图片、查询订单、发放赠课；重复赠课返回 `gifted=false`；
- Nginx 安全头存在；HTTP 自动跳转到 HTTPS。

完整清单见 [docs/DEPLOY.md](docs/DEPLOY.md) 的“上线验收清单”。

---

## 3. 日常发布流程

### 3.1 发布前检查

- [ ] 已确认待发布提交与版本号；
- [ ] 已在非生产环境跑过后端 pytest 和关键 P0 手工用例；
- [ ] 新增 Alembic 迁移已在预发/备份环境中验证；
- [ ] 已生成并校验最新 MySQL 逻辑备份；
- [ ] 已归档当前 `admin-web/dist` 与当前 FastAPI 镜像 tag（自动回滚备份会在下一次发布被覆盖）；
- [ ] 当前无进行中的支付异常/对账；
- [ ] 发布窗口内有人值守，且能访问微信商户平台与腾讯云控制台。

### 3.2 发布

推荐在本地项目根目录一键日常发布：

```bash
cd /d/project/xiaochengxu/beauty-course-mp
bash deploy/daily-deploy.sh
```

脚本会：打包 → 上传 → 清理服务器旧代码并解压 → 重建 admin-web 与后端镜像 → 启动 MySQL/Redis → `alembic upgrade head` → 启动 FastAPI → 重建 Nginx → HTTPS 健康检查；失败自动回滚镜像与静态资源。MySQL/Redis 数据卷、服务器 `.env`、证书、`deploy/secrets` 均保持不变。

修改了本地 `.env` 时：`REFRESH_ENV=1 bash deploy/daily-deploy.sh`（会重新生成并覆盖服务器 `.env`）。若服务器 `.env` 不存在，日常发布会直接报错退出，需先做一次全量发布。

服务器上手工发布（不使用本地脚本时）：

```bash
cd /opt/huahuo-spark
bash deploy/deploy.sh
```

发布特点：

- FastAPI 只有单实例，更新期间有短暂 502/连接失败窗口；Nginx 会在上游恢复后继续服务；
- 支付回调在该窗口内可能失败，微信支付会重试；若持续失败，按第 7.5 节排查；
- `alembic upgrade head` 在启动新 FastAPI 容器**之前**执行；如果迁移失败，脚本会尝试回滚镜像与静态资源，但不会回滚已执行的 DDL；
- 健康检查默认校验证书链（`CURL_INSECURE=1` 可临时跳过）；证书过期仍需独立监控。

### 3.3 发布后验证

至少执行：

```bash
docker compose --env-file .env -f deploy/docker-compose.prod.yml ps
docker compose --env-file .env -f deploy/docker-compose.prod.yml logs --tail=100 fastapi
docker compose --env-file .env -f deploy/docker-compose.prod.yml logs --tail=100 nginx
curl -fsS "https://<你的域名>/api/v1/health"
curl -fsS -o /dev/null "https://<你的域名>/admin/"
```

再用测试账号走一遍：微信登录 → 课程详情 → 支付（小额真实或商户测试）→ 播放 → 进度上报 → 后台查看订单/赠课。不要用生产管理员账号做破坏性测试。

### 3.4 版本归档（建议）

自动回滚只在**本次部署失败时**有效；部署成功后 `dist.prev` 被删除，`rollback` 镜像也会在下次发布时被覆盖。为了支持跨发布回滚，应在**每次发布前归档即将被替换的版本**（或在每次发布成功后立即归档本次产物，并至少保留上一版）：

```bash
cd /opt/huahuo-spark
TS=$(date +%Y%m%d%H%M%S)
mkdir -p backups/releases

# 当前（即将被替换的）后台静态资源
tar -czf "backups/releases/admin-dist-${TS}.tar.gz" -C admin-web dist

# 当前后端镜像（先确认容器实际使用的 tag）
docker inspect --format '{{.Config.Image}}' \
  "$(docker compose --env-file .env -f deploy/docker-compose.prod.yml ps -q fastapi)"
docker image ls huahuo-spark-fastapi --format '{{.Repository}}:{{.Tag}} {{.ID}}'
docker save huahuo-spark-fastapi:<当前版本tag> \
  | gzip > "backups/releases/fastapi-${TS}.tar.gz"

# 部署配置（不含 .env 真实值）
cp deploy/docker-compose.prod.yml deploy/nginx/nginx.conf backups/releases/
```

镜像归档体积较大，可只保留最近 N 个版本；后台静态资源与配置必须与对应镜像版本一起保存。若在发布成功后才归档，请把上述 `<当前版本tag>` 换成刚发布的版本，并保留上一版归档不要覆盖。

---

## 4. 日志

### 4.1 查看容器日志

```bash
cd /opt/huahuo-spark
COMPOSE_FILE=deploy/docker-compose.prod.yml

# 全服务
docker compose --env-file .env -f "$COMPOSE_FILE" logs --tail=200 -f

# 单个服务
docker compose --env-file .env -f "$COMPOSE_FILE" logs --tail=500 -f fastapi
docker compose --env-file .env -f "$COMPOSE_FILE" logs --tail=200 -f nginx
docker compose --env-file .env -f "$COMPOSE_FILE" logs --tail=200 -f mysql
```

Uvicorn 的访问日志（`uvicorn.access`）输出到容器 stdout，由 Docker 日志驱动保存。`docker compose logs` 的 `--since`/`--until` 可用于定位时间窗：

```bash
docker compose --env-file .env -f deploy/docker-compose.prod.yml logs \
  --since "2026-01-01T10:00:00" --until "2026-01-01T10:10:00" fastapi
```

> **日志配置**：FastAPI 启动时按 `LOG_LEVEL`（默认 `INFO`）统一配置根 logger，输出到容器 stdout，格式为：
>
> ```text
> 2026-11-03 10:00:00 INFO [app.services.pay_service] 支付成功并发课: out_trade_no=... user_id=12 mobile=13800138000 amount=9900
> ```
>
> `uvicorn.access` 与 `uvicorn.error` 的时间格式也会对齐，访问日志仍由 Nginx 后方真实客户端地址与状态码组成。登录、绑定手机号、下单、支付回调、赠课与播放鉴权失败等关键业务日志会带上 `user_id` / `mobile`；后台操作日志会带上 `admin_id` / `account`。业务日志不会输出 Token、密码、请求头或密钥；如需排查第三方请求，只记录异常类型和业务标识（订单号、FileId 等）。
>
> 手机号属于个人信息：日志应视为内部敏感数据，仅授权运维可访问，并通过 Docker 日志轮转控制保留时间；不要将日志上传到公开网盘、聊天群或工单附件。将 `LOG_LEVEL` 调整为 `WARNING` 可关闭 INFO，适用于日志量过大的临时处理；修改后需重建 FastAPI 容器，仅 `restart` 不会重新读取 `env_file`。

### 4.2 Nginx 日志

`deploy/nginx/nginx.conf` 将日志写入容器内：

- `/var/log/nginx/access.log`
- `/var/log/nginx/error.log`

Docker 日志里通常只看到 Nginx 启动/错误输出，访问日志需要进入容器查看：

```bash
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  exec nginx tail -n 200 /var/log/nginx/access.log

docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  exec nginx tail -n 200 /var/log/nginx/error.log
```

**注意**：这些文件位于容器可写层，容器重建后会丢失。若需要持久化或接入日志平台，建议在 `deploy/docker-compose.prod.yml` 的 `nginx` 服务增加宿主机日志卷（例如将 `/var/log/nginx` 挂载到宿主机目录），或在 Nginx 配置中将 `access_log` 指向 `/dev/stdout`。修改后必须执行 `nginx -t` 再 reload/重建容器。

### 4.3 需要重点关注的日志

| 关键字/事件 | 含义 | 处理 |
| --- | --- | --- |
| `启动初始化完成`（INFO） | 管理员/默认配置初始化结果 | 正常信息；若新建管理员异常，核对 `.env` |
| `应用启动完成`（INFO） | FastAPI 生命周期启动成功 | 每次启动一条；重复说明容器在重启 |
| `微信登录成功` / `手机号绑定成功`（INFO） | 用户登录或绑定手机号，含 `user_id` / `mobile` | 频繁重复或手机号异常时排查对应用户 |
| `管理员登录成功` / `管理员登录失败`（INFO/WARNING） | 后台登录，含 `admin_id` / `account` 与失败原因 | 连续失败需排查暴力尝试 |
| `订单创建成功`（INFO） | 用户提交订单，含订单号、账号与手机号 | 用户反馈支付问题时按订单号检索 |
| `支付成功并发课` / `重复支付回调已幂等处理`（INFO） | 支付回调结果，含订单号、账号与手机号 | `repaired=true` 表示授权异常后补齐 |
| `赠课成功` / `赠课跳过（已拥有）`（INFO） | 后台赠课结果，含管理员账号与目标手机号 | 重复赠课属幂等，不产生新授权 |
| `播放鉴权失败`（WARNING） | 未购买、未生效或已过期的播放请求 | 结合 `reason` 判断是否为过期或未购买 |
| `学习进度落库任务已启动`（INFO） | 进程内进度任务已启动 | 每个 FastAPI 实例只应出现一次 |
| `学习进度落库完成：N 条`（INFO） | 本轮落库数量 | 定期少量属正常 |
| `学习进度落库任务执行失败，将在下一周期重试` | Redis/MySQL 异常 | 查 MySQL/Redis 与磁盘 |
| `学习进度落库任务意外退出` | 协程异常终止 | 重启 FastAPI；检查 stack trace |
| `学习进度写入 Redis 失败` | 客户端上报丢失 | 恢复 Redis；不影响播放 |
| `微信支付回调验签未通过` | 签名/证书/API v3 密钥问题 | 查支付配置与微信平台 |
| `微信支付私钥文件不存在` | 私钥未挂载 | 查 `deploy/secrets/` 与 Compose secret |
| `忽略非支付成功回调事件` | 非成功事件，正常 | 一般不处理 |
| `学习进度批量落库失败` | MySQL 写入失败 | 查数据库、连接池、磁盘 |
| `401`/`403` 集中出现 | 前后端 Token 混用或密钥变更 | 查 Nginx/API 日志与前端版本 |

日志中不应出现完整 Token、管理员密码、微信 AppSecret、支付 API v3 密钥、商户私钥。手机号为业务排查所需的个人信息，应按敏感数据管理；若发现密码或密钥出现在日志中，按安全事件处理并轮换对应密钥。

### 4.4 Docker 日志轮转

Docker 默认 `json-file` 驱动不限制大小，长期运行可能占满磁盘。建议在宿主机 `/etc/docker/daemon.json` 配置：

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  }
}
```

然后重启 Docker daemon：

```bash
sudo systemctl restart docker
```

该配置只对**新创建**的容器生效；发布或 `docker compose up -d --force-recreate` 后生效。修改 Docker 日志配置属于基础设施变更，请安排窗口。

---

## 5. 监控与告警

当前仓库没有内置 Prometheus/Grafana/告警系统。上线后至少配置外部拨测与基础资源监控。

### 5.1 必配探针

| 探针 | 地址/命令 | 期望 | 建议频率 |
| --- | --- | --- | --- |
| API 健康 | `GET https://<域名>/api/v1/health` | HTTP 200 | 1 分钟 |
| 后台页面 | `GET https://<域名>/admin/` | HTTP 200 | 5 分钟 |
| 证书有效期 | `openssl s_client -connect <域名>:443 -servername <域名>` | 剩余 >30 天告警 | 每日 |
| 容器状态 | `docker compose ... ps` | 四个服务 healthy | 1 分钟 |
| 磁盘 | `df -h` | 使用率 >80% 告警 | 5 分钟 |
| 内存/CPU | 云监控或 node_exporter | 持续高位告警 | 1 分钟 |

### 5.2 容器与依赖检查

```bash
cd /opt/huahuo-spark
COMPOSE_FILE=deploy/docker-compose.prod.yml

# 容器健康状态
docker compose --env-file .env -f "$COMPOSE_FILE" ps

# MySQL ping（密码只在容器内展开，不写入宿主机命令行）
docker compose --env-file .env -f "$COMPOSE_FILE" exec -T mysql sh -c \
  'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqladmin ping -h 127.0.0.1 -uroot --silent'

# Redis ping
docker compose --env-file .env -f "$COMPOSE_FILE" exec -T redis redis-cli ping

# FastAPI 容器健康日志
docker inspect --format '{{json .State.Health}}' \
  "$(docker compose --env-file .env -f "$COMPOSE_FILE" ps -q fastapi)"
```

MySQL/Redis 不暴露宿主端口，不要为了监控临时加上公网端口映射。

### 5.3 业务监控

- 支付回调失败/验签失败日志数量；
- 订单状态长期停留在 `pending` 的数量；
- 学习进度落库失败与任务意外退出；
- 管理后台登录失败峰值；
- COS 预签名 403、VOD 播放 403；
- 微信接口超时/证书错误。

### 5.4 告警分级建议

| 级别 | 示例 | 响应 |
| --- | --- | --- |
| P0 | API 持续 5xx、数据库不可用、支付回调持续失败、证书过期 | 立即处理，通知负责人 |
| P1 | 单个容器 unhealthy、磁盘 >90%、进度任务持续失败 | 30 分钟内处理 |
| P2 | 偶发 502、单笔支付异常、COS/VOD 个别失败 | 当日处理 |
| P3 | 日志量异常、备份延迟 | 计划处理 |

---

## 6. 备份与恢复

### 6.1 备份范围

| 数据 | 方式 | 说明 |
| --- | --- | --- |
| MySQL | `mysqldump` 逻辑备份 | 课程、课时、用户、订单、赠课日志、学习记录、系统配置 |
| `.env` | 加密离线备份 | 包含所有生产密钥 |
| TLS 证书与私钥 | 加密离线备份 | 证书可由 CA 重新签发，私钥必须妥善保管 |
| 微信支付私钥 | 加密离线备份 | 丢失会影响下单与回调验签 |
| `nginx.conf`、Compose、部署脚本 | 随代码仓库/发布包归档 | 配置变更需可追溯 |
| `admin-web/dist` | 发布归档 | 支持静态资源回滚 |
| 后端镜像 | `docker save` 或镜像仓库 | 支持跨发布回滚 |
| COS 图片 | COS 版本控制/跨区域复制 | 课程封面等 |
| VOD 视频 | 腾讯云 VOD 存储策略 | 源文件与转码产物 |

**Redis 不是权威数据源**：AOF 只用于减少进度缓冲丢失，不能替代 MySQL 备份。

### 6.2 MySQL 逻辑备份

建议每天至少一次全量备份，并在发布前额外备份。示例脚本保存为 `/usr/local/bin/huahuo-backup-mysql.sh`：

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="/opt/huahuo-spark"
BACKUP_DIR="${PROJECT_DIR}/backups/mysql"
COMPOSE_FILE="deploy/docker-compose.prod.yml"
TS="$(date +%F_%H%M%S)"
OUT="${BACKUP_DIR}/${TS}.sql.gz"

cd "$PROJECT_DIR"
mkdir -p "$BACKUP_DIR"
umask 077

docker compose --env-file .env -f "$COMPOSE_FILE" exec -T mysql sh -c '
  MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot \
    --single-transaction --quick --routines --triggers --events \
    --default-character-set=utf8mb4 "$MYSQL_DATABASE"
' | gzip > "$OUT"

gzip -t "$OUT"
[[ -s "$OUT" ]]
echo "backup ok: $OUT ($(du -h "$OUT" | cut -f1))"
```

执行：

```bash
chmod 700 /usr/local/bin/huahuo-backup-mysql.sh
/usr/local/bin/huahuo-backup-mysql.sh
```

验证备份内容（至少检查表结构结尾与大小，不要只看退出码）：

```bash
gzip -cd backups/mysql/<时间戳>.sql.gz | head -n 30
gzip -cd backups/mysql/<时间戳>.sql.gz | tail -n 30
```

建议 cron：

```cron
# 每天 03:17 全量备份（时间按业务低峰调整）
17 3 * * * /usr/local/bin/huahuo-backup-mysql.sh >> /var/log/huahuo-backup.log 2>&1
```

### 6.3 备份保留与异地

- 本地保留最近 7 天日备、4 份周备；
- 至少一份加密备份传到异地/对象存储，且与生产账号权限隔离；
- 定期检查备份完整性，不要等到恢复时才发现文件损坏；
- 数据库备份包含用户手机号与订单信息，必须加密、限权、审计访问。

加密示例（GPG 公钥加密，私钥离线保存）：

```bash
cd /opt/huahuo-spark
umask 077

LATEST="$(ls -1t backups/mysql/*.sql.gz | head -n 1)"
gpg --encrypt --recipient <运维公钥ID> \
  --output "${LATEST}.gpg" "$LATEST"

# 验证加密包可解密后再删除明文
gpg --decrypt "${LATEST}.gpg" | gzip -t
shred -u "$LATEST"
```

不要使用可逆的“伪加密”脚本；不要把私钥和备份放在同一台机器。加密后的备份不要放在 Web 可访问目录。

### 6.4 配置与密钥备份

```bash
cd /opt/huahuo-spark
umask 077
TS="$(date +%F_%H%M%S)"

tar -czf "backups/config-${TS}.tar.gz" \
  .env \
  deploy/nginx/certs \
  deploy/secrets \
  deploy/nginx/nginx.conf \
  deploy/docker-compose.prod.yml

gpg --symmetric --cipher-algo AES256 \
  "backups/config-${TS}.tar.gz"

# 确认加密包可解密后删除明文压缩包
gpg --decrypt "backups/config-${TS}.tar.gz.gpg" | tar -tzf - >/dev/null
shred -u "backups/config-${TS}.tar.gz"
```

加密后的文件再复制到离线介质或密钥管理服务。验证恢复时必须能在隔离环境解密，而不是只在原机测试。

### 6.5 MySQL 恢复

> 恢复会覆盖当前数据。操作前：停止 FastAPI、生成当前库的“恢复前备份”、确认备份文件与恢复目标，最好先在预发环境演练。

```bash
cd /opt/huahuo-spark
COMPOSE_FILE=deploy/docker-compose.prod.yml
BACKUP_FILE="backups/mysql/<时间戳>.sql.gz"

# 1. 停止 API，避免恢复期间写入
docker compose --env-file .env -f "$COMPOSE_FILE" stop fastapi

# 2. 恢复前备份当前库（即使当前库已损坏，也保留现场）
docker compose --env-file .env -f "$COMPOSE_FILE" exec -T mysql sh -c '
  MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot \
    --single-transaction --quick --routines --triggers --events \
    --default-character-set=utf8mb4 "$MYSQL_DATABASE"
' | gzip > "backups/mysql/pre-restore-$(date +%F_%H%M%S).sql.gz"

# 3. 清空并重建目标库（会删除库内全部表，确认无误后执行）
docker compose --env-file .env -f "$COMPOSE_FILE" exec -T mysql sh -c '
  MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -e \
    "DROP DATABASE IF EXISTS \`$MYSQL_DATABASE\`; \
     CREATE DATABASE \`$MYSQL_DATABASE\` \
       CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
'

# 4. 导入备份
gzip -cd "$BACKUP_FILE" | \
  docker compose --env-file .env -f "$COMPOSE_FILE" exec -T mysql sh -c '
    MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot \
      --default-character-set=utf8mb4 "$MYSQL_DATABASE"
'

# 5. 清理 Redis 中的进度缓冲，避免旧位置覆盖恢复后的 MySQL
docker compose --env-file .env -f "$COMPOSE_FILE" exec -T redis sh -c '
  redis-cli --scan --pattern "study:progress:*" | while IFS= read -r key; do
    redis-cli DEL "$key" >/dev/null
  done
  redis-cli DEL study:progress:dirty
'

# 6. 启动 API
docker compose --env-file .env -f "$COMPOSE_FILE" start fastapi

# 7. 校验
curl -fsS "https://<你的域名>/api/v1/health"
docker compose --env-file .env -f "$COMPOSE_FILE" logs --tail=100 fastapi
```

恢复后必须核对：

- Alembic 版本：`docker compose ... exec -T fastapi alembic current`；
- 管理员能否登录；
- 课程、订单、赠课日志、用户课程是否与备份点一致；
- 备份点之后的支付订单是否丢失。若订单已在微信支付成功但数据库中为 `pending`/不存在，需按微信商户平台流水人工核对并处理，不能只依赖用户投诉。

**为什么必须清理 Redis 进度**：进度落库任务会把 Redis 中更新的播放位置写回 MySQL。数据库回退后若 Redis 仍保留较新的位置，会在下一轮落库时覆盖恢复后的学习记录。清理后由客户端重新上报即可。

### 6.6 Redis 恢复

Redis 仅缓存学习进度：

- 故障期间播放与购买不受影响，新进度上报会失败并记录 `学习进度写入 Redis 失败`；
- 恢复后无需从备份恢复即可继续服务，丢失的只是故障期间的进度缓冲；
- 如 Redis 数据损坏，可在 FastAPI 停止时清空 `huahuo-spark-prod_redis_prod_data`（会丢失进度缓冲，**不影响** MySQL 已落库记录）；
- 不要删除 Redis 卷后再指望已落库的进度回填；以 MySQL 为准。

### 6.7 恢复演练

至少每季度一次：

1. 在隔离环境启动同版本 MySQL/Redis；
2. 使用加密备份恢复；
3. 启动后端，执行迁移 `alembic upgrade head`；
4. 跑 [docs/TEST_CASE.md](docs/TEST_CASE.md) 的 P0 用例；
5. 记录恢复耗时（RTO）与可接受的数据丢失窗口（RPO），更新本手册。

---

## 7. 回滚与故障处理

### 7.1 `deploy.sh` 自动回滚行为

部署失败时，脚本会：

- 恢复 `admin-web/dist.prev`（如果存在）；
- 用 `huahuo-spark-fastapi:rollback` 重建 FastAPI；
- 强制重建 Nginx（静态目录 inode 变化）；
- 等待 FastAPI/Nginx 健康检查；
- 提示数据库迁移不会自动回退。

不会自动回滚：

- 已执行的 Alembic 迁移；
- MySQL/Redis 数据变更；
- 已上传的 COS 文件与 VOD 资源；
- 已发出的支付/赠课业务数据。

成功部署后脚本会删除 `dist.prev`，因此**跨发布回滚必须依赖第 3.4 节的版本归档**。

### 7.2 手动回滚后端镜像

前提：确认目标镜像仍存在（发布时归档或本地 tag 未清理）。

```bash
cd /opt/huahuo-spark
COMPOSE_FILE=deploy/docker-compose.prod.yml

# 查看可用镜像
docker image ls huahuo-spark-fastapi

# 若镜像只存在于归档，先载入
# gunzip -c backups/releases/fastapi-<时间戳>.tar.gz | docker load

# 使用指定版本镜像
export RELEASE_TAG="<目标版本tag>"
docker compose --env-file .env -f "$COMPOSE_FILE" up -d --no-deps fastapi

# 等待健康
docker compose --env-file .env -f "$COMPOSE_FILE" ps
curl -fsS "https://<你的域名>/api/v1/health"
```

如果目标版本早于当前数据库迁移，旧代码可能因表结构不匹配而启动失败。此时只有两条路：

1. 前向修复新版本；
2. 用数据库备份恢复到旧版本对应的数据点（见 6.5），并接受备份点之后的数据丢失。

### 7.3 手动回滚后台静态资源

```bash
cd /opt/huahuo-spark
COMPOSE_FILE=deploy/docker-compose.prod.yml

# 假设已归档 admin-dist-<时间戳>.tar.gz
rm -rf admin-web/dist
mkdir -p admin-web/dist
tar -xzf backups/releases/admin-dist-<时间戳>.tar.gz -C admin-web

# 静态目录变化后必须重建 Nginx
docker compose --env-file .env -f "$COMPOSE_FILE" up -d --no-deps --force-recreate nginx

curl -fsS -o /dev/null "https://<你的域名>/admin/"
```

回滚后台时确认其调用的 `/api/v1` 与新后端版本兼容。

### 7.4 API 502/504

排查顺序：

```bash
cd /opt/huahuo-spark
COMPOSE_FILE=deploy/docker-compose.prod.yml

docker compose --env-file .env -f "$COMPOSE_FILE" ps
docker compose --env-file .env -f "$COMPOSE_FILE" logs --tail=200 fastapi
docker compose --env-file .env -f "$COMPOSE_FILE" logs --tail=200 nginx
docker compose --env-file .env -f "$COMPOSE_FILE" logs --tail=200 mysql
docker compose --env-file .env -f "$COMPOSE_FILE" logs --tail=200 redis
```

常见原因：

- FastAPI 容器未 healthy（启动初始化失败、迁移未跑、数据库不可用）；
- MySQL/Redis 未 healthy；
- 磁盘满、内存不足、容器被 OOM kill；
- Nginx 刚重建/配置错误；
- 上游超时（长事务、数据库锁）。

处理：

```bash
# 单服务重启（不会新建镜像）
docker compose --env-file .env -f deploy/docker-compose.prod.yml restart fastapi
docker compose --env-file .env -f deploy/docker-compose.prod.yml restart nginx
```

不要通过增加 FastAPI 副本“扛住”故障；先修复根本原因。若需要临时降低流量，优先在 Nginx/云负载层限流。

### 7.5 FastAPI 崩溃/启动失败

```bash
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  logs --tail=300 fastapi
```

重点检查：

1. `.env` 是否被误改（密钥长度、API v3 密钥 32 字节、回调 HTTPS、进度周期 < TTL）；
2. 数据库迁移是否执行：

   ```bash
   # 容器还能执行命令时
   docker compose --env-file .env -f deploy/docker-compose.prod.yml \
     exec fastapi alembic current
   docker compose --env-file .env -f deploy/docker-compose.prod.yml \
     exec fastapi alembic heads
   ```

   如果 FastAPI 已无法启动，先确认当前部署镜像 tag，再以该 tag 运行一次性容器（不要依赖默认 `latest`，生产镜像通常按发布时间打 tag）：

   ```bash
   docker inspect --format '{{.Config.Image}}' \
     "$(docker compose --env-file .env -f deploy/docker-compose.prod.yml ps -q fastapi)"

   RELEASE_TAG="<上一步输出中的tag>" \
     docker compose --env-file .env -f deploy/docker-compose.prod.yml \
     run --rm --no-deps fastapi alembic current
   ```
3. 微信支付私钥是否挂载到容器内且可读；
4. 初始管理员不存在且未配置 `ADMIN_INITIAL_PASSWORD` 会导致启动失败；
5. MySQL 是否可达、账号密码是否正确、数据库是否已创建；
6. 端口占用或 Nginx 配置错误不影响 FastAPI 启动，但会导致外部不可达。

### 7.6 MySQL 故障

```bash
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  logs --tail=300 mysql
docker compose --env-file .env -f deploy/docker-compose.prod.yml ps mysql
df -h
docker stats --no-stream
```

- 若因磁盘满：先清理可安全删除的内容（旧备份、已归档日志），不要删除 MySQL 数据卷；
- 若 MySQL 损坏：停止 FastAPI，按 6.5 恢复；
- 若只是连接池耗尽/长事务：查 `SHOW PROCESSLIST` 与慢查询，终止异常会话前确认业务影响；
- 任何情况下都不要执行 `docker compose down -v`。

### 7.7 Redis 故障

- 表现为进度上报失败、进度落库任务报错；播放/购买/支付仍可使用；
- 检查 `docker compose logs redis`、磁盘、内存；
- 重启 Redis：`docker compose ... restart redis`；
- 若 AOF 损坏，可在确认可以丢失进度缓冲后清空 Redis 数据卷；MySQL 中已落库进度不受影响；
- Redis 恢复后进度任务会在下一周期继续处理仍存在的脏集合；已丢失的缓冲无法恢复。

### 7.8 支付回调失败

排查：

1. 请求是否到达 Nginx/FastAPI：查访问日志中的 `/api/v1/payments/wechat/notify`；
2. HTTP 状态与响应体是否符合微信要求（`SUCCESS`/`FAIL`）；
3. 验签失败：核对 `WECHAT_PAY_API_V3_KEY`、API 证书序列号、商户私钥是否匹配当前商户号；
4. 商户号/AppID 不一致：回调中的 `mchid`、`appid` 必须与配置一致；
5. 金额不一致：订单金额（分）与微信支付金额不一致时回调会被拒绝；
6. 订单不存在：检查 `out_trade_no` 是否为本系统订单；
7. 重复回调：已支付订单重复回调应返回成功且不重复发课；若日志出现重复入账，按 P0 处理并核对 `user_course`、`orders`、赠课日志。

不要用伪造签名或手工 `curl` 重放支付回调来“测试生产”；需要重试时使用微信商户平台的回调重试能力或小额真实交易。

### 7.9 管理后台登录异常

- 确认使用的管理员账号不是小程序用户；
- 修改 `ADMIN_INITIAL_PASSWORD` 不会重置已有管理员；
- 查看后端日志是否有 401/403；C 端 Token 不能访问后台（会返回 403）；
- 管理员 Token 默认 8 小时过期；过期后重新登录；
- 浏览器 localStorage 中残留旧会话时，清除后重登。

### 7.10 管理员密码重置

密码以 bcrypt 哈希存储，数据库中不保存明文。重置步骤：

```bash
cd /opt/huahuo-spark
COMPOSE_FILE=deploy/docker-compose.prod.yml

# 1. 生成 bcrypt 哈希（在容器内交互输入密码，避免明文进入 shell 历史）
docker compose --env-file .env -f "$COMPOSE_FILE" exec fastapi python -c \
  'import getpass; from app.core.security import hash_password; print(hash_password(getpass.getpass("新密码: ")))'
```

复制输出的哈希（形如 `$2b$12$...`），然后更新数据库：

```bash
docker compose --env-file .env -f "$COMPOSE_FILE" exec -T mysql sh -c \
  'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot "$MYSQL_DATABASE"' <<'SQL'
UPDATE admin_users
SET password_hash = '在此粘贴 bcrypt 哈希'
WHERE username = '在此填写管理员用户名';
SQL
```

注意：

- 哈希包含 `$`，必须使用单引号 SQL 字面量；不要把哈希放进双引号 shell 字符串；
- 不要手工构造 `$2b$` 哈希，必须用后端同一套 bcrypt 参数；
- 重置密码**不会**使已签发的 Admin Token 立即失效（JWT 无状态）。如需强制所有后台会话下线，轮换 `ADMIN_JWT_SECRET` 并重建 FastAPI（见 8.3）；
- 操作前后确认更新行数；生产操作建议两人复核。

### 7.11 证书过期/更换

```bash
cd /opt/huahuo-spark

# 替换 fullchain.pem / privkey.pem 后
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  exec nginx nginx -t
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  exec nginx nginx -s reload

# 校验
openssl s_client -connect <你的域名>:443 -servername <你的域名> </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -dates
```

`deploy.sh` 默认校验证书链（可用 `CURL_INSECURE=1` 临时跳过），但不能代替证书到期监控。

### 7.12 磁盘空间不足

```bash
df -h
docker system df
docker image ls
du -sh /opt/huahuo-spark/backups/*
```

可安全清理：

- 已归档到异地的旧备份；
- 无用的旧镜像（确认不是当前/回滚版本）；
- 轮转后的 Docker 日志。

不要清理 MySQL/Redis 数据卷、正在使用的证书、`deploy/secrets/`。

---

## 8. 常规运维操作

### 8.1 服务启停

```bash
cd /opt/huahuo-spark
COMPOSE_FILE=deploy/docker-compose.prod.yml

# 启动全部服务
docker compose --env-file .env -f "$COMPOSE_FILE" up -d

# 停止全部服务（保留数据卷）
docker compose --env-file .env -f "$COMPOSE_FILE" stop

# 重启单个服务
docker compose --env-file .env -f "$COMPOSE_FILE" restart fastapi

# 查看状态
docker compose --env-file .env -f "$COMPOSE_FILE" ps
```

修改 `.env` 后需要重建 FastAPI 才能加载新值：

```bash
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  up -d --no-deps --force-recreate fastapi
```

修改 Nginx 配置后：

```bash
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  exec nginx nginx -t
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  up -d --no-deps --force-recreate nginx
```

### 8.2 数据库迁移

发布时由 `deploy.sh` 自动执行 `alembic upgrade head`。手工操作：

```bash
cd /opt/huahuo-spark
COMPOSE_FILE=deploy/docker-compose.prod.yml

# 查看当前版本（先备份数据库）
docker compose --env-file .env -f "$COMPOSE_FILE" \
  exec fastapi alembic current

# 查看是否有待执行迁移
docker compose --env-file .env -f "$COMPOSE_FILE" \
  exec fastapi alembic heads

# 执行迁移
docker compose --env-file .env -f "$COMPOSE_FILE" \
  exec fastapi alembic upgrade head
```

`exec` 在**正在运行**的 FastAPI 容器内执行，使用的就是当前部署镜像。若容器已无法启动，必须先确认当前镜像 tag，再显式带上 `RELEASE_TAG` 运行一次性容器：

```bash
# 1. 读取当前容器使用的镜像
CURRENT_IMAGE="$(docker inspect --format '{{.Config.Image}}' \
  "$(docker compose --env-file .env -f "$COMPOSE_FILE" ps -q fastapi)")"
echo "$CURRENT_IMAGE"

# 2. 用该镜像的 tag 运行，禁止依赖默认 latest
RELEASE_TAG="${CURRENT_IMAGE##*:}" \
  docker compose --env-file .env -f "$COMPOSE_FILE" \
  run --rm --no-deps fastapi alembic upgrade head
```

不要省略 `RELEASE_TAG` 直接 `run --rm`：`docker-compose.prod.yml` 的默认镜像是 `latest`，可能与应用实际运行的版本不一致。

生产禁止随意 `alembic downgrade`。如确需回退，必须先备份、评估数据丢失，并在预发演练。

### 8.3 轮换密钥

| 密钥 | 影响 | 步骤 |
| --- | --- | --- |
| `USER_JWT_SECRET` | 所有小程序用户 Token 失效，需要重新静默登录 | 更新 `.env` → 重建 FastAPI → 观察登录 |
| `ADMIN_JWT_SECRET` | 所有后台会话失效 | 更新 `.env` → 重建 FastAPI → 管理员重新登录 |
| 微信支付 API v3 密钥 | 支付回调验签失败，可能导致支付状态不更新 | 在商户平台与 `.env` 同步轮换，安排支付低峰窗口，核对回调 |
| 微信支付私钥/证书 | 下单与回调验签失败 | 在商户平台重签证书，替换 `deploy/secrets/`，重建 FastAPI |
| 小程序 AppSecret | 微信登录失败 | 公众平台重置后更新 `.env`，重建 FastAPI |
| 腾讯云 SecretId/SecretKey | 图片预签名/播放签名失败 | 在 CAM 轮换，更新 `.env`，重建 FastAPI |
| VOD 播放密钥 | 视频播放签名失效 | 更新 VOD 与 `.env`，重建 FastAPI |

轮换后必须验证：小程序登录、后台登录、支付回调、图片上传、视频播放。

### 8.4 第三方配置变更

- 微信支付回调地址变更：同时修改商户平台与 `WECHAT_PAY_NOTIFY_URL`，重建 FastAPI，用真实小额支付验证；
- COS 域名/CORS 变更：更新 `COS_PUBLIC_BASE_URL`，重建 FastAPI，在后台验证图片上传与展示；
- VOD 防盗链/密钥变更：同步更新 VOD 与 `VOD_PLAY_KEY`，真机验证 `psign` 播放；
- 小程序 request 合法域名变更：在公众平台配置后重新发布/体验版验证。

### 8.5 数据查询与导出

- 订单查询用后台只读接口；不要在数据库直接改订单状态；
- 赠课只通过后台发放，保证日志留痕；
- 需要导出用户手机号/订单时，按最小必要原则审批，导出文件加密并限时删除；
- 任何直接 SQL 修改都必须先备份、记录变更、双人复核。

---

## 9. 安全运维

### 9.1 最小暴露面

- 防火墙只开放 22（限 IP）、80、443；
- MySQL/Redis/FastAPI 不对公网暴露；
- 生产不需要 Swagger/ReDoc；Nginx 已对 `/docs`、`/redoc`、`/openapi.json` 返回 404；
- 不要在生产开启调试模式或暴露异常堆栈；
- Nginx 已配置安全响应头、请求体限制与隐藏文件拒绝。

### 9.2 密钥管理

- `.env`、证书私钥、支付私钥权限 600，属主为部署用户/root；
- 密钥只保存在服务器与加密备份中，不进入 Git、镜像、前端 bundle、聊天工具；
- 定期轮换 JWT 密钥、微信支付密钥、腾讯云密钥；
- 离职/交接时轮换所有共享密钥；
- 如怀疑泄露：先轮换密钥并重建服务，再排查日志与访问记录。

### 9.3 审计与留痕

- 赠课操作有 `gift_logs` 留痕；
- 订单后台只读，不提供修改状态能力；
- 发布记录保留版本 tag、操作人、时间、备份文件；
- 生产数据库变更、密钥轮换、回滚均需工单记录。

### 9.4 合规提示

微信小程序涉及用户手机号、支付与学习记录，需按业务所在地法规与微信平台规则处理隐私政策、授权、数据保留与删除请求。本手册不替代法律合规评估。

---

## 10. 已知限制与待改进项

| 限制 | 影响 | 建议 |
| --- | --- | --- |
| 进度落库为进程内任务，FastAPI 单实例 | 无法水平扩容，重启窗口内进度缓冲依赖 Redis | 扩容前拆分独立单实例 Worker 或分布式锁 |
| JWT 无状态，退出登录只清客户端 Token | 已泄露 Token 在过期前仍有效 | 缩短 Admin Token 有效期；轮换密钥强制下线 |
| `deploy.sh` 自动回滚只覆盖镜像与静态资源 | 不恢复数据库；成功后删除 `dist.prev` | 发布前归档镜像/静态资源；数据库单独备份 |
| 数据库迁移只前进 | 回滚代码可能不兼容新表结构 | 迁移需向后兼容，重大变更分批发布 |
| Nginx 访问日志在容器内 | 容器重建后日志丢失 | 挂载日志卷或改为 stdout |
| `deploy.sh` 健康检查忽略证书校验 | 证书过期不会被发布脚本发现 | 外部证书到期监控 |
| 无内置监控/告警/日志平台 | 故障发现依赖外部拨测 | 接入云监控或 Prometheus/Grafana/Loki |
| 无自动备份定时器 | 依赖运维配置 cron | 按第 6 节落地并演练 |
| 支付回调依赖微信重试 | 长时间故障可能导致订单状态滞后 | 监控回调失败；必要时人工对账 |
| VOD 插件 `psign` 需真机验证 | 部分插件版本可能不接受该参数 | 上线前真机验收；禁止退回明文地址 |

---

## 11. 值班速查

```bash
cd /opt/huahuo-spark
COMPOSE_FILE=deploy/docker-compose.prod.yml
DC="docker compose --env-file .env -f $COMPOSE_FILE"

$DC ps
$DC logs --tail=200 -f fastapi
$DC logs --tail=200 nginx
curl -fsS "https://<你的域名>/api/v1/health"
$DC exec -T redis redis-cli ping
$DC exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqladmin ping -h 127.0.0.1 -uroot --silent'
df -h
docker system df
```

出现 P0 时优先顺序：

1. 确认影响范围（API/支付/播放/后台）；
2. 保留现场日志，不要急着重启覆盖证据；
3. 恢复服务优先于定位根因；
4. 若与发布相关，按第 7 节回滚；
5. 涉及支付/数据一致性时，停止进一步写操作并通知负责人；
6. 事后补齐时间线、根因、影响数据与改进项。

---

## 12. 运维验收清单

- [ ] 域名、证书、HTTPS 跳转正常，证书到期有监控
- [ ] 生产 `.env` 已替换全部占位值，权限 600
- [ ] 两套 JWT 密钥不同且 ≥32 字节
- [ ] 初始管理员强密码；已记录密码保管方式
- [ ] 微信小程序/支付/COS/VOD 配置与真机验证完成
- [ ] Nginx Swagger/ReDoc 已 404
- [ ] MySQL/Redis 不对公网暴露
- [ ] FastAPI 只有一个实例
- [ ] 发布前备份、发布后验证流程已演练
- [ ] MySQL 备份 cron 已配置，异地加密备份可恢复
- [ ] 配置/证书/支付私钥加密备份完成
- [ ] 外部健康探针与告警已配置
- [ ] Docker 日志轮转已配置
- [ ] 回滚流程已演练（镜像、静态资源、数据库）
- [ ] 值班联系人、升级路径与商户平台/云厂商账号可访问

---

## 13. 文档验证状态

本文档基于仓库中的 `deploy/`、`backend/`、`admin-web/` 与 `miniprogram/` 实现进行静态核对编写。当前交付环境未安装 Node/npm，也未接入真实 MySQL/Redis/微信支付/腾讯云 COS/VOD，因此以下操作**未在本次交付中实际执行**：

- `deploy.sh` 首次部署与发布；
- MySQL 备份、恢复与 Redis 清理；
- 镜像/静态资源回滚；
- 管理员密码重置、证书续期、密钥轮换；
- 外部拨测、Docker 日志轮转与告警接入。

首次上线前必须在预发环境完整演练第 3、6、7 节，并记录实际耗时、RTO/RPO 与负责人。发现本文与实现不一致时，以仓库代码与 `deploy/` 配置为准，并同时更新本文和 [docs/DEPLOY.md](docs/DEPLOY.md)。
