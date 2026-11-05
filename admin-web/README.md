# 禾下美学院｜管理后台（admin-web）

禾下美学院知识付费项目的独立 B 端站点。它只通过 FastAPI 的 `/admin/*` 接口工作，与学员端小程序完全解耦，不共享路由、状态或构建产物。

## 技术栈

- Vite 5 + React 18 + TypeScript 5
- Redux Toolkit + react-redux
- react-router-dom 6
- TailwindCSS 3
- axios

## 页面与能力

| 路由 | 页面 | 能力 |
| --- | --- | --- |
| `/login` | 管理员登录 | 账号密码登录、退出登录 |
| `/courses` | 课程管理 | 课程列表/搜索、新建、编辑、删除、三张图片 COS 直传 |
| `/lessons` | 课时管理 | 按课程维护课时标题与腾讯云 VOD 文件 ID |
| `/gifts` | 赠课管理 | 手机号 + 课程赠课、幂等结果提示、赠课日志分页查询 |
| `/orders` | 订单查询 | 只读筛选与分页，不提供下单、支付或状态修改 |
| `/config` | 系统配置 | 展示文案编辑、单项恢复默认、全部恢复默认 |

课程删除受后端约束：存在课时、订单、课程授权或赠课记录的课程会被拒绝删除，后台只展示后端返回的原因。

后台明确不提供以下能力：

- 管理员下单、支付、改价、修改订单状态或退款
- 视频预览、加载或播放；课时页只维护 VOD 文件 ID
- 试看、评论、收藏、优惠券、分销、直播、社群、打卡、题库、积分、会员体系
- 新增/删除系统配置键或动态增删底部 Tab

## 认证与权限隔离

- Admin JWT 与 C 端用户 JWT 使用**两套独立密钥**，任一方的令牌都不能访问另一方接口。
- 登录成功后，会话（token、管理员资料、过期时间）写入独立的 localStorage 键
  `spark.admin.session.v1`。Redux 只持久化这一份会话；课程、课时、赠课、订单和配置始终从服务端重新读取。
- axios 请求拦截器统一注入 `Authorization: Bearer <Admin JWT>`；不会读取或使用 C 端令牌。
- 路由守卫 `RequireAuth` 在无令牌或令牌过期时跳转 `/login`，并记录原路径用于登录后返回。
- 除登录接口外，任意接口返回 `401` 都会清除本地会话并跳转登录页。
- 令牌到期由定时器自动失效；多标签页通过 `storage` 事件同步登录/退出。
- 管理员密码不写入 localStorage、Redux 或任何前端日志。

> localStorage 会话会受 XSS 影响。生产环境必须使用 HTTPS、限制后台来源，并在 Nginx/网关层配置合理的 CSP 与访问控制。

## 本地开发

要求：Node.js >= 18、npm。

```bash
cd admin-web
cp .env.example .env
npm install
npm run dev
```

- 开发地址：<http://127.0.0.1:5173>
- 默认 API：`http://127.0.0.1:8000/api/v1`
- 管理员账号来自后端根目录 `.env` 的 `ADMIN_INITIAL_USERNAME` / `ADMIN_INITIAL_PASSWORD`，由后端首次启动钩子创建。
- 后端 CORS 默认允许 `http://127.0.0.1:5173` 与 `http://localhost:5173`；修改端口时需同步调整后端 `CORS_ALLOW_ORIGINS`。

也可以从项目根目录使用开发用 Compose：

```bash
docker compose --env-file .env -f deploy/docker-compose.dev.yml up -d --build
```

其中 `admin-web` 服务使用 Node 容器运行 Vite，API 地址由 `VITE_API_BASE_URL` 注入。

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `VITE_API_BASE_URL` | API 基础地址，末尾不要带斜杠。开发默认 `http://127.0.0.1:8000/api/v1`；生产可设为 `/api/v1` 由 Nginx 同源代理 |

前端构建只能包含公开信息。腾讯云 COS 密钥、VOD 播放密钥、微信支付私钥、JWT 密钥等全部保留在后端 `.env` 与服务器文件系统，绝不进入浏览器包。

`.env`、`.env.local` 已在 `.gitignore` 中忽略。

## 构建与生产部署

生产后台由 Nginx 挂在 `/admin/`，必须传入 Vite base：

```bash
cd admin-web
npm ci          # 无 lockfile 时使用 npm install
VITE_API_BASE_URL=/api/v1 npm run build -- --base=/admin/
```

产物位于 `admin-web/dist`。生产 Compose 将其只读挂载到
`/usr/share/nginx/html/admin`，Nginx 负责：

- `/admin/assets/*` 长缓存静态资源
- `/admin/*` 的 History 路由回退到 `/admin/index.html`
- `/api/*` 反向代理到 FastAPI

`src/main.tsx` 从 `import.meta.env.BASE_URL` 推导 `BrowserRouter` 的 basename，因此开发（`/`）与生产（`/admin/`）使用同一份路由代码。

`deploy/deploy.sh` 已包含后台构建、静态资源备份和失败回滚；部署前必须设置真实管理员密码与全部服务端密钥。

## COS 图片上传

课程封面大图、列表封面、课程图标是三个独立字段，每次上传各自请求预签名：

1. 后台调用 `POST /admin/courses/image-presign`（参数走 query：`filename`、`content_type`、`expires_in`）。
2. 后端返回短期 PUT 预签名 URL 与要求的请求头。
3. 浏览器使用**原生 axios** 直接 PUT 到 COS，不携带 Admin Token；图片二进制与云密钥都不经过 FastAPI。
4. 上传成功后把 `public_url` 写入课程字段，保存课程时提交给后端。

COS 存储桶需要配置与后台域名匹配的 CORS，至少允许：

- Origin：开发 `http://127.0.0.1:5173`，生产后台实际域名
- Methods：`PUT`（预览公网图片还需 `GET`/`HEAD`）
- Headers：`Content-Type`（如预签名返回其他头，也一并放行）
- Expose headers：`ETag`（便于排查上传问题）

图片限制为 JPG/JPEG/PNG/WebP、单张不超过 10MB，前端与后端都会校验扩展名、MIME 与大小。候选 URL 必须为 http(s)，最终课程图片应使用可公开访问的 HTTPS COS 地址。

## 业务约束说明

### 赠课

- 只输入已绑定手机号与课程 ID；后端唯一通过 `user.mobile` 匹配用户，未绑定手机号的用户无法被赠课。
- 同一手机号 + 课程为幂等键。重复提交返回 `gifted: false`，不会新增课程授权或赠课日志。
- 只有真实新增授权时才写入赠课日志；日志包含管理员、手机号、课程与时间，后台只读查询并支持分页筛选。
- 赠课发放整门课程，解锁全部课时；课时没有独立价格，不能单独售卖或赠送。

### 订单

- 订单由学员在小程序内通过微信支付产生，后台只读。
- 状态只有 `pending`（待支付）与 `paid`（已支付）；不存在退款、关闭订单或补单入口。
- 金额以分为单位存储，界面按元展示。

### 系统配置

- 配置键由后端启动钩子初始化，唯一且只读；后台只能修改当前值或恢复默认值。
- 配置只承载展示文案，不承载价格、权限或业务开关。
- 底部 Tab 固定两个，仅 `tab_home_text` 与 `tab_course_text` 两段文字可调整。
- 保存后小程序在下一次页面 `onShow` 拉取最新文案。

### 时间与金额

- 后端 MySQL `DATETIME` 按 `Asia/Shanghai` 墙上时间存储。
- 后台列表直接格式化后端返回的墙上时间，筛选框发送无时区的 naive datetime，避免浏览器时区造成 8 小时偏差。
- 课程价格在表单中按元输入，提交前转换为整数分。

## 目录结构

```text
admin-web/
├─ src/
│  ├─ api/            # axios 封装与 Admin 接口
│  ├─ components/     # 布局外通用组件：弹窗、表单、分页、上传等
│  ├─ layouts/        # 后台主框架
│  ├─ pages/          # 六个页面
│  ├─ router/         # 路由与登录守卫
│  ├─ store/          # Redux store、五个 slice、类型化 hooks
│  ├─ styles/         # Tailwind 与基础样式
│  ├─ types/          # 与后端对齐的 DTO
│  └─ utils/          # 会话、格式化、校验、COS 上传
├─ public/
├─ .env.example
├─ tailwind.config.js
├─ vite.config.ts
└─ deploy 脚本在项目根目录 deploy/
```

## 构建检查

```bash
npm run typecheck   # tsc --noEmit
npm run build       # 类型检查 + Vite 生产构建
```

本次交付环境未安装 Node/npm，因此未能实际执行 `tsc` 或 Vite 构建；已使用静态脚本核对全部 TS/TSX 的括号与字符串闭合、相对导入与导出名称、配置文件 JSON、敏感信息扫描和危险接口调用，并逐项比对后端 DTO 与路由。首次在有 Node 18+ 的环境安装依赖后，请优先执行 `npm run build -- --base=/admin/` 验证。
