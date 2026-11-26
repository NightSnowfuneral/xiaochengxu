# 禾下美学院｜C 端微信小程序（Taro）

本目录是禾下美学院知识付费项目的 C 端微信小程序，技术栈为
**Taro 4 + React 18 + TypeScript + Redux Toolkit + redux-persist**。
只包含学员侧页面；管理后台是独立工程，不在本小程序内，也不包含管理员登录、
下单后台或后台视频播放能力。

## 1. 运行前准备

- Node.js 18+、npm 9+（当前交付环境没有 Node/npm，因此未执行真实构建）。
- 微信开发者工具。
- 在微信公众平台注册小程序，取得正式 AppID，并替换
  [project.config.json](./project.config.json) 中的 `"appid": "touristappid"`。
- 后端已按 `.env.example` 启动，默认地址为
  `http://127.0.0.1:8000/api/v1`。

```bash
cd beauty-course-mp/miniprogram
npm install

# 开发（watch，自动启用开发环境模拟登录兜底）
npm run dev:weapp

# 生产构建（会通过 alias 移除模拟登录凭据与入口）
npm run build:weapp:prod

# 仅做 TypeScript 检查（需先 npm install）
npm run typecheck
```

构建产物在 `dist/`。微信开发者工具「导入项目」选择本 `miniprogram` 目录即可，
工具会按 `project.config.json` 的 `miniprogramRoot: dist/` 读取产物。

### API 地址

复制 `.env.example` 为 `.env`，或构建时注入环境变量：

```bash
TARO_APP_API_BASE_URL=https://api.example.com/api/v1
```

- 开发者工具调试时可勾选「不校验合法域名」。
- 真机必须使用 HTTPS，并在微信公众平台配置 request 合法域名。
- 前端包内不放置微信 AppSecret、支付密钥、VOD PlayKey、JWT 密钥等任何服务端密钥。

## 2. 页面与业务范围

| 页面 | 路径 | 说明 |
| --- | --- | --- |
| 首页 | `pages/home/index` | 主标题、公告、图标入口、热门课程 |
| 商学院课程广场 | `pages/academy/index` | 热门课程 + 全部课程分页 |
| 课程列表 | `pages/course-list/index` | 搜索、全部 / 热门 / 我的课程 |
| 课程详情 | `pages/course-detail/index` | 全量课时、购买、权限解锁 |
| 视频播放 | `pages/player/index` | VOD 播放、倍速/全屏、loading、15 秒进度上报、看完标记、续播 |
| 支付结果 | `pages/payment-success/index` | 轮询确认支付结果、刷新课程 |
| 我的订单 | `pages/orders/index` | 订单中心：全部 / 待支付 / 已支付 / 已取消筛选，继续支付、取消订单 |
| 订单详情 | `pages/order-detail/index` | 订单号、课程、金额、状态；待支付可支付或取消 |
| 个人中心 | `pages/profile/index` | 个人资料、我的订单入口、我的课程、退出登录 |
| 我的预约 | `pages/appointment/index` | 预约次数、可预约时段、预约记录 |

底部 TabBar 固定两项：首页、课程广场；只动态更新两项文字，不新增 Tab。

课程购买后解锁**全部课时**；课时没有独立价格，不能单独售卖。未购买时课时列表
只展示锁定态，不提供试看。

## 3. 目录结构

```text
src/
├─ app.config.ts              # 页面、双 Tab、腾讯云 VOD 插件
├─ app.tsx                    # Provider、启动/热启动登录态校验、拉取配置
├─ components/                # CourseIconGrid / HotTopicCard / CourseCard
│                             # WxAuthSheet / PurchaseModal / VodPlayer / MockModeBadge
├─ hooks/                     # useRequireAuth、useSystemConfig
├─ pages/                     # 10 个页面（含我的订单、订单详情）
├─ services/                  # axios + Taro.request 适配、业务 API
├─ store/                     # RTK slices、redux-persist 适配
├─ utils/                     # 登录、惰性鉴权 authGate、导航、格式化
├─ dev/                       # 仅开发环境的模拟登录及生产替身
└─ types/                     # 后端 DTO 与自定义组件类型
```

Redux slices：`userSlice`、`authSheetSlice`、`configSlice`、`courseSlice`、`orderSlice`。
仅 `user` 与 `config` 持久化；登录弹窗、课程和订单始终从内存或服务端读取。

## 4. 登录与页面守卫

1. 无独立登录页。首页与课程广场公开浏览；冷启动无 Token 时不跳转、不弹窗。
2. 需要身份的操作（我的预约、全部课程、我的课程、个人中心、购买、播放等）
   通过 `useRequireAuth` / `requestAuth` 暂存原动作，并打开底部半屏
   `WxAuthSheet`。登录成功后自动继续原跳转；关闭弹窗则中止并停留当前页。
3. 一次性按钮完成「手机号快捷登录」：内部通过 `Taro.login()` 取 `loginCode`，
   `open-type="getPhoneNumber"` 取 `phoneCode`，交由后端
   `/auth/wx-login` 换取 openid 与 **C 端 JWT**。前端不接触 openid、session_key，
   手机号只以临时 code 形式交给后端。
4. 冷/热启动仅在本地已有 Token 时调用 `/auth/token-check`；`onShow` 2 秒防抖
   并复用进行中的请求。Token 失效或任意业务接口 401 只清理本地登录态与持久化
   缓存，停留当前页，不跳转登录页、不自动拉起手机号授权。
5. 主动退出完成后切回首页 Tab；首页以未登录状态正常渲染，重启仍保持未登录。

### 开发环境模拟登录

- 只有 `npm run dev:weapp`（development）才有入口。
- 点击底部登录弹窗中的 **“模拟登录（仅开发环境）”** 使用固定测试账号；
  生产构建会替换为空实现，入口与凭据都不会打进包内。
- 模拟用户固定为：

```ts
{
  id: 999999,
  nickname: '测试用户',
  mobile: '13800138000',
  avatar: '',
  token: 'mock_test_token_123456'
}
```

- 模拟身份只用于页面守卫与交互联调，不请求真实业务数据；真实接口返回 401 是
  预期结果。页面顶部会显示黄色“测试模式”条。
- 生产构建通过 `config/index.ts` 的 `@mock-login` alias 指向
  `src/dev/mockLogin.stub.ts`，包内不包含模拟用户与模拟 Token；同时
  `IS_DEV && MOCK_LOGIN_ENABLED` 条件会隐藏模拟登录按钮。

## 5. 支付流程

1. 课程详情页创建订单：`POST /payments/create-order`（只传 `course_id`，金额由服务端固化）。
2. 后端返回微信支付参数；前端将 snake_case 映射为 `wx.requestPayment` 的
   `timeStamp / nonceStr / package / signType / paySign`。
3. 支付调起成功后每 **2 秒**轮询 `/payments/query-order/{order_no}`，直到 `paid`
   （最多约 2 分钟），随后刷新课程详情与“我的课程”，课时的 `is_owned`
   以服务端返回为准。
4. 支付取消可重新发起；轮询超时提示稍后在“我的课程”确认。
5. 支付结果最终以微信异步回调为准，本端不猜状态，也不修改订单。

## 6. 视频播放与进度

- 播放前请求 `/client/lessons/{id}/play-auth`；后端校验课程归属后返回
  `app_id / file_id / signature / expire_at / play_url / last_position`。
  其中 `play_url` 是服务端调用 VOD `DescribeMediaInfos` 解析出 H.264 MP4 地址，
  再按 Key 防盗链规则签名后的完整地址，有效期与 `signature` 一致。
- 未购买返回 403（`COURSE_NOT_OWNED`），页面引导返回详情购买。
- 前端使用原生 `Video` 组件播放 `play_url`（`VodPlayer` 组件），不引入点播插件、
  不持有 VOD PlayKey，也不自行拼接 CDN 地址。
- 播放中每 **15 秒**上报一次 `/client/study/progress`，页面隐藏/卸载时补报一次。
  后端先写 Redis 缓冲，再由定时任务批量 upsert 到 MySQL；前端只上报最新位置。
- 原生控件开启播放/暂停、进度拖拽、当前/总时长与全屏；倍速使用浅色工具栏
  （0.5x / 0.75x / 1x / 1.25x / 1.5x / 2x），通过
  `Taro.createVideoContext(id, page).playbackRate(rate)` 设置。该 API 要求基础库
  ≥ 2.13.0，低版本会保持 1x，不影响正常播放。
- 视频加载与缓冲时展示 loading 遮罩，可播放后自动消失；遮罩不拦截视频控件。
- 播放器触发 `ended` 后调用 `POST /api/vod/finish-lesson`（固定路径，不带 `/v1`）
  标记已看完。接口幂等，服务端把 `last_position` 归零，再次进入从头播放；
  失败时页面展示“重新标记”，不打断播放。
- 完成回调地址由 `src/config/index.ts` 的 `FINISH_LESSON_URL` 生成（默认
  `<API_ORIGIN>/api/vod/finish-lesson`）；若网关修改固定路径，需同时改后端
  `app/api/vod.py` 与前端该配置。
- 播放地址过期后重新进入播放页即可刷新；`play_url` 为空时页面提供“重新获取授权”。

### VOD 前置条件（必须人工完成）

1. 腾讯云点播控制台开通服务，上传并转码视频；建议生成 H.264 MP4（转码模板
   `100030` STD-H264-MP4-720P），避免部分 Android 设备无法解码 HEVC。
2. 后端配置 `VOD_APP_ID`、`VOD_PLAY_KEY`、`VOD_PLAY_KEY_EXPIRE_SECONDS`，以及
   用于调用 VOD API 的 `TENCENTCLOUD_SECRET_ID` / `TENCENTCLOUD_SECRET_KEY`。
3. 生产环境在点播控制台开启 **Key 防盗链**，并把播放域名加入小程序
   「request 合法域名」/「downloadFile 合法域名」（视频使用 HTTPS）。
4. 官方「云点播短视频播放器」插件（`wx116d0dd5e6a39ac7`）需要非个人主体、
   购买 License 并通过「微信小程序视频发布」审核，且插件参数表不支持 `psign`，
   因此本项目不依赖该插件。`play-auth` 仍保留 `signature` 字段，供后续接入
   官方播放器或 HLS 加密时使用。
5. 必须在真机验证播放、倍速、全屏、loading、续播、进度上报与看完回调；开发者工具需勾选「不校验合法域名」。

## 7. 系统配置与 TabBar

每个页面 `onShow` 拉取 `GET /config`（免 JWT），成功后写入 `configSlice`，
失败时保留上一次配置并使用前端内置默认值。

| 前端业务键 | 兼容的后端键 | 用途 |
| --- | --- | --- |
| `home_page_title` | `home_title` | 首页主标题 |
| `academy_page_title` | `course_square_title` | 课程广场标题 |
| `hot_topic_title` | `home_hot_title` | 热门板块标题 |
| `home_notice` | `home_notice` | 首页公告（空则隐藏） |
| `search_placeholder` | `search_placeholder` | 搜索占位 |
| `tab_home_text` | `tab_home_text` | 第一个 Tab 文字 |
| `tab_course_text` | `tab_course_text` | 第二个 Tab 文字 |

TabBar 只在首页/课程广场调用 `Taro.setTabBarItem({ index: 0/1 })`，不修改其他
属性，也不在非 Tab 页面调用。

## 8. 请求层

- `services/request.ts` 用 `Taro.request` 实现 axios adapter（小程序没有 XHR），
  继续使用 axios 的拦截器、参数序列化与错误归一化。
- 请求自动注入 `Authorization: Bearer <C端JWT>`；登录接口与公开只读接口除外。
- 公开课程列表通过 `skipAuth` 不携带本地 Token，避免过期 Token 把公开请求变成 401。
- 后端错误统一为 `{ code, message, data }`，前端转换为 `ApiError`。
- 服务端路由：
  - `/auth/wx-login`、`/auth/token-check`、`/auth/logout`
  - `/client/user/profile`
  - `/client/courses`、`/client/courses/mine`、`/client/courses/{id}`
  - `/client/lessons/{id}/play-auth`、`/client/study/progress`
  - `/client/orders`（我的订单列表，可按状态筛选）、`/client/orders/{order_no}`（详情）、
    `/client/orders/{order_no}/pay`（继续支付）、
    `/client/orders/{order_no}/cancel`（取消待支付订单）
  - `/config`

## 9. 安全与边界

- C 端 JWT 与后台 Admin Token 完全独立；本工程没有任何管理员接口调用。
- 不在前端保存 VOD 密钥、微信支付密钥、AppSecret 或后端 JWT 密钥。
- 不实现也不包含：试看、退款、评论、收藏、优惠券、分销、直播、社群、打卡、
  题库、积分、会员体系。
- 后台不具备下单与视频播放能力；本小程序也不提供后台入口。

## 10. 本次静态检查说明

当前交付环境没有 Node/npm，因此**未执行 `npm install`、Taro 构建、真机调试或
`tsc`**。已完成的静态检查：

- 48 个 TS/TSX 文件定界符平衡检查；
- 相对模块路径存在性检查；
- `package.json`、`project.config.json`、`tsconfig.json` JSON 语法检查。

仍需在安装依赖后执行 `npm run typecheck`、`npm run build:weapp`，然后按第 6 节
完成 VOD 插件、支付和真机手机号授权验证。
