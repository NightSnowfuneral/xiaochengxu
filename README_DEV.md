# 禾下美学院｜本地开发启动说明

本项目包含三个可独立运行的工程，后端是唯一数据源：

```text
beauty-course-mp/
├─ backend/       FastAPI + MySQL + Redis（API 服务）
├─ admin-web/     React 管理后台（Vite，开发端口 5173）
├─ miniprogram/   Taro 微信小程序（微信开发者工具）
├─ deploy/        Compose、Nginx、部署脚本
└─ docs/          架构、API、部署、测试用例
```

建议启动顺序：**环境变量 → MySQL/Redis → 数据库迁移 → FastAPI → 管理后台 → 小程序**。数据库迁移必须在 FastAPI 首次启动前完成，否则应用启动时会因表不存在而失败。

## 1. 前置依赖

| 工具 | 版本 | 用途 |
| --- | --- | --- |
| Docker Desktop / Docker Engine | 24+，Compose v2 | 推荐方式运行 MySQL、Redis、后端与后台 |
| Python | 3.11 | 不使用 Docker 运行后端时 |
| Node.js | 18+（建议 20 LTS） | 管理后台与小程序构建 |
| 微信开发者工具 | 最新稳定版 | 小程序调试 |
| Git Bash / WSL | - | Windows 下执行 `.sh` 命令 |

小程序真机调试还需要：

- 正式小程序 AppID；
- 微信公众平台配置 request 合法域名（HTTPS）；
- 腾讯云 VOD 插件与 COS 配置（详见 [docs/DEPLOY.md](docs/DEPLOY.md)）。

## 2. 环境变量

在项目根目录创建 `.env`：

```bash
cp .env.example .env
```

至少修改：

```dotenv
MYSQL_ROOT_PASSWORD=<强密码>
MYSQL_PASSWORD=<强密码>
USER_JWT_SECRET=<至少 32 字符，与下面不同>
ADMIN_JWT_SECRET=<至少 32 字符>
ADMIN_INITIAL_USERNAME=admin
ADMIN_INITIAL_PASSWORD=<至少 12 字符，≤72 字节>
```

生成随机值（Git Bash / Linux / macOS）：

```bash
openssl rand -hex 32
openssl rand -hex 32
```

说明：

- `.env` 位于项目根目录，`backend/app/core/config.py` 固定读取它；不要把 `.env` 放到 `backend/` 下。
- 后端启动时会校验：两套 JWT 密钥均 ≥32 字符且互不相同、初始管理员密码 ≥12 字符、API v3 密钥恰好 32 字节、通知地址为 HTTPS、进度落库周期小于 Redis TTL。
- 本地不接支付 / 上传 / 视频时，微信、支付、COS、VOD 变量可以留空；但微信登录、支付、上传、播放相关功能不可用。
- `.env`、`deploy/secrets/`、证书私钥已被 `.gitignore` 忽略，禁止提交。

开发用 Compose 会覆盖容器内的数据库地址：

```text
DATABASE_URL=mysql+aiomysql://...@mysql:3306/...
REDIS_URL=redis://redis:6379/0
```

因此 `.env` 中的 `DATABASE_URL` 可以保持 `127.0.0.1`，供宿主机直接运行后端时使用。

## 3. 推荐启动方式：Docker Compose

以下命令均在**项目根目录**执行。

### 3.1 启动 MySQL / Redis

```bash
docker compose --env-file .env -f deploy/docker-compose.dev.yml \
  up -d --build mysql redis
```

等待健康检查通过：

```bash
docker compose --env-file .env -f deploy/docker-compose.dev.yml ps
```

`mysql` 与 `redis` 的 `STATUS` 应包含 `healthy`。

### 3.2 首次执行数据库迁移

开发 Compose **不会自动执行 Alembic**。首次启动、拉取新代码或新增迁移后，先执行：

```bash
docker compose --env-file .env -f deploy/docker-compose.dev.yml \
  build fastapi

docker compose --env-file .env -f deploy/docker-compose.dev.yml \
  run --rm fastapi alembic upgrade head
```

验证当前版本：

```bash
docker compose --env-file .env -f deploy/docker-compose.dev.yml \
  run --rm fastapi alembic current
```

### 3.3 启动 FastAPI 与管理后台

```bash
docker compose --env-file .env -f deploy/docker-compose.dev.yml \
  up -d fastapi admin-web
```

启动后：

| 服务 | 地址 |
| --- | --- |
| API | <http://127.0.0.1:8000/api/v1> |
| 健康检查 | <http://127.0.0.1:8000/api/v1/health> |
| Swagger（仅开发） | <http://127.0.0.1:8000/docs> |
| ReDoc（仅开发） | <http://127.0.0.1:8000/redoc> |
| 管理后台 | <http://127.0.0.1:5173> |

首次启动后端会：

- 写入默认系统配置（已存在则跳过）；
- 根据 `ADMIN_INITIAL_USERNAME` / `ADMIN_INITIAL_PASSWORD` 创建管理员（仅当用户名不存在）；
- 启动进程内学习进度落库任务（默认每 60 秒一次）。

查看日志：

```bash
docker compose --env-file .env -f deploy/docker-compose.dev.yml logs -f fastapi
docker compose --env-file .env -f deploy/docker-compose.dev.yml logs -f admin-web
```

后端日志默认输出 `INFO` 及以上级别，格式为 `时间 级别 [模块名] 消息`，例如
`2026-11-03 10:00:00 INFO [app.services.pay_service] ...`。可在 `.env` 中用
`LOG_LEVEL=DEBUG|INFO|WARNING|ERROR` 调整；修改后需重建 FastAPI 容器
（`up -d --force-recreate fastapi`），仅 `restart` 不会重新读取 `.env`。

登录、绑定手机号、下单、支付回调、赠课与播放鉴权失败等关键事件会输出
`user_id` / `mobile`，后台操作输出 `admin_id` / `account`，便于定位具体账号。
日志不会输出 Token、密码、请求头或密钥。手机号属于个人信息，开发环境的容器
日志也应限制访问，不要提交到仓库或转发到公开渠道。

> 修改后端代码会自动 reload；修改 `requirements.txt` 或 Dockerfile 后需要重新 `build fastapi`。管理后台源码挂载到容器，Vite 会热更新；`node_modules` 使用命名卷。

### 3.4 停止

```bash
# 停止服务，保留数据卷
docker compose --env-file .env -f deploy/docker-compose.dev.yml down

# 停止并删除数据库 / Redis 开发数据（谨慎）
docker compose --env-file .env -f deploy/docker-compose.dev.yml down -v
```

## 4. 不使用 Docker 的运行方式

适合只想在宿主机跑 Python 调试后端的情况。MySQL 8 / Redis 7 仍需可用，可以只用 Compose 启动基础设施：

```bash
docker compose --env-file .env -f deploy/docker-compose.dev.yml up -d mysql redis
```

然后：

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate     # Git Bash on Windows
# source .venv/bin/activate       # Linux / macOS

pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

要求 `.env` 中：

```dotenv
DATABASE_URL=mysql+aiomysql://spark:<URL编码后的密码>@127.0.0.1:3306/huahuo_spark?charset=utf8mb4
REDIS_URL=redis://127.0.0.1:6379/0
```

注意：

- 密码包含 `@`、`:`、`/`、`?`、`#` 时必须 URL 编码。
- 微信支付私钥/公钥路径若仍是 `/run/secrets/...`，宿主机模式下不存在；需要使用支付时改成宿主机路径。
- 新版商户没有平台证书，必须同时配置 `WECHAT_PAY_PUBLIC_KEY_PATH` 与 `WECHAT_PAY_PUBLIC_KEY_ID`；公钥文件从商户平台「API 安全 → 微信支付公钥」下载。
- `alembic` 必须在 `backend/` 目录运行，配置会读取根目录 `.env`。

## 5. 管理后台单独开发

```bash
cd admin-web
npm install
cp .env.example .env
npm run dev
```

- 地址：<http://127.0.0.1:5173>
- `VITE_API_BASE_URL` 默认 `http://127.0.0.1:8000/api/v1`。
- 后端 `CORS_ALLOW_ORIGINS` 默认允许 `http://127.0.0.1:5173` 与 `http://localhost:5173`；改端口时需同步修改后端否则会被 CORS 拦截。
- 登录账号来自后端首次启动创建的管理员。
- 修改 `.env` 后需要重启 Vite。

常用检查：

```bash
npm run typecheck
npm run build
```

生产构建必须使用 `/admin/` 基础路径：

```bash
VITE_API_BASE_URL=/api/v1 npm run build -- --base=/admin/
```

## 6. 微信小程序开发

```bash
cd miniprogram
npm install
TARO_APP_API_BASE_URL=http://127.0.0.1:8000/api/v1 npm run dev:weapp
```

如果 npm 10 安装阶段报 `Cannot read properties of null (reading 'edgesOut')`，改用：

```bash
npm install --legacy-peer-deps
```

Taro 4.3 的 React Babel 预设已显式声明为 `@babel/preset-react`，不需要手动补装。

然后：

1. 打开微信开发者工具，「导入项目」选择 `miniprogram` 目录；
2. 项目读取 `project.config.json` 的 `miniprogramRoot: dist/`，因此必须先构建出 `dist/`；
3. 本地调试勾选「不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书」，或保留现有 `urlCheck: false`；
4. 将 `project.config.json` 的 `appid` 替换成自己的测试/正式 AppID；`touristappid` 只能看界面，不能验证支付与 VOD。

生产构建（直连已部署服务器）：

```bash
npm run build:weapp:online   # 内置 https://api.qinghebacademy.cn/api/v1
```

恢复本地调试构建：

```bash
TARO_APP_API_BASE_URL=http://127.0.0.1:18000/api/v1 npm run build:weapp
```

说明：

- `TARO_APP_API_BASE_URL` 在 Taro 构建时注入，**建议在命令前显式设置环境变量**；`miniprogram/.env.example` 仅作为值参考，不保证 Taro CLI 自动加载。
- `dist/` 是上一次构建的产物：执行 `build:weapp:online` 后开发者工具会请求生产服务器；想回到本地后端需重新执行上面的本地构建命令。
- 开发模式自带模拟登录兜底；模拟 Token 不请求真实业务接口，接口 401 属于预期。生产构建会通过 alias 移除模拟登录与模拟用户。
- 真机不能访问 `127.0.0.1`；真机联调需要局域网 IP + 关闭域名校验，或使用 HTTPS 测试域名。
- 微信登录需要真实的 `WECHAT_APP_ID` / `WECHAT_APP_SECRET`；否则请仅使用模拟登录验证页面交互。
- VOD 插件 `psign` 兼容性、支付与手机号授权必须用正式 AppID 真机验证，详见 [miniprogram/README.md](miniprogram/README.md) 与 [docs/DEPLOY.md](docs/DEPLOY.md)。

## 7. 后端测试

测试使用 SQLite 文件库、FakeRedis，并 mock 微信与 VOD，不依赖 MySQL / Redis：

```bash
cd backend
python -m pytest -q
```

覆盖：

- 管理员登录与 C 端 Token 访问 Admin 返回 403；
- 微信登录幂等、手机号绑定；
- 同手机号 + 课程赠课只发一次、未绑定手机号无法赠课；
- 重复支付回调只发课一次；
- 播放鉴权必须拥有课程；
- 公开配置读取、配置写入必须 Admin。

测试文件位于 `backend/tests/`，具体映射见 [docs/TEST_CASE.md](docs/TEST_CASE.md)。

## 8. 常用开发命令

```bash
# 查看迁移历史
cd backend && alembic history

# 新建迁移（模型改动后）
cd backend && alembic revision --autogenerate -m "describe change"

# 执行迁移
cd backend && alembic upgrade head

# 回退一版迁移（仅开发环境；生产默认不做自动回退）
cd backend && alembic downgrade -1

# 重新构建后端镜像
docker compose --env-file .env -f deploy/docker-compose.dev.yml build fastapi

# 只重启 FastAPI
docker compose --env-file .env -f deploy/docker-compose.dev.yml restart fastapi
```

## 9. 本地接口速查

| 接口 | 说明 |
| --- | --- |
| `GET /api/v1/health` | 健康检查 |
| `GET /api/v1/config` | 公开系统配置（免 JWT） |
| `POST /api/v1/client/auth/wx-login` | 小程序静默登录 |
| `POST /api/v1/admin/auth/login` | 管理员登录 |
| `GET /api/v1/client/courses` | 课程广场 |
| `POST /api/v1/client/orders` | 创建订单 |
| `POST /api/v1/payments/wechat/notify` | 微信支付回调（仅微信签名） |

完整字段、错误码与鉴权规则见 [docs/API.md](docs/API.md)。

## 10. 常见问题

### 10.1 FastAPI 启动即退出 / 报数据表不存在

首次启动前没有执行迁移。先运行：

```bash
docker compose --env-file .env -f deploy/docker-compose.dev.yml \
  run --rm fastapi alembic upgrade head
```

### 10.2 管理后台登录 401 / 一直跳登录页

- 确认使用的是管理员账号密码，不是小程序用户；
- 确认 `ADMIN_INITIAL_PASSWORD` 是首次启动时的值；修改环境变量不会重置已存在管理员；
- 确认浏览器 localStorage 中没有旧的 `spark.admin.session.v1`，必要时清除后重登；
- 确认没有把 C 端 Token 填到后台会话中（两套 JWT 隔离，互不通用）。

### 10.3 管理后台请求被 CORS 拦截

- 后端 `CORS_ALLOW_ORIGINS` 必须包含实际访问源（含协议与端口）；
- 同一源部署时不要带路径或通配符；
- 修改 `.env` 后重启 FastAPI。

### 10.4 小程序一直提示登录 / 401

- 开发环境模拟登录只用于页面守卫，真实接口仍会返回 401；
- 必须配置真实 `WECHAT_APP_ID` / `WECHAT_APP_SECRET` 才能完成 `wx.login`；
- 真机需使用 HTTPS 域名或正确配置局域网调试；`127.0.0.1` 在手机上指向手机自身。

### 10.5 图片上传失败

- 检查 COS 桶 CORS 是否允许后台 Origin、`PUT` 方法与 `Content-Type`；
- 检查 `COS_PUBLIC_BASE_URL` 是否可公网访问；
- 上传请求不要带 Admin Token；
- 仅支持 JPG / JPEG / PNG / WebP，单张不超过 10 MB；
- 预签名有效期 60–3600 秒，过期后重新申请。

### 10.6 视频无法播放

- 确认用户已购买 / 已获赠课程；
- 确认 VOD 已配置 `VOD_APP_ID`、`VOD_PLAY_KEY` 与 Key 防盗链；
- 确认课时 `vod_file_id` 正确、视频已转码；
- 确认微信插件已申请且 License 有效；
- 若插件不接受 `psign`，需按腾讯云官方方案调整，禁止改为明文地址。

### 10.7 MySQL 端口冲突

修改 `.env`：

```dotenv
MYSQL_PORT=3307
REDIS_PORT=6380
```

并同步调整宿主机模式下 `DATABASE_URL` / `REDIS_URL` 的端口；Compose 内部仍使用服务名与默认 port。

### 10.8 Windows 下文件监听异常

开发 Compose 已为管理后台设置 `CHOKIDAR_USEPOLLING=true`。若 Taro 构建在 Windows 上出现文件锁或路径问题，建议使用 Git Bash / WSL，并避免在 OneDrive 同步目录中运行。

## 11. 本地验证记录（2026-10-28）

已在 Docker 中完成一轮本地验证（Python 3.11、Node 20、MySQL 8、Redis 7）：

- `backend/requirements.txt` 补入测试依赖 `aiosqlite` 后，后端 pytest：**7 passed**；
- 启动真实 MySQL / Redis / FastAPI，执行模拟微信登录、手机号绑定、模拟支付、COS 预签名与 VOD 签名，C 端 + B 端端到端流程：**54 项检查全部通过**；
- 管理后台 `tsc --noEmit` 与 Vite 生产构建通过，`/admin/` 静态产物可正常访问；
- 小程序 `tsc --noEmit` 与 Taro 生产构建通过，生产包中未检出开发模拟登录代码。

本轮**未验证**以下依赖真实外部环境的能力，上线前仍需补测：

- 真实微信 `code2Session` / `getPhoneNumber` 与微信支付统一下单、平台证书验签；
- 腾讯云 COS 实际 PUT 上传与公网访问（仅验证了预签名生成）；
- 腾讯云 VOD 真机插件 `psign` 播放、加密转码与防盗链；
- 微信开发者工具中的页面交互、真机支付与手机号授权。

首次在具备 Node 18+、Python 3.11、Docker 的环境拉取代码后，请严格按本文顺序执行，并优先完成 [docs/TEST_CASE.md](docs/TEST_CASE.md) 中的 P0 用例。
