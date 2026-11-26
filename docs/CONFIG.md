# 禾下美学院｜账号 / 密钥 / 地址配置清单

> **本文档不包含任何真实密钥。**
> 所有敏感值只记录「变量名 + 存放位置 + 获取方式」，请在服务器 `.env` 或对应控制台查看。
> `.env.example` 只允许保留占位符；`.env`、`deploy/secrets/`、`deploy/nginx/certs/` 已被 `.gitignore` 排除，禁止提交。

- 整理日期：2026-10-30
- 生产环境：`APP_ENV=production`，部署目录 `/opt/huahuo-spark`
- 相关文档：[DEPLOY.md](DEPLOY.md)（部署流程）、[API.md](API.md)（接口定义）

---

## 1. 访问地址

### 1.1 生产环境

| 用途 | 地址 | 说明 |
| --- | --- | --- |
| API 根地址 | `https://api.qinghebacademy.cn/api/v1` | 小程序与后台共用 |
| 健康检查 | `https://api.qinghebacademy.cn/api/v1/health` | 部署脚本与监控使用 |
| 管理后台 | `https://api.qinghebacademy.cn/admin/` | 静态资源由 Nginx 提供 |
| 管理员登录接口 | `POST https://api.qinghebacademy.cn/api/v1/admin/auth/login` | 免 Admin JWT |
| C 端微信登录接口 | `POST https://api.qinghebacademy.cn/api/v1/auth/wx-login` | 免 JWT，见 [API.md](API.md) |
| 微信支付回调 | `https://api.qinghebacademy.cn/api/v1/payments/wechat/notify` | 不走 JWT，只校验微信签名 |
| 小程序播放完成回调 | `https://api.qinghebacademy.cn/api/vod/finish-lesson` | 注意**不带** `/v1`，固定挂在 `/api/vod` |
| 小程序 request 合法域名 | `https://api.qinghebacademy.cn` | 只填 origin，不带路径、端口、IP |
| COS 对象公网前缀 | `https://hexiameixueyuan-1518742118.cos.ap-guangzhou.myqcloud.com` | `COS_PUBLIC_BASE_URL` |
| 服务器 | `124.220.162.138:22`（用户 `ubuntu`） | 本地 SSH 别名 `beauty`，配置在 `D:/ssh/config` |

> 域名未完成 ICP 备案前，PC 端访问域名会出现 TLS 重置（约 2/10 成功率）；临时可用 `https://124.220.162.138/...`（证书警告、仅供内部测试）。小程序正式版**必须**使用备案域名。

### 1.2 本地开发（当前实际端口，与 README 的 8000/5173 不同）

宿主机 8000 端口被其他项目占用，本地改用：

| 用途 | 地址 | 说明 |
| --- | --- | --- |
| API | `http://127.0.0.1:18000/api/v1` | 容器 `huahuo-spark-fastapi-local`，映射 `18000:8000` |
| Swagger | `http://127.0.0.1:18000/docs` | FastAPI 默认开启；生产 Nginx 只代理 `/api/` 与 `/admin/`，公网 `/docs` 返回 404 |
| 管理后台 | `http://127.0.0.1:15173` | 容器 `huahuo-admin-dev`，映射 `15173:5173` |
| MySQL | `127.0.0.1:3306` | 容器 `huahuo-spark-dev-mysql-1` |
| Redis | `127.0.0.1:6380` | 容器 `huahuo-spark-dev-redis-1` |
| 小程序 API 基址 | `http://<局域网IP>:18000/api/v1` | 真机调试用，换网络后需重新构建 |
| 小程序模拟器 | `http://127.0.0.1:18000/api/v1` | `urlCheck: false` |

### 1.3 第三方控制台

| 平台 | 地址 | 用途 |
| --- | --- | --- |
| 微信公众平台（小程序） | <https://mp.weixin.qq.com> | AppID/AppSecret、开发设置、request 合法域名 |
| 微信支付商户平台 | <https://pay.weixin.qq.com> | 商户号、API 证书、APIv3 密钥、回调配置 |
| 腾讯云 COS | <https://console.cloud.tencent.com/cos> | 存储桶、CORS、访问权限 |
| 腾讯云 VOD | <https://console.cloud.tencent.com/vod> | 应用 ID、Key 防盗链、上传模板 |
| 腾讯云 CAM | <https://console.cloud.tencent.com/cam> | 访问密钥（SecretId / SecretKey） |

---

## 2. 管理账号

### 2.1 账号信息

| 项目 | 值 |
| --- | --- |
| 登录地址 | `https://api.qinghebacademy.cn/admin/` |
| 用户名 | `admin`（对应 `ADMIN_INITIAL_USERNAME`） |
| 密码 | **不在本文档与代码仓库中**。见下方说明 |
| Token 类型 | Admin JWT（Bearer），默认有效期 `ADMIN_JWT_EXPIRE_MINUTES=480`（8 小时） |
| 账号创建方式 | 后端启动时 `ensure_initial_admin` 自动创建，无注册接口 |

密码说明：

- 账号只在**用户名不存在**时创建，初次密码取自服务器 `.env` 的 `ADMIN_INITIAL_PASSWORD`（≥12 位，≤72 字节）。
- 账号已存在时修改 `ADMIN_INITIAL_PASSWORD` **不会重置密码**；线上实际密码可能早已不是 `.env` 中的值，请以账号实际持有者为准。
- 系统**没有**修改密码 / 找回密码接口，只能按 2.3 在服务器上重置。
- 管理员与 C 端用户使用两套独立 JWT 密钥，Admin Token 无法调用 C 端接口，反之亦然。

### 2.2 登录方式

```http
POST https://api.qinghebacademy.cn/api/v1/admin/auth/login
Content-Type: application/json

{"username": "admin", "password": "<密码>"}
```

返回的 Token 放入后续请求头：`Authorization: Bearer <token>`。
退出登录只清除本地 Token（JWT 无状态，服务端不维护黑名单）。

### 2.3 重置管理员密码（无接口，需登录服务器）

在服务器 `/opt/huahuo-spark` 下执行（`-e` 把新密码以环境变量传入容器，避免出现在进程列表）：

```bash
cd /opt/huahuo-spark
read -rsp "新管理员密码（≥12 位）: " NEW_ADMIN_PASSWORD; echo

docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  exec -e NEW_ADMIN_PASSWORD="$NEW_ADMIN_PASSWORD" -T fastapi python - <<'PY'
import asyncio
import os

from sqlalchemy import select

from app.api.deps import SessionFactory
from app.core.security import hash_password
from app.models.admin_user import AdminUser


async def main() -> None:
    password = os.environ["NEW_ADMIN_PASSWORD"]
    if len(password) < 12:
        raise SystemExit("密码长度不足 12 位")
    if len(password.encode("utf-8")) > 72:
        raise SystemExit("密码超过 bcrypt 72 字节上限")

    async with SessionFactory() as session:
        admin = (
            await session.execute(select(AdminUser).where(AdminUser.username == "admin"))
        ).scalar_one_or_none()
        if admin is None:
            raise SystemExit("管理员 admin 不存在")
        admin.password_hash = hash_password(password)
        await session.commit()
    print("已更新 admin 密码")


asyncio.run(main())
PY
unset NEW_ADMIN_PASSWORD
```

注意事项：

- JWT 无状态，改密码**不会**让已签发的 Admin Token 立即失效（最长再存活 8 小时）。需要立即踢出所有人时，更换 `ADMIN_JWT_SECRET` 并重建 FastAPI 容器。
- 不要手工删除 `admin_users` 里的唯一管理员；万一被清空，需保证 `.env` 仍有合法的 `ADMIN_INITIAL_PASSWORD`，重启后端可重新创建。
- 重置后同步更新密码保管记录，不要把新密码写进仓库、文档或聊天记录。

---

## 3. 配置项清单

所有变量定义在 `backend/app/core/config.py`（pydantic-settings，密钥使用 `SecretStr`）。
「生产已配置值」一列仅展示非敏感项；敏感项一律以 `********` 表示。

### 3.1 应用与网络

| 变量 | 生产已配置值 | 说明 | 敏感 |
| --- | --- | --- | --- |
| `APP_ENV` | `production` | 控制 Swagger 等调试开关 | 否 |
| `APP_NAME` | 见服务器 `.env` | 应用名称 | 否 |
| `API_PREFIX` | `/api/v1` | 必须以 `/` 开头、不以 `/` 结尾 | 否 |
| `LOG_LEVEL` | `INFO` | 应用日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL） | 否 |
| `CORS_ALLOW_ORIGINS` | `https://api.qinghebacademy.cn` | 只允许裸 origin，禁止通配符/路径 | 否 |

### 3.2 数据库与缓存

| 变量 | 生产已配置值 | 说明 | 敏感 |
| --- | --- | --- | --- |
| `MYSQL_HOST` | `mysql`（容器内） | MySQL 服务名 | 否 |
| `MYSQL_PORT` | `3306` | | 否 |
| `MYSQL_DATABASE` | 见服务器 `.env` | 业务库名 | 否 |
| `MYSQL_USER` | 见服务器 `.env` | 业务账号 | 否 |
| `MYSQL_PASSWORD` | `********` | 业务账号密码 | **是** |
| `MYSQL_ROOT_PASSWORD` | `********` | root 密码，仅初始化容器用 | **是** |
| `DATABASE_URL` | `********` | 形如 `mysql+aiomysql://user:pass@mysql:3306/db?charset=utf8mb4`，密码需 URL 编码 | **是** |
| `REDIS_URL` | `********` | 形如 `redis://redis:6379/0` | **是** |
| `STUDY_PROGRESS_TTL_SECONDS` | `604800` | 学习进度缓存 TTL（7 天） | 否 |
| `STUDY_PROGRESS_FLUSH_INTERVAL_SECONDS` | `60` | 进度落库周期，必须小于 TTL | 否 |

### 3.3 JWT 与管理员

| 变量 | 生产已配置值 | 说明 | 敏感 |
| --- | --- | --- | --- |
| `USER_JWT_SECRET` | `********` | C 端用户 JWT 密钥，≥32 字符 | **是** |
| `USER_JWT_ALGORITHM` | `HS256` | | 否 |
| `USER_JWT_EXPIRE_MINUTES` | `10080` | 7 天 | 否 |
| `ADMIN_JWT_SECRET` | `********` | 后台 JWT 密钥，≥32 字符，**必须与 USER 不同** | **是** |
| `ADMIN_JWT_ALGORITHM` | `HS256` | | 否 |
| `ADMIN_JWT_EXPIRE_MINUTES` | `480` | 8 小时 | 否 |
| `ADMIN_INITIAL_USERNAME` | `admin` | 初始管理员用户名 | 否 |
| `ADMIN_INITIAL_PASSWORD` | `********` | ≥12 位；仅账号首次创建时生效 | **是** |

### 3.4 微信小程序

| 变量 | 生产已配置值 | 说明 | 敏感 |
| --- | --- | --- | --- |
| `WECHAT_APP_ID` | `wx0ed8e6f218161748` | 小程序 AppID，也写在 `miniprogram/project.config.json` | 否 |
| `WECHAT_APP_SECRET` | `********` | 小程序 AppSecret，**仅服务端** | **是** |

获取：微信公众平台 → 开发管理 → 开发设置 → 小程序密钥。重置 AppSecret 后旧值立即失效，需同步更新服务器 `.env` 并重建 FastAPI。

### 3.5 微信支付

| 变量 | 生产已配置值 | 说明 | 敏感 |
| --- | --- | --- | --- |
| `WECHAT_PAY_MCH_ID` | 见服务器 `.env` | 商户号 | 是（业务敏感） |
| `WECHAT_PAY_CERT_SERIAL_NO` | `********` | API 证书序列号 | **是** |
| `WECHAT_PAY_PRIVATE_KEY_PATH` | `/run/secrets/wechatpay_apiclient_key.pem` | 容器内路径，宿主机文件见第 4 节 | 否（路径） |
| `WECHAT_PAY_API_V3_KEY` | `********` | APIv3 密钥，**恰好 32 字节** | **是** |
| `WECHAT_PAY_PUBLIC_KEY_PATH` | `/run/secrets/wechatpay_public_key.pem` | 微信支付公钥的容器内路径；与公钥 ID 必须同时配置 | 否（路径） |
| `WECHAT_PAY_PUBLIC_KEY` | 留空 | 可选：直接以 PEM 内容提供微信支付公钥；与路径同时配置时以内容为准 | **是** |
| `WECHAT_PAY_PUBLIC_KEY_ID` | `PUB_KEY_ID_...` | 微信支付公钥 ID，用于校验微信响应/回调解密签名 | **是** |
| `WECHAT_PAY_NOTIFY_URL` | `https://api.qinghebacademy.cn/api/v1/payments/wechat/notify` | 必须 HTTPS；回调只验签、不走 JWT，返回 HTTP 200 | 否 |
| `COURSE_VALID_DAY` | `365` | 支付成功后课程授权有效天数；有效期仅后台可见 | 否 |

获取：

- 商户号：微信支付商户平台 → 账户中心 → 商户信息。
- 证书序列号 + 商户私钥：商户平台 → 账户中心 → API 安全 → 申请 API 证书，下载后得到 `apiclient_key.pem`。
- APIv3 密钥：商户平台 → 账户中心 → API 安全 → 设置 APIv3 密钥（自行设置，32 字节）。
- 微信支付公钥：商户平台 → 账户中心 → API 安全 → 「微信支付公钥」，下载 `pub_key.pem` 并记录页面展示的公钥 ID（`PUB_KEY_ID_...`）。新版商户没有平台证书，未配置公钥时 SDK 初始化会报 `No wechatpay platform certificate`。

### 3.6 腾讯云 COS（课程资源）

| 变量 | 生产已配置值 | 说明 | 敏感 |
| --- | --- | --- | --- |
| `TENCENTCLOUD_SECRET_ID` | `********` | 子账号 SecretId | **是** |
| `TENCENTCLOUD_SECRET_KEY` | `********` | 子账号 SecretKey | **是** |
| `COS_BUCKET` | `hexiameixueyuan-1518742118` | 存储桶名，含 APPID 后缀 | 否 |
| `COS_REGION` | `ap-guangzhou` | 存储桶地域 | 否 |
| `COS_PUBLIC_BASE_URL` | `https://hexiameixueyuan-1518742118.cos.ap-guangzhou.myqcloud.com` | 对象公网前缀 | 否 |

要求：

- CAM 子账号最小权限：仅 `cos:PutObject`，资源限定到桶的 `courses/*`。
- 桶 CORS Origin：`https://api.qinghebacademy.cn`；本地联调按后台实际端口另加（当前 `http://127.0.0.1:15173`、`http://localhost:15173` 及 `5173` 同款）；Methods `PUT/GET/HEAD`；Expose `ETag`。
- 后端 `CORS_ALLOW_ORIGINS` 本地值与后台端口保持一致：`http://127.0.0.1:15173,http://localhost:15173,http://127.0.0.1:5173,http://localhost:5173`。
- 密钥泄露或曾用于 Git/共享时必须轮换。

### 3.7 腾讯云 VOD（课程视频）

| 变量 | 生产已配置值 | 说明 | 敏感 |
| --- | --- | --- | --- |
| `VOD_APP_ID` | `1518742118` | 云点播应用 ID | 否 |
| `VOD_PLAY_KEY` | `********` | Key 防盗链密钥 | **是** |
| `VOD_PLAY_KEY_EXPIRE_SECONDS` | `7200` | 播放签名有效期（2 小时） | 否 |
| `VOD_UPLOAD_PROCEDURE` | `SimpleAesEncryptPreset` | 上传后处理任务流（转码 + 加密） | 否 |
| `VOD_UPLOAD_MAX_SIZE_MB` | `2048` | 单文件上限（与前端、Nginx 50m 上传限制区分） | 否 |

获取：云点播控制台 → 应用管理 → 应用信息 / 分发播放设置 → Key 防盗链。
播放地址由后端生成 `psign` 签名，不给小程序下发密钥。

### 3.8 构建期地址（非机密）

| 变量 | 生产已配置值 | 使用方 |
| --- | --- | --- |
| `TARO_APP_API_BASE_URL` | `https://api.qinghebacademy.cn/api/v1` | 小程序构建（`npm run build:weapp:online`） |
| `VITE_API_BASE_URL` | `/api/v1` | admin-web 生产构建（同域相对路径） |
| `VITE_BASE_PATH` / `PUBLIC_URL` | `/admin/` | admin-web 静态资源基路径 |
| `REDIS_PORT` | `6379`（本地 compose 用） | 本地开发 |

生产构建小程序时必须确认包内地址为正式域名，**不得**打入服务器 IP 或其他临时地址。

---

## 4. 密钥文件与存放位置

| 内容 | 本地位置 | 生产位置 | 权限 | 是否进 Git |
| --- | --- | --- | --- | --- |
| 环境变量模板 | `.env.example` | 同左 | 644 | 是（仅占位符） |
| 本地开发环境变量 | `.env`（项目根） | — | 600 | 否 |
| 生产环境变量（本地生成） | `deploy/.env.production` | — | 600 | 否（仅 `REFRESH_ENV=1` 时上传覆盖） |
| 生产环境变量（服务器） | — | `/opt/huahuo-spark/.env` | 600 | 否 |
| 微信支付商户私钥 | `deploy/secrets/wechatpay_apiclient_key.pem` | `/opt/huahuo-spark/deploy/secrets/wechatpay_apiclient_key.pem` | 600 | 否 |
| 微信支付公钥（新版商户） | `deploy/secrets/wechatpay_public_key.pem` | `/opt/huahuo-spark/deploy/secrets/wechatpay_public_key.pem` | 600 | 否 |
| TLS 证书链 | `deploy/nginx/certs/fullchain.pem` | 同左 | 600 | 否 |
| TLS 私钥 | `deploy/nginx/certs/privkey.pem` | 同左 | 600 | 否 |
| SSH 私钥 | `D:/ssh/` 下由 `D:/ssh/config` 指定 | — | 600 | 否 |
| 小程序 AppID | `miniprogram/project.config.json` | — | — | 是（AppID 非机密） |

补充：

- 生产证书默认从 `/home/ubuntu/ssl` 自动导入；已存在 `deploy/nginx/certs/` 时不覆盖。
- 商户私钥以只读方式挂载到容器 `/run/secrets/wechatpay_apiclient_key.pem`，与 `WECHAT_PAY_PRIVATE_KEY_PATH` 对应。
- 微信支付公钥（新版商户）以只读方式挂载到 `/run/secrets/wechatpay_public_key.pem`，与 `WECHAT_PAY_PUBLIC_KEY_PATH` 对应；公钥（路径或内容）与 `WECHAT_PAY_PUBLIC_KEY_ID` 必须同时配置或同时留空。私钥始终只从文件读取，不要写入环境变量。
- 部署压缩包会排除 `.env`、`deploy/secrets`、`deploy/nginx/certs`、`deploy/data`。

---

## 5. 配置变更流程

### 5.1 只改服务器配置（推荐）

```bash
ssh -F D:/ssh/config beauty
cd /opt/huahuo-spark
chmod 600 .env
# 编辑 .env 后，环境变量在容器创建时注入，必须重建 FastAPI 容器
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  up -d --no-deps --force-recreate fastapi
```

改完用 `https://api.qinghebacademy.cn/api/v1/health` 与后台登录验证。

### 5.2 重新生成并覆盖生产 `.env`

本地 `.env` 与服务器不一致时，可用 `REFRESH_ENV=1 bash deploy/daily-deploy.sh`：
以本地 `.env` 为基底生成 `deploy/.env.production`（自动改写 `APP_ENV`、`CORS`、回调域名、API 基址），上传覆盖服务器 `.env` 并重新部署。
**覆盖前先备份服务器 `.env`，并确认本地 `.env` 中的密钥都是线上真实值。**

### 5.3 各密钥轮换影响

| 轮换项 | 影响 | 处理 |
| --- | --- | --- |
| `USER_JWT_SECRET` | 所有 C 端用户登录态失效 | 重建 FastAPI，用户重新微信登录 |
| `ADMIN_JWT_SECRET` | 所有管理员登录态失效 | 重建 FastAPI，管理员重新登录 |
| `WECHAT_APP_SECRET` | 微信登录 / 手机号获取立即失败 | 更新 `.env` → 重建 |
| 商户 API 证书 / APIv3 密钥 | 支付下单与回调验签失败 | 新证书放 `deploy/secrets`，更新序列号与路径 → 重建；商户平台回调配置同步 |
| COS / VOD 腾讯云密钥 | 上传、播放签名失败 | CAM 生成新密钥 → 更新 `.env` → 重建 |
| `VOD_PLAY_KEY` | 已签发播放地址在有效期内仍可用，新地址改用新签名 | 更新 `.env` → 重建 |
| `WECHAT_XPAY_PROD_APP_KEY` / `..._MSG_TOKEN` / `..._ENCODING_AES_KEY` | 虚拟支付下单签名（iOS/Android 全端）与推送验签、发货立刻失败 | 微信公众平台重置后同步 `.env` → 重建；推送配置需保持一致 |

### 5.4 小程序虚拟支付（课程为虚拟商品，全端必须使用虚拟支付）

微信审核要求：虚拟商品只能通过官方「小程序虚拟支付」售卖，不得出现任何普通微信支付购买入口。
控制台路径：微信公众平台 → 支付与交易 → 虚拟支付。

- **基础配置**：填写「小程序简称」（Apple 支付展示名，需与主体/品牌一致）；开启「是否启用苹果 IAP 支付」（不开启时 iOS 下单返回 `15001`，约 10 分钟生效）。
- **道具管理**：道具 ID 必须与 `vpay_products.product_id` 一致，价格（分）必须等于 `courses.price`；保存后**发布到线上**（未发布/未生效返回 `15010` / `15014`）。
- **iOS 要求**：微信 ≥ 8.0.68、iOS ≥ 15、中国大陆 Apple ID；道具单价 ≥ 1 元；iOS 无沙箱，`env` 固定 `0`。
- **消息推送**：回调地址 `https://api.qinghebacademy.cn/api/wx/xpay/callback`（XML、安全模式加密，Token / AESKey 与 `.env` 中 `WECHAT_XPAY_PROD_*` 一致）。
- **服务端 `.env`**：`WECHAT_XPAY_OFFER_ID`、`WECHAT_XPAY_PROD_APP_KEY`、`WECHAT_XPAY_PROD_MSG_TOKEN`、`WECHAT_XPAY_PROD_ENCODING_AES_KEY`（沙箱另配一套）。
- **审核备注建议**：本小程序课程为虚拟商品，已接入小程序虚拟支付，Android / iOS 均通过 `wx.requestVirtualPayment` 完成购买，无任何普通微信支付购买入口。

---

## 6. 上线前配置检查

- [ ] 域名 `api.qinghebacademy.cn` 完成 ICP 备案，HTTPS 证书有效且未过期
- [ ] 微信公众平台「开发设置 → 服务器域名」已添加 `https://api.qinghebacademy.cn`（request 与 uploadFile 合法域名；头像上传使用 `Taro.uploadFile`）
- [ ] 小程序线上包使用 `npm run build:weapp:online` 构建，包内 API 地址为正式域名
- [ ] 微信支付回调地址在商户平台可达，返回 HTTP 200，且回调接口不要求 JWT
- [ ] 虚拟支付已签约并配置 `WECHAT_XPAY_OFFER_ID` 与现网 AppKey / MsgToken / EncodingAESKey；推送地址 `/api/wx/xpay/callback` 握手通过
- [ ] 虚拟支付基础配置已开启「苹果 IAP 支付」并填写小程序简称（否则 iOS 下单返回 15001）
- [ ] 线上道具已发布且价格与课程价一致；`vpay_products` 映射 `enabled=1` 且 `env=0`
- [ ] `npm run build:weapp:online` 产物中不存在 `wx.requestPayment`，购买只使用 `wx.requestVirtualPayment`
- [ ] COS 桶 CORS、最小权限策略、公网读配置正确
- [ ] VOD 应用已开启 Key 防盗链，`VOD_UPLOAD_PROCEDURE` 与点播控制台模板一致
- [ ] 管理员密码已改为强密码并由专人保管；`ADMIN_INITIAL_PASSWORD` 不再作为日常登录凭据
- [ ] 所有曾出现在开发机、Git 历史或聊天中的密钥均已轮换
- [ ] `USER_JWT_SECRET` 与 `ADMIN_JWT_SECRET` 不同且各 ≥32 字符
- [ ] MySQL / Redis / `.env` / 证书 / 商户私钥权限为 600，未进入代码仓库
