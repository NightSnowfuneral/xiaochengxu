# 禾下美学院｜API 接口文档

本文档以 `backend/app/api/v1` 的实际实现为准，覆盖 C 端、管理后台、公开接口与微信支付回调。字段命名统一使用 `snake_case`，时间、金额、分页约定见「通用约定」。

## 1. 基础信息

| 项目 | 说明 |
| --- | --- |
| 本地地址 | `http://127.0.0.1:8000/api/v1` |
| 生产地址 | `https://<你的域名>/api/v1`（Nginx 将 `/api/` 原样转发给 FastAPI） |
| 数据格式 | 请求与响应均为 `application/json; charset=utf-8`，进度上报成功返回 `204` 无响应体 |
| 开放文档 | 本地开发可用 `/docs`、`/redoc`；生产 Nginx 明确返回 404 |
| 健康检查 | `GET /api/v1/health`，仅表示 FastAPI 进程可响应，不探测 MySQL / Redis |

## 2. 鉴权体系

系统存在两套**完全独立**的 JWT，密钥、audience、token 类型均不同，不能混用。

| 身份 | 请求头 | 签发接口 | 默认有效期 |
| --- | --- | --- | --- |
| C 端用户 | `Authorization: Bearer <user access_token>` | `POST /client/auth/wx-login` | 7 天（10080 分钟） |
| 后台管理员 | `Authorization: Bearer <admin access_token>` | `POST /admin/auth/login` | 8 小时（480 分钟） |
| 微信支付回调 | 不使用 JWT | 微信支付平台发起 | 仅校验微信支付签名 |

鉴权失败语义：

- 未携带 Token、Token 格式错误、签名错误或已过期：`401 UNAUTHORIZED`。
- Token 本身有效但身份不匹配：把 Admin Token 用在 C 端接口返回 `403 USER_PERMISSION_DENIED`；把 C 端 Token 用在 Admin 接口返回 `403 ADMIN_PERMISSION_DENIED`。
- 资源级权限在业务层判断：例如未购买课程请求播放鉴权，返回 `403 COURSE_NOT_OWNED`。

> 微信支付回调接口 `/payments/wechat/notify` 不走 JWT 鉴权，身份可信性完全依赖微信支付平台证书验签与解密后的商户号、AppID、金额、付款人校验。

## 3. 通用约定

### 3.1 成功响应

成功响应直接返回业务对象，不额外包裹 `code/message/data`：

```json
{
  "id": 1,
  "title": "禾下美学院第一课",
  "price": 19900
}
```

分页响应统一为：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20
}
```

`page` 从 1 开始，默认 1；`page_size` 默认 20，范围 1–100。

### 3.2 错误响应

所有业务错误、参数校验错误与未捕获异常统一为：

```json
{
  "code": "COURSE_NOT_OWNED",
  "message": "请先购买该课程后再观看",
  "data": null
}
```

参数校验失败（HTTP 422）时 `data` 为明细数组：

```json
{
  "code": "VALIDATION_ERROR",
  "message": "请求参数校验失败",
  "data": [
    {
      "loc": ["body", "course_id"],
      "msg": "Input should be greater than 0",
      "type": "greater_than"
    }
  ]
}
```

请求 DTO 默认拒绝未声明字段；字符串自动去除首尾空白。未知字段会触发 422。

### 3.3 金额与时间

- 金额一律为整数，**单位：分**。如 `19900` 表示 199 元。
- 时间字段为 ISO 8601 字符串，形如 `2026-10-28T10:30:00`，通常不带时区后缀；客户端按字符串展示即可。
- 后台时间筛选参数建议传不带时区的本地时间；若携带时区，服务端会统一换算为 UTC 后参与比较，且 `created_from` 与 `created_to` 的时区信息必须一致。
- 日期筛选为闭区间：`created_at >= created_from` 且 `created_at <= created_to`。

### 3.4 枚举

| 枚举 | 取值 | 说明 |
| --- | --- | --- |
| 订单状态 `status` | `pending` / `paid` / `closed` / `refunded` | `pending` 待支付；`paid` 已支付；`closed` 已关闭（超时关单或微信侧关闭）；`refunded` 仅用于历史退款数据，系统不提供退款接口 |
| 课程授权来源 | `buy` / `gift` | 内部字段，不对外返回；购买与赠课都写入统一授权表 |

### 3.5 通用错误码

| HTTP | code | 场景 |
| --- | --- | --- |
| 400 | `BAD_REQUEST` | 通用请求错误 |
| 401 | `UNAUTHORIZED` | 未登录、Token 无效或过期 |
| 403 | `FORBIDDEN` | 通用无权限 |
| 404 | `NOT_FOUND` | 通用资源不存在 |
| 405 | `METHOD_NOT_ALLOWED` | 请求方法不允许 |
| 409 | `CONFLICT` | 通用状态冲突 |
| 422 | `VALIDATION_ERROR` | 请求参数校验失败 |
| 429 | `TOO_MANY_REQUESTS` | 请求过于频繁 |
| 500 | `INTERNAL_ERROR` | 服务器内部错误，不暴露内部细节 |
| 502 | `BAD_GATEWAY` | 上游服务异常 |

业务专用错误码见各接口说明及文末「错误码汇总」。

## 4. 接口总览

### 4.1 公开接口（免 JWT）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查 |
| GET | `/config` | 公开系统配置（展示文案） |
| POST | `/client/auth/wx-login` | 微信静默登录 |
| POST | `/admin/auth/login` | 管理员账号密码登录 |
| POST | `/payments/wechat/notify` | 微信支付异步回调（仅微信签名校验） |

### 4.2 C 端接口（C 端用户 JWT）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/client/auth/bind-mobile` | 绑定微信手机号 |
| GET | `/client/user/profile` | 个人中心用户信息 |
| PUT | `/client/user/profile` | 更新个人资料（昵称） |
| POST | `/client/user/avatar` | 上传个人头像（multipart） |
| GET | `/client/courses` | 课程广场列表 / 首页热门 |
| GET | `/client/courses/mine` | 我的课程 |
| GET | `/client/courses/{course_id}` | 课程详情 |
| GET | `/client/lessons/{lesson_id}/play-auth` | 获取 VOD 临时播放鉴权 |
| POST | `/client/study/progress` | 上报播放进度 |
| POST | `/api/vod/finish-lesson` | 播放器完成回调（固定路径，不带 `/v1`） |
| POST | `/client/orders` | 创建订单并获取支付参数（兼容接口） |
| POST | `/payments/create-order` | 创建订单并获取微信 V3 支付参数（小程序当前使用） |
| GET | `/payments/query-order/{order_no}` | 查询订单；`pending` 时主动向微信查单并同步 |
| POST | `/payments/close-order/{order_no}` | 关闭超过 30 分钟未支付的订单 |
| GET | `/client/orders/{order_no}` | 查询订单支付状态 |

### 4.3 后台接口（Admin JWT）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/admin/auth/profile` | 当前管理员信息 |
| POST | `/admin/auth/logout` | 退出登录（无状态） |
| POST | `/admin/courses/image-presign` | 课程图片 COS 直传预签名 |
| GET | `/admin/courses` | 课程列表 |
| POST | `/admin/courses` | 新建课程 |
| GET | `/admin/courses/{course_id}` | 课程详情 |
| PUT | `/admin/courses/{course_id}` | 更新课程 |
| DELETE | `/admin/courses/{course_id}` | 删除空课程 |
| POST | `/admin/vod/upload` | 上传本地视频到 VOD 媒资库（仅超级管理员） |
| GET | `/admin/vod/list` | 媒资库分页列表（名称模糊 / FileId 精确） |
| POST | `/admin/vod/sync-status` | 同步 VOD 转码状态（仅超级管理员） |
| GET | `/admin/vod/{media_id}` | 媒资详情 |
| PUT | `/admin/vod/{media_id}` | 修改媒资名称（仅超级管理员） |
| DELETE | `/admin/vod/{media_id}` | 删除本地媒资记录（仅超级管理员，绑定中禁止） |
| GET | `/admin/lessons` | 按课程查询课时列表 |
| POST | `/admin/lessons` | 新建课时（仅超级管理员） |
| GET | `/admin/lessons/{lesson_id}` | 课时详情 |
| PUT | `/admin/lessons/{lesson_id}` | 更新课时（仅超级管理员） |
| DELETE | `/admin/lessons/{lesson_id}` | 删除课时（仅超级管理员） |
| POST | `/admin/lesson/create` | 新建课时别名（body 与 7.10 一致，仅超级管理员） |
| PUT | `/admin/lesson/update` | 更新课时别名（body 需带 `id`，仅超级管理员） |
| GET | `/admin/lesson/list` | 课时列表别名（Query 同 7.9） |
| POST | `/admin/gifts` | 按手机号赠课（幂等） |
| GET | `/admin/gifts/logs` | 赠课日志 |
| GET | `/admin/orders` | 订单只读查询 |
| GET | `/admin/users/lookup` | 按手机号或用户 ID 查找用户 |
| GET | `/admin/users/{user_id}/courses` | 用户已拥有课程分页查询（购买 + 赠课） |
| POST | `/admin/users/grant-course` | 赠课 / 重置有效期（同一用户 + 课程仅一条授权） |
| POST | `/admin/users/revoke-course` | 收回课程授权 |
| GET | `/admin/user-courses` | 用户课程授权与有效期只读查询 |
| GET | `/admin/configs` | 系统配置列表 |
| POST | `/admin/configs/reset` | 全部配置恢复默认 |
| PUT | `/admin/configs/{config_key}` | 修改单个配置值 |
| POST | `/admin/configs/{config_key}/reset` | 单个配置恢复默认 |

后台**不提供**下单、支付、退款、修改订单状态、视频播放、修改学习进度能力；订单接口只读。
管理员分 `super`（超级管理员）与 `normal`（普通管理员）两种角色：上传视频、同步转码状态、新建 / 编辑 / 删除课时仅 `super` 可调用，`normal` 仅可读取课程、课时、媒资与订单。

---

## 5. 公开接口

### 5.1 健康检查

`GET /health`

- 鉴权：无
- 入参：无
- 出参：

```json
{ "status": "ok" }
```

说明：仅检查 FastAPI 进程能否响应，不检查 MySQL / Redis；依赖服务短暂抖动不会导致容器被反复重启。

### 5.2 读取公开系统配置

`GET /config`

- 鉴权：无
- 入参：无
- 出参：

```json
{
  "configs": {
    "home_title": "禾下美学院",
    "tab_home_text": "首页",
    "tab_course_text": "课程"
  }
}
```

说明：

- 配置只承载展示文案，不承载权限、价格或业务开关。
- 缺失的配置由前端内置默认值兜底；接口异常时前端仍可渲染。
- 底部 Tab 固定两个，仅 `tab_home_text` / `tab_course_text` 两段文字可调整。

### 5.3 微信静默登录

`POST /client/auth/wx-login`

- 鉴权：无
- 请求体：

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `code` | string | 是 | 1–128 字符 | `wx.login` 获取的临时 code |

```json
{ "code": "081abcDEFghiJklMnoPQRsTuvWXYz123" }
```

- 出参：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `access_token` | string | C 端用户 JWT |
| `token_type` | string | 固定 `bearer` |
| `expires_in` | integer | 有效期秒数 |
| `is_new_user` | boolean | 本次是否新建用户；`true` 时通常尚未绑定手机号 |
| `user` | object | 用户信息，见下 |

`user` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 用户 ID |
| `mobile` | string \| null | 已绑定手机号；`null` 表示未绑定，无法被后台赠课 |
| `nickname` | string \| null | 微信昵称；`null` 表示用户尚未设置 |
| `avatar_url` | string \| null | 头像 COS 公网地址；只由头像上传接口写入 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

```json
{
  "access_token": "<user-jwt>",
  "token_type": "bearer",
  "expires_in": 604800,
  "is_new_user": true,
  "user": {
    "id": 1,
    "mobile": null,
    "nickname": null,
    "avatar_url": null,
    "created_at": "2026-10-28T10:00:00",
    "updated_at": "2026-10-28T10:00:00"
  }
}
```

- 说明：微信不再支持静默获取头像昵称，`nickname` / `avatar_url` 由用户在个人中心主动设置。

- 错误：`400 WECHAT_LOGIN_FAILED`、`403 WECHAT_LOGIN_RISKY`、`429 WECHAT_LOGIN_TOO_FREQUENT`、`502 WECHAT_UNAVAILABLE`
- 幂等：同一 openid 重复登录返回同一用户，不会重复创建。

### 5.4 管理员登录

`POST /admin/auth/login`

- 鉴权：无
- 请求体：

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `username` | string | 是 | 1–64 字符 |
| `password` | string | 是 | 1–128 字符 |

```json
{ "username": "admin", "password": "<管理员密码>" }
```

- 出参：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `access_token` | string | Admin JWT |
| `token_type` | string | 固定 `bearer` |
| `expires_in` | integer | 有效期秒数 |
| `admin` | object | `id` / `username` / `role` / `created_at`；`role` 为 `super` 或 `normal` |

```json
{
  "access_token": "<admin-jwt>",
  "token_type": "bearer",
  "expires_in": 28800,
  "admin": {
    "id": 1,
    "username": "admin",
    "role": "super",
    "created_at": "2026-10-26T09:00:00"
  }
}
```

- 错误：`401 INVALID_CREDENTIALS`（账号或密码错误，不区分具体原因）
- 后台不提供注册、验证码、微信登录或找回密码接口。

### 5.5 微信支付异步回调

`POST /payments/wechat/notify`

- 鉴权：**无 JWT**，仅校验微信支付平台签名并解密回调报文。
- 必需请求头（由微信支付发送）：`Wechatpay-Signature`、`Wechatpay-Serial`、`Wechatpay-Timestamp`、`Wechatpay-Nonce`。
- 请求体：微信支付 v3 原始通知 JSON，包含 `id`、`event_type`、`resource`（`algorithm` / `ciphertext` / `nonce` / `associated_data`）。

成功应答（HTTP 200）：

```json
{ "code": "SUCCESS", "message": "OK" }
```

失败应答（非 2xx，微信将重试）：

```json
{ "code": "FAIL", "message": "支付回调验签失败" }
```

服务端处理规则：

1. 使用微信支付公钥与 `WECHAT_PAY_PUBLIC_KEY_ID` 验签，APIv3 密钥解密；失败或报文不合法返回 `400 PAYMENT_CALLBACK_INVALID`，不写入任何数据。
2. 非 `TRANSACTION.SUCCESS` 或 `trade_state != SUCCESS`：不产生授权，仍返回 SUCCESS 确认收到。
3. 校验 `mchid`、`appid`、币种、金额、付款人 openid。
4. 以 `out_trade_no` 对订单加行锁；重复已支付回调直接返回成功，不重复发课。
5. 首次成功：同一事务内订单置为 `paid`、写入 `pay_time` 与唯一 `pay_transaction_id`，并写入 / 续期课程授权，有效期为「支付完成时间 + `COURSE_VALID_DAY` 天」（默认 365 天）。
6. 微信侧已关闭或已退款的交易不会把课程授权写入用户账号。

回调相关错误码：`PAYMENT_MERCHANT_MISMATCH`、`PAYMENT_APPID_MISMATCH`、`PAYMENT_AMOUNT_MISMATCH`、`PAYMENT_PAYER_MISMATCH`、`PAYMENT_ORDER_NOT_FOUND`、`PAYMENT_ORDER_REFUNDED`、`PAYMENT_CALLBACK_INVALID`。这些错误均返回给微信侧，不会暴露给小程序用户。

---

## 6. C 端接口

以下接口除特别说明外，均要求 `Authorization: Bearer <user access_token>`。

### 6.1 绑定微信手机号

`POST /client/auth/bind-mobile`

- 鉴权：C 端用户 JWT
- 请求体：

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `code` | string | 是 | 1–128 字符 | `getPhoneNumber` 返回的动态令牌 |

```json
{ "code": "<getPhoneNumber-code>" }
```

- 出参：`user` 对象（`id` / `mobile` / `nickname` / `avatar_url` / `created_at` / `updated_at`），格式同 5.3。
- 错误：
  - `400 WECHAT_PHONE_CODE_INVALID`：授权凭证无效或过期
  - `400 INVALID_MOBILE`：非中国大陆手机号
  - `409 MOBILE_ALREADY_BOUND`：该手机号已绑定其他用户
  - `429 WECHAT_PHONE_TOO_FREQUENT`
  - `502 WECHAT_PHONE_FAILED`
- 幂等：重复绑定同一手机号直接返回当前用户，不报错。

### 6.2 获取个人中心信息

`GET /client/user/profile`

- 鉴权：C 端用户 JWT
- 入参：无
- 出参：`user` 对象，格式同 5.3。
- 错误：`404 USER_NOT_FOUND`（Token 对应用户已被删除）

### 6.3 课程广场列表

`GET /client/courses`

- 鉴权：C 端用户 JWT（当前实现要求登录）
- Query 参数：

| 参数 | 类型 | 必填 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `page` | integer | 否 | 1 | ≥1 | 页码 |
| `page_size` | integer | 否 | 20 | 1–100 | 每页数量 |
| `keyword` | string | 否 | - | ≤100 字符 | 按课程标题模糊搜索；空白视为未传 |
| `is_hot_topic` | boolean | 否 | - | - | 传 `true` 仅返回热门课程；首页热门板块使用 |

- 出参：`PageResponse<CourseListItem>`

`CourseListItem`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 课程 ID |
| `title` | string | 课程标题 |
| `lecturer` | string | 讲师 |
| `price` | integer | 价格，单位分 |
| `cover_small` | string | 列表小图 URL |
| `icon_url` | string | 课程图标 URL |
| `is_hot_topic` | boolean | 是否热门 |

```json
{
  "items": [
    {
      "id": 1,
      "title": "禾下美学院第一课",
      "lecturer": "禾下老师",
      "price": 19900,
      "cover_small": "https://cdn.example.com/courses/small.jpg",
      "icon_url": "https://cdn.example.com/courses/icon.png",
      "is_hot_topic": true
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

- 排序：创建时间倒序，同时间按 ID 倒序。

### 6.4 我的课程

`GET /client/courses/mine`

- 鉴权：C 端用户 JWT
- Query 参数：`page`（默认 1）、`page_size`（默认 20，1–100）
- 出参：`PageResponse<CourseListItem>`，字段同 6.3。
- 说明：仅返回当前用户已购买或已获赠的课程；按授权时间倒序。

### 6.5 课程详情

`GET /client/courses/{course_id}`

- 鉴权：C 端用户 JWT
- Path 参数：`course_id`，正整数
- 出参：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 课程 ID |
| `title` | string | 标题 |
| `lecturer` | string | 讲师 |
| `description` | string | 课程描述 |
| `price` | integer | 价格，单位分 |
| `cover_big` | string | 详情大图 URL |
| `cover_small` | string | 列表小图 URL |
| `icon_url` | string | 图标 URL |
| `is_hot_topic` | boolean | 是否热门 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |
| `lessons` | array | 全量课时摘要，见下表 |
| `is_owned` | boolean | 当前用户是否已拥有该课程（服务端实时判断） |

`lessons[]` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 课时 ID |
| `title` | string | 课时标题 |
| `duration_seconds` | integer | 视频时长（秒），来自 VOD 媒资信息；`0` 表示尚未取得 |
| `is_finished` | boolean | 当前用户是否已看完该课时（读自 `study_records`），未登录/未拥有时恒为 `false` |

```json
{
  "id": 1,
  "title": "禾下美学院第一课",
  "lecturer": "禾下老师",
  "description": "课程介绍",
  "price": 19900,
  "cover_big": "https://cdn.example.com/courses/big.jpg",
  "cover_small": "https://cdn.example.com/courses/small.jpg",
  "icon_url": "https://cdn.example.com/courses/icon.png",
  "is_hot_topic": true,
  "created_at": "2026-10-27T09:00:00",
  "updated_at": "2026-10-27T09:00:00",
  "lessons": [
    { "id": 10, "title": "第一讲", "duration_seconds": 338, "is_finished": false }
  ],
  "is_owned": false
}
```

- 错误：`404 COURSE_NOT_FOUND`
- 说明：未拥有时仍返回课时标题列表，但不返回 `vod_file_id`、播放签名等任何视频信息；解锁以 `is_owned=true` 为准。课时不单独售卖。授权过期后 `is_owned` 仍为 `true`，课程详情与目录可正常浏览，仅在播放鉴权时返回 `403 COURSE_ACCESS_EXPIRED`；本接口不返回任何有效期或过期标记。

### 6.6 获取播放鉴权

`GET /client/lessons/{lesson_id}/play-auth`

- 鉴权：C 端用户 JWT
- Path 参数：`lesson_id`，正整数
- 出参：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `lesson_id` | integer | 课时 ID |
| `course_id` | integer | 所属课程 ID |
| `file_id` | string | 腾讯云 VOD 文件 ID |
| `app_id` | integer | 腾讯云 VOD AppId |
| `expire_at` | integer | 签名过期时间，Unix 秒 |
| `signature` | string | VOD 临时播放签名（psign，保留给官方插件方案） |
| `play_url` | string \| null | 服务端解析的播放地址，供小程序原生 video 组件播放；VOD 暂不可用时为 `null` |
| `last_position` | integer | 上次播放位置，单位秒；无记录为 0 |
| `duration_seconds` | integer | 视频时长（秒），来自 VOD 媒资信息；`0` 表示 VOD 尚未返回 |

```json
{
  "lesson_id": 10,
  "course_id": 1,
  "file_id": "<vod-file-id>",
  "app_id": 1234567890,
  "expire_at": 1793268000,
  "signature": "<psign>",
  "play_url": "https://<vod-cdn-domain>/<path>/<file>.mp4",
  "last_position": 126,
  "duration_seconds": 338
}
```

- 错误：
  - `404 LESSON_NOT_FOUND`
  - `403 COURSE_NOT_OWNED`：未购买 / 未获赠，不泄露视频信息
  - `403 COURSE_ACCESS_NOT_STARTED`：授权尚未生效
  - `403 COURSE_ACCESS_EXPIRED`：授权已过期，提示「该课程观看权限已过期，可重新购买继续学习」；课程详情与目录仍可浏览
- 说明：签名只绑定 `appId` / `fileId` / 时间窗口，不包含用户身份；每次请求重新签发，过期后必须重新请求。服务端通过 VOD `DescribeMediaInfos` 解析播放地址（优先 H.264 MP4 转码，其次其它 MP4，最后自适应 HLS），按 Key 防盗链规则签名后仅下发给已购买用户，并按 `fileId` 缓存 10 分钟（失败结果缓存 60 秒）。`last_position` 读自 MySQL，Redis 中的缓冲进度不作为续播依据。
- 时长回填：`duration_seconds` 与播放地址同源解析（优先 `BasicInfo.Duration`，其次转码信息，最后 `MetaData.Duration`）；拿到正数时长且与库中不一致时，顺带更新 `lessons.duration_seconds`。后台新建/修改课时也会同步抓取时长，历史数据可用 `python -m scripts.backfill_lesson_durations` 回填。

### 6.7 上报播放进度

`POST /client/study/progress`

- 鉴权：C 端用户 JWT
- 请求体：

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `lesson_id` | integer | 是 | >0 | 课时 ID |
| `current_time` | integer | 是 | ≥0 | 当前播放位置，单位秒 |

```json
{ "lesson_id": 10, "current_time": 135 }
```

- 出参：`204 No Content`，无响应体。
- 说明：
  - 用户身份只取自 JWT，请求体不接收 `user_id`。
  - 服务端写入 Redis 缓冲并标记脏集合，默认每 60 秒批量 upsert 到 MySQL，只保留最新位置。
  - 客户端约定每 15 秒上报一次；Redis 异常时不阻断播放，最多丢失一个上报周期。
  - 进度仅用于续播，不统计时长、完成率，不提供排名或打卡；播放到结尾时客户端上报 `current_time = 0`，下次进入从头播放。
- 错误：参数校验失败返回 422。

### 6.8 标记课时已看完（播放器完成回调）

`POST /api/vod/finish-lesson`

> 该路径按产品约定固定为 `/api/vod/finish-lesson`，不带 `/v1`，与 `/api/v1/client/*` 共用 C 端用户 JWT。

- 鉴权：C 端用户 JWT（Admin Token 调用返回 403）
- 请求体：

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `lesson_id` | integer | 是 | >0 | 课时 ID |

```json
{ "lesson_id": 10 }
```

- 出参：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `lesson_id` | integer | 课时 ID |
| `is_finished` | boolean | 固定为 `true` |
| `finished_at` | string \| null | 首次看完时间（数据库服务器时间，ISO 8601）；重复调用不覆盖 |
| `last_position` | integer | 看完后归零的续播位置，固定为 0 |

```json
{
  "lesson_id": 10,
  "is_finished": true,
  "finished_at": "2026-10-28T13:14:32",
  "last_position": 0
}
```

- 错误：
  - `401`：缺少或无效 C 端 JWT
  - `403 USER_PERMISSION_DENIED`：Admin Token 不能调用
  - `403 COURSE_NOT_OWNED`：未购买 / 未获赠课程
  - `404 LESSON_NOT_FOUND`
  - `422`：参数校验失败
- 说明：
  - 只由播放器 `ended` 事件触发；普通进度上报不能直接把课时标记为完成。
  - 服务端重新校验 `user_course`，写入 `study_records.is_finished=1` 与首次 `finished_at`，把 `last_position` 归零，并清理 Redis 中待落库的旧进度。
  - 幂等：重复调用返回首次完成时间，不产生重复记录；看完后再次进入从 0 开始播放。

### 6.9 创建订单并获取支付参数（微信支付 V3 JSAPI）

`POST /payments/create-order`

- 鉴权：C 端用户 JWT（管理员 Token 会被拒绝）
- 请求体：

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `course_id` | integer | 是 | >0 | 要购买的课程 ID |
| `user_id` | integer | 否 | >0 | 兼容字段；传值时必须等于 JWT 用户 ID，否则 403 |
| `openid` | string | 否 | 1–128 字符 | 兼容字段；传值时必须等于 JWT 用户的 openid，否则 403 |

```json
{ "course_id": 1 }
```

- 身份以 JWT 为准，服务端不会使用请求体中的 `user_id` / `openid` 下单或付款。

- 出参：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `order_no` | string | 商户订单号，`HH` 开头 |
| `course_id` | integer | 课程 ID |
| `amount` | integer | 金额，单位分，服务端按课程价格固化 |
| `status` | string | 新订单固定 `pending` |
| `payment` | object | `wx.requestPayment` 参数 |

`payment` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `time_stamp` | string | 对应 `timeStamp` |
| `nonce_str` | string | 对应 `nonceStr` |
| `package` | string | 对应 `package` |
| `sign_type` | string | 对应 `signType`，默认 `RSA` |
| `pay_sign` | string | 对应 `paySign` |

```json
{
  "order_no": "HH202610281030001234567890abcdef12",
  "course_id": 1,
  "amount": 19900,
  "status": "pending",
  "payment": {
    "time_stamp": "1793268000",
    "nonce_str": "abc123",
    "package": "prepay_id=wx20261028...",
    "sign_type": "RSA",
    "pay_sign": "<pay-sign>"
  }
}
```

- 错误：
  - `404 COURSE_NOT_FOUND`
  - `409 COURSE_ALREADY_OWNED`：有效期内的课程（含永久有效），不能重复下单
  - `409 COURSE_ACCESS_NOT_STARTED`：授权尚未生效
  - `400 COURSE_PRICE_INVALID`：课程价格 ≤ 0，暂不可购买
  - `502 PAYMENT_UNAVAILABLE` / `PAYMENT_CREATE_FAILED`：微信支付下单失败
  - `400 PAYMENT_OPENID_MISSING` / `PAYMENT_AMOUNT_INVALID`
  - `403 PAYMENT_USER_MISMATCH` / `PAYMENT_OPENID_MISMATCH`：请求体身份与 JWT 不一致
- 说明：
  - 客户端不能指定金额、用户或订单状态。
  - 已过期授权允许重新购买；支付成功后复用原授权记录，将有效期刷新为「支付完成时间 + `COURSE_VALID_DAY` 天」（默认 365 天）。
  - 订单先落库再请求微信统一下单；即使统一下单超时，微信回调仍可通过 `order_no` 找回订单并发课。
  - `payment` 字段需转换为微信参数后调用 `Taro.requestPayment`：`timeStamp` / `nonceStr` / `package` / `signType` / `paySign`。
  - 最终支付状态以微信异步回调为准；用户取消支付时订单保持 `pending`，可重新下单或在超时后关单。
  - 兼容接口 `POST /client/orders` 入参与出参相同，仅请求体不接收 `user_id` / `openid`。

### 6.10 查询订单状态（微信支付 V3 JSAPI）

`GET /payments/query-order/{order_no}`

- 鉴权：C 端用户 JWT
- Path 参数：`order_no`，1–64 字符
- 出参：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `order_no` | string | 商户订单号 |
| `course_id` | integer | 课程 ID |
| `course_title` | string \| null | 课程标题（仅展示，不含有效期） |
| `amount` | integer | 金额，单位分 |
| `status` | string | `pending` / `paid` / `closed` / `refunded` |
| `paid_at` | datetime \| null | 支付成功时间；非 `paid` 时为 `null` |
| `created_at` | datetime | 下单时间 |

```json
{
  "order_no": "HH202610281030001234567890abcdef12",
  "course_id": 1,
  "amount": 19900,
  "status": "paid",
  "paid_at": "2026-10-28T10:31:20",
  "created_at": "2026-10-28T10:30:00"
}
```

- 错误：
  - `404 ORDER_NOT_FOUND`（订单不存在或不属于当前用户，不区分两种情况）
  - `502 PAYMENT_QUERY_FAILED` / `PAYMENT_QUERY_INVALID`：主动查单失败或微信返回数据异常
- 说明：
  - 本地订单为 `pending` 时，服务端会主动向微信查单并同步结果；确认支付成功后与回调走同一套幂等发课逻辑。
  - 已支付或已关闭订单直接返回本地状态，不重复发课。
  - 不提供取消订单、查询他人订单或退款接口。
  - 兼容接口 `GET /client/orders/{order_no}` 仍可查询，但不会主动向微信查单。

### 6.11 关闭未支付订单（微信支付 V3 JSAPI）

`POST /payments/close-order/{order_no}`

- 鉴权：C 端用户 JWT
- Path 参数：`order_no`，1–64 字符
- 出参：同 6.10 的订单对象。
- 错误：
  - `404 ORDER_NOT_FOUND`
  - `409 PAYMENT_CLOSE_TOO_EARLY`：下单未满 30 分钟，暂不允许关闭
  - `502 PAYMENT_CLOSE_FAILED`：微信关单失败
- 说明：
  - 仅允许关闭下单超过 30 分钟且仍为 `pending` 的订单。
  - 微信返回订单已支付时，会先查单同步为 `paid` 并发课，不会误关闭已付款订单。
  - 已支付、已关闭、已退款订单直接返回当前状态，不重复处理。

### 6.12 更新个人资料（昵称）

`PUT /client/user/profile`

- 鉴权：C 端用户 JWT
- 请求体：

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `nickname` | string | 是 | 1–32 字符，去首尾空白后不能为空 | 用户主动设置或修改的昵称 |

```json
{ "nickname": "禾下学员" }
```

- 出参：`user` 对象，格式同 5.3。
- 错误：
  - `401 UNAUTHORIZED`：未携带或 Token 无效
  - `403 USER_PERMISSION_DENIED`：使用 Admin Token 调用
  - `404 USER_NOT_FOUND`：Token 对应用户已被删除
  - `422 VALIDATION_ERROR`：昵称空白、超长、包含换行/控制字符，或携带 `avatar_url` 等未声明字段
- 说明：
  - 微信已不支持静默获取昵称，昵称只能由用户在小程序内主动设置（小程序使用 `Input type="nickname"` 触发微信键盘快捷填入）。
  - `avatar_url` 不能通过本接口写入，只能由 6.13 头像上传接口产生。

### 6.13 上传个人头像

`POST /client/user/avatar`

- 鉴权：C 端用户 JWT
- 请求格式：`multipart/form-data`

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `file` | file | 是 | ≤ 5MB；JPG / PNG / WebP | 头像图片，服务端按魔术字节校验真实格式 |

- 出参：`user` 对象（含最新 `avatar_url`），格式同 5.3。
- 错误：
  - `400 INVALID_IMAGE_TYPE`：MIME 不在允许列表、扩展名与内容不一致、或空文件
  - `400 IMAGE_TOO_LARGE`：文件超过 5MB
  - `401 UNAUTHORIZED` / `403 USER_PERMISSION_DENIED`
  - `404 USER_NOT_FOUND`
  - `500 INTERNAL_ERROR`：COS 未配置或上传失败
- 说明：
  - 小程序不直接持有 COS 凭证：图片先传到后端，再由后端写入 COS `avatars/{user_id}/{uuid}.{ext}`，返回公网可读地址。
  - 客户端文件名不参与对象键生成；旧头像对象不自动删除。
  - 小程序侧使用 `Taro.uploadFile`，不要手动设置 `Content-Type`（multipart boundary 由宿主生成）。

---

## 7. 后台接口

以下接口全部要求 `Authorization: Bearer <admin access_token>`。

### 7.1 当前管理员信息

`GET /admin/auth/profile`

- 出参：`{ "id": 1, "username": "admin", "role": "super", "created_at": "..." }`
- 错误：`401 UNAUTHORIZED`；管理员记录被删除时返回 401。
- `role`：`super`=超级管理员（可上传媒资、维护课时），`normal`=普通管理员（只读）。权限以数据库实时值为准，角色调整后下一次请求立即生效。

### 7.2 退出登录

`POST /admin/auth/logout`

- 入参：无
- 出参：`{ "message": "已退出登录" }`
- 说明：JWT 为无状态令牌，服务端不维护黑名单；前端应立即清除本地 Token 与 Redux 状态。Token 在过期前仍可被重放，因此必须依赖 HTTPS 与客户端安全存储。

### 7.3 课程图片直传预签名

`POST /admin/courses/image-presign`

- Query 参数：

| 参数 | 类型 | 必填 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `filename` | string | 是 | - | 1–255 字符 | 原始文件名，仅用于校验扩展名 |
| `content_type` | string | 否 | - | ≤100 字符 | 浏览器声明的 MIME，必须与扩展名一致 |
| `expires_in` | integer | 否 | 600 | 60–3600 | 预签名有效期，秒 |

- 出参：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `object_key` | string | 服务端生成的对象键，客户端不可指定 |
| `upload_url` | string | COS 预签名 PUT URL |
| `public_url` | string | 上传完成后可访问的图片 URL |
| `headers` | object | 上传时必须携带的请求头，如 `{"Content-Type": "image/png"}` |
| `expires_in` | integer | 有效期秒数 |
| `method` | string | 固定 `PUT` |

```json
{
  "object_key": "courses/2026/10/4f2c...e1.png",
  "upload_url": "https://bucket.cos.ap-guangzhou.myqcloud.com/courses/...",
  "public_url": "https://cdn.example.com/courses/2026/10/4f2c...e1.png",
  "headers": { "Content-Type": "image/png" },
  "expires_in": 600,
  "method": "PUT"
}
```

- 允许类型：`.jpg` / `.jpeg` / `.png` / `.webp`，且扩展名与 `content_type` 必须匹配。
- 错误：`400 INVALID_IMAGE_TYPE`、`400 INVALID_UPLOAD_EXPIRES`、`500 INTERNAL_ERROR`（COS 未配置或预签名失败）。
- 说明：
  - 图片二进制不经过业务服务器，COS 密钥不下发前端。
  - 上传请求只携带 `Content-Type`，**不要携带 Admin Token**，避免 Token 泄露给第三方存储。
  - 上传成功后，把 `public_url` 填入课程三张图片字段。

### 7.4 后台课程列表

`GET /admin/courses`

- Query：`page`、`page_size`、`keyword`（课程标题模糊搜索）、`is_hot_topic`
- 出参：`PageResponse<CourseResponse>`
- `CourseResponse`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 课程 ID |
| `title` | string | 标题 |
| `lecturer` | string | 讲师 |
| `description` | string | 描述 |
| `price` | integer | 价格，单位分 |
| `cover_big` | string | 详情大图 |
| `cover_small` | string | 列表小图 |
| `icon_url` | string | 图标 |
| `is_hot_topic` | boolean | 是否热门 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

- 排序：创建时间倒序。

### 7.5 新建课程

`POST /admin/courses`

- 请求体：

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `title` | string | 是 | 1–200 字符 | 标题 |
| `lecturer` | string | 是 | 1–100 字符 | 讲师 |
| `description` | string | 是 | 1–10000 字符 | 描述 |
| `price` | integer | 是 | ≥0，单位分 | 价格 |
| `cover_big` | string | 是 | HTTP(S) URL，≤1024 字符 | 详情大图 |
| `cover_small` | string | 是 | HTTP(S) URL，≤1024 字符 | 列表小图 |
| `icon_url` | string | 是 | HTTP(S) URL，≤1024 字符 | 图标 |
| `is_hot_topic` | boolean | 否 | 默认 `false` | 是否展示在首页热门板块 |

```json
{
  "title": "禾下美学院第一课",
  "lecturer": "禾下老师",
  "description": "课程介绍",
  "price": 19900,
  "cover_big": "https://cdn.example.com/courses/big.jpg",
  "cover_small": "https://cdn.example.com/courses/small.jpg",
  "icon_url": "https://cdn.example.com/courses/icon.png",
  "is_hot_topic": true
}
```

- 出参：`CourseResponse`，HTTP 200。
- 说明：课程创建后才能添加课时；课时没有价格，不可单独售卖。

### 7.6 后台课程详情

`GET /admin/courses/{course_id}`

- Path：`course_id` 正整数
- 出参：`CourseResponse`
- 错误：`404 COURSE_NOT_FOUND`

### 7.7 更新课程

`PUT /admin/courses/{course_id}`

- 请求体：下列字段全部可选，但**至少提供一个**，且不能显式传 `null`：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `title` | string | 1–200 字符 |
| `lecturer` | string | 1–100 字符 |
| `description` | string | 1–10000 字符 |
| `price` | integer | ≥0，单位分 |
| `cover_big` | string | HTTP(S) URL |
| `cover_small` | string | HTTP(S) URL |
| `icon_url` | string | HTTP(S) URL |
| `is_hot_topic` | boolean | - |

```json
{ "price": 29900, "is_hot_topic": false }
```

- 出参：更新后的 `CourseResponse`
- 错误：`404 COURSE_NOT_FOUND`、`400 INVALID_UPDATE_FIELD`（空对象或字段为 null）
- 说明：更新价格只影响后续新订单，不修改历史订单金额。

### 7.8 删除课程

`DELETE /admin/courses/{course_id}`

- 出参：`{ "message": "课程已删除" }`
- 错误：
  - `404 COURSE_NOT_FOUND`
  - `409 COURSE_IN_USE`：课程下存在课时、订单、课程授权或赠课记录
- 说明：只允许删除完全空的课程，避免破坏交易记录与学习历史。

### 7.9 按课程查询课时列表

`GET /admin/lessons`

- Query 参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `course_id` | integer | 是 | 课程 ID，>0 |

- 出参：`LessonResponse[]`（数组，不分页）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 课时 ID |
| `course_id` | integer | 所属课程 ID |
| `title` | string | 课时标题 |
| `sort_order` | integer | 排序值，越小越靠前 |
| `file_id` | string | 腾讯云 VOD FileId（即媒资库 `vod_media.file_id`） |
| `vod_file_id` | string | 与 `file_id` 同值，兼容旧调用方 |
| `video_name` | string \| null | 绑定视频名称，来自媒资库 |
| `cover_url` | string \| null | 绑定视频封面，来自媒资库 |
| `duration_seconds` | integer | 视频时长（秒），0 表示尚未取得 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

- 错误：`404 COURSE_NOT_FOUND`
- 排序：`sort_order` 升序，相同值按课时 ID 升序。

### 7.10 新建课时

`POST /admin/lessons`（仅超级管理员；别名 `POST /admin/lesson/create`）

- 请求体：

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `course_id` | integer | 是 | >0 | 所属课程 |
| `title` | string | 是 | 1–200 字符 | 课时标题 |
| `file_id` | string | 是 | 1–128 字符 | 从媒资库选择的 VOD FileId |
| `vod_file_id` | string | 否 | 1–128 字符 | 兼容字段，等价于 `file_id`；二者都传时必须相同 |
| `sort_order` | integer | 否 | 0–99999 | 排序值；不传时自动追加到课程末尾（当前最大值 + 1） |

```json
{
  "course_id": 1,
  "title": "第一讲：认识禾下",
  "file_id": "<tencent-vod-file-id>",
  "sort_order": 10
}
```

- 出参：`LessonResponse`
- 错误：
  - `404 COURSE_NOT_FOUND`
  - `400 VOD_MEDIA_NOT_FOUND`：FileId 不在本地媒资库中
  - `409 VOD_MEDIA_NOT_READY`：视频仍在转码或转码失败，不能绑定
  - `422`：缺少 `file_id`，或 `file_id` 与 `vod_file_id` 不一致
- 说明：课时的 `duration_seconds` 自动取媒资库时长（缺省时回查 VOD），无需手工填写；课时不设价格，不存在单独购买 / 单独赠送入口。

### 7.11 后台课时详情

`GET /admin/lessons/{lesson_id}`

- 出参：`LessonResponse`
- 错误：`404 LESSON_NOT_FOUND`

### 7.12 更新课时

`PUT /admin/lessons/{lesson_id}`（仅超级管理员；别名 `PUT /admin/lesson/update`，请求体需额外携带 `id`）

- 请求体（至少一个字段，不能为 null）：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `title` | string | 1–200 字符 |
| `file_id` | string | 1–128 字符，必须为已转码完成的媒资 |
| `vod_file_id` | string | 兼容字段，规则同 `file_id` |
| `sort_order` | integer | 0–99999 |

```json
{ "title": "第一讲：重新认识禾下", "sort_order": 20 }
```

- 出参：更新后的 `LessonResponse`
- 错误：`404 LESSON_NOT_FOUND`、`400 INVALID_UPDATE_FIELD`、`400 VOD_MEDIA_NOT_FOUND`、`409 VOD_MEDIA_NOT_READY`
- 说明：不允许修改 `course_id`；课时跨课程迁移会破坏已有课程授权与学习记录语义。替换视频时会重新校验媒资状态并同步时长。

### 7.13 删除课时

`DELETE /admin/lessons/{lesson_id}`

- 出参：`{ "message": "课时已删除" }`
- 错误：
  - `404 LESSON_NOT_FOUND`
  - `409 LESSON_HAS_PROGRESS`：课时存在学习记录
- 说明：有学习记录的课时禁止删除。

### 7.14 按手机号赠课

`POST /admin/gifts`

- 请求体：

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `mobile` | string | 是 | 11 位中国大陆手机号 `^1[3-9]\d{9}$` | 赠课唯一匹配字段 |
| `course_id` | integer | 是 | >0 | 要赠送的课程 |
| `validity` | string | 否 | `one_year` / `permanent`，默认 `one_year` | 赠送后有效期；一年从赠课操作时间（UTC）起算，永久有效两列均为 null |

```json
{ "mobile": "13800138000", "course_id": 1, "validity": "one_year" }
```

- 出参：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `mobile` | string | 手机号 |
| `course_id` | integer | 课程 ID |
| `user_id` | integer | 按手机号匹配到的用户 ID |
| `gifted` | boolean | 本次是否真实新增授权 |
| `gift_log_id` | integer \| null | 仅真实新增时返回日志 ID |
| `message` | string | 结果说明 |

首次发放：

```json
{
  "mobile": "13800138000",
  "course_id": 1,
  "user_id": 7,
  "gifted": true,
  "gift_log_id": 12,
  "message": "赠课成功"
}
```

重复发放（HTTP 200，幂等）：

```json
{
  "mobile": "13800138000",
  "course_id": 1,
  "user_id": 7,
  "gifted": false,
  "gift_log_id": null,
  "message": "该用户已拥有该课程，无需重复赠课"
}
```

- 错误：
  - `404 COURSE_NOT_FOUND`
  - `404 GIFT_MOBILE_NOT_BOUND`：手机号未绑定小程序，无法赠课
  - `409 MOBILE_AMBIGUOUS`：同一手机号对应多个用户，拒绝任意选择
  - `409 GIFT_CONFLICT`：并发写入冲突
- 硬性规则：
  - **赠课唯一依赖 `mobile` 匹配，未绑定手机号用户无法被后台赠课。**
  - **同一手机号 + 课程不可重复发放；重复请求不新增授权、不新增日志。**
  - 只有真实新增授权时才写入赠课日志，日志记录操作管理员、手机号、课程与时间。
  - 赠课解锁整门课程的全部课时，不修改订单、不触达微信支付。
  - 赠课后默认一年有效，`valid_start_at = 赠课操作时间（UTC）`、`valid_end_at = +1 年`；选择 `permanent` 时两列均为 null。有效期只在播放鉴权时校验，C 端不展示。

### 7.15 赠课日志

`GET /admin/gifts/logs`

- Query 参数：

| 参数 | 类型 | 必填 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `page` | integer | 否 | 1 | ≥1 | 页码 |
| `page_size` | integer | 否 | 20 | 1–100 | 每页数量 |
| `mobile` | string | 否 | - | 11 位手机号 | 精确匹配 |
| `course_id` | integer | 否 | - | >0 | 课程筛选 |
| `admin_id` | integer | 否 | - | >0 | 操作管理员筛选 |
| `created_from` | datetime | 否 | - | ISO 8601 | 开始时间 |
| `created_to` | datetime | 否 | - | ISO 8601 | 结束时间，不得早于开始时间 |

- 出参：`PageResponse<GiftLogResponse>`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 日志 ID |
| `admin_id` | integer | 操作管理员 ID |
| `mobile` | string | 被赠手机号 |
| `course_id` | integer | 课程 ID |
| `created_at` | datetime | 发放时间 |
| `admin_username` | string \| null | 管理员账号展示字段 |
| `course_title` | string \| null | 课程标题展示字段 |

```json
{
  "items": [
    {
      "id": 12,
      "admin_id": 1,
      "mobile": "13800138000",
      "course_id": 1,
      "created_at": "2026-10-28T11:00:00",
      "admin_username": "admin",
      "course_title": "禾下美学院第一课"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

- 排序：发放时间倒序。

### 7.16 后台订单查询（只读）

`GET /admin/orders`

- Query 参数：

| 参数 | 类型 | 必填 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `page` | integer | 否 | 1 | ≥1 | 页码 |
| `page_size` | integer | 否 | 20 | 1–100 | 每页数量 |
| `order_no` | string | 否 | - | ≤64 字符 | 精确订单号 |
| `user_id` | integer | 否 | - | >0 | 用户 ID |
| `course_id` | integer | 否 | - | >0 | 课程 ID |
| `mobile` | string | 否 | - | 11 位手机号 | 按下单用户手机号筛选 |
| `status` | string | 否 | - | `pending` / `paid` / `closed` / `refunded` | 订单状态 |
| `created_from` | datetime | 否 | - | ISO 8601 | 下单开始时间 |
| `created_to` | datetime | 否 | - | ISO 8601 | 下单结束时间 |

- 出参：`PageResponse<AdminOrderResponse>`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 订单主键 |
| `order_no` | string | 商户订单号 |
| `course_id` | integer | 课程 ID |
| `amount` | integer | 金额，单位分 |
| `status` | string | `pending` / `paid` / `closed` / `refunded` |
| `paid_at` | datetime \| null | 支付时间 |
| `created_at` | datetime | 下单时间 |
| `user_id` | integer | 下单用户 ID |
| `user_mobile` | string \| null | 用户手机号展示字段 |
| `course_title` | string \| null | 课程标题展示字段 |

- 排序：下单时间倒序。
- 说明：**只读接口**，后台不支持下单、支付、修改状态或退款；不存在对应写接口。

### 7.17 系统配置列表

`GET /admin/configs`

- 入参：无
- 出参：

```json
{
  "items": [
    {
      "id": 1,
      "config_key": "tab_home_text",
      "config_value": "首页",
      "default_value": "首页",
      "description": "底部导航首页文案",
      "updated_at": "2026-10-28T09:00:00"
    }
  ]
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 配置主键 |
| `config_key` | string | 配置键，创建后不可修改 |
| `config_value` | string | 当前值 |
| `default_value` | string | 出厂默认值 |
| `description` | string \| null | 说明 |
| `updated_at` | datetime | 更新时间 |

### 7.18 全部配置恢复默认

`POST /admin/configs/reset`

- 入参：无
- 出参：同 7.17 的配置列表
- 说明：所有配置的当前值恢复为数据库中的默认值；配置键不变，不新增或删除配置项。

### 7.19 修改单个配置

`PUT /admin/configs/{config_key}`

- Path：`config_key`，1–64 字符，必须是已存在的配置键
- 请求体：

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `config_value` | string | 是 | ≤4096 字符，可为空字符串 | 新的展示文案 |

```json
{ "config_value": "商学院" }
```

- 出参：更新后的单个配置对象，格式同 7.17 的 `items[]`
- 错误：`404 CONFIG_NOT_FOUND`（配置键不存在）
- 说明：只能修改值，不能修改键、不能新增或删除配置项；价格、权限、业务规则不通过系统配置管理。

### 7.20 单个配置恢复默认

`POST /admin/configs/{config_key}/reset`

- Path：`config_key`，已存在的配置键
- 入参：无
- 出参：恢复后的单个配置对象
- 错误：`404 CONFIG_NOT_FOUND`

### 7.21 媒资库列表

`GET /admin/vod/list`

- 权限：所有管理员（普通管理员只读）
- Query 参数：

| 参数 | 类型 | 必填 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `page` | integer | 否 | 1 | ≥1 | 页码 |
| `page_size` | integer | 否 | 20 | 1–100 | 每页条数 |
| `keyword` | string | 否 | - | ≤100 字符 | 视频名称模糊搜索（不区分大小写） |
| `file_id` | string | 否 | - | ≤128 字符 | 按 VOD FileId 精确查询 |
| `status` | integer | 否 | - | 0 / 1 / 2 | 0=转码中，1=正常可用，2=失败 |

- 出参：`PageResponse<VodMediaResponse>`
- `VodMediaResponse`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 媒资 ID |
| `file_id` | string | 腾讯云 VOD FileId（唯一） |
| `video_name` | string | 视频名称（默认取上传文件名，可由后台修改） |
| `duration_seconds` | integer | 时长（秒），0 表示尚未取得 |
| `cover_url` | string \| null | 封面地址，由 VOD 自动截取视频首帧生成，后台不可修改 |
| `uploader_id` | integer \| null | 上传管理员 ID |
| `status` | integer | 0=转码中，1=正常可用，2=上传/转码失败 |
| `fail_reason` | string \| null | 失败原因，`status=2` 时提供 |
| `created_at` | datetime | 上传时间 |
| `updated_at` | datetime | 更新时间 |

- 排序：上传时间倒序（同秒按 ID 倒序）。
- 错误：`401 UNAUTHORIZED`、`422`（参数不合法）。

### 7.22 上传视频到媒资库

`POST /admin/vod/upload`

- 权限：仅超级管理员（`normal` 返回 `403 ADMIN_SUPER_REQUIRED`）
- Content-Type：`multipart/form-data`
- 表单字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | file | 是 | 本地视频，支持 `.mp4` / `.m4v`；大小由 `VOD_UPLOAD_MAX_SIZE_MB` 控制（默认 2048MB） |

- 服务端流程：`ApplyUpload`（自动携带 `Procedure=VOD_UPLOAD_PROCEDURE` 加密转码任务流）→ COS SDK 直传 → `CommitUpload` → 写入 `vod_media`（`status=0`）→ 立即回查一次转码状态。
- 出参：`VodMediaResponse`，HTTP 200。
- 错误：
  - `400 INVALID_VIDEO_FILE`：扩展名或文件名不合法
  - `400 EMPTY_VIDEO_FILE`：空文件
  - `413 VIDEO_TOO_LARGE`：超过大小上限
  - `502 VOD_UPLOAD_FAILED`：VOD Apply / 上传 / Commit 失败，**不会写入媒资记录**
  - `500 VOD_MEDIA_SAVE_FAILED`：VOD 已上传但本地媒资落库失败
  - `403 ADMIN_SUPER_REQUIRED`
- 说明：腾讯云 SecretId / SecretKey 与上传凭证只在服务端使用，前端只拿 FileId 与元数据；上传完成后视频仍在转码时 `status=0`，需通过 7.23 同步或等待后台自动同步为 `1` 后才能绑定课时。

```json
{
  "id": 12,
  "file_id": "<tencent-vod-file-id>",
  "video_name": "第 1 讲 · 认识禾下.mp4",
  "duration_seconds": 0,
  "cover_url": null,
  "uploader_id": 1,
  "status": 0,
  "fail_reason": null,
  "created_at": "2026-10-29T10:00:00",
  "updated_at": "2026-10-29T10:00:00"
}
```

### 7.23 同步 VOD 转码状态

`POST /admin/vod/sync-status`

- 权限：仅超级管理员
- 请求体（可省略；字段均可选）：

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `media_ids` | integer[] | ≤100，元素 >0 | 按本地媒资 ID 同步 |
| `file_ids` | string[] | ≤100，元素 ≤128 字符 | 按 VOD FileId 同步 |

```json
{ "media_ids": [12, 13] }
```

- 出参：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `items` | `VodMediaResponse[]` | 本次同步涉及的媒资最新状态 |
| `message` | string | 结果说明 |

- 处理规则：`PROCESSING` 或无产物地址 → `status=0`；任一转码任务 `ERROR` 或 `ErrCode≠0` → `status=2` 并写入 `fail_reason`；全部任务完成（显式 `FINISH`，或线上仅返回产物 `Url`）→ `status=1` 并回填时长；封面始终以 VOD 自动截取的首帧截图为准并回填（后台不可修改），名称保留后台修改值、仅本地为空时用 VOD 值补齐；VOD 中已找不到该视频 → `status=2`。
- 未指定目标时，默认同步最近 50 条需要更新的媒资：`status=0` 的，以及 `status=1` 但封面为空的（历史数据回填）。
- 错误：`502 VOD_SYNC_FAILED`、`422`、`403 ADMIN_SUPER_REQUIRED`。

### 7.24 媒资详情

`GET /admin/vod/{media_id}`

- 权限：所有管理员
- Path：`media_id` 正整数
- 出参：`VodMediaResponse`
- 错误：`404 VOD_MEDIA_NOT_FOUND`

### 7.25 修改媒资名称

`PUT /admin/vod/{media_id}`

- 权限：仅超级管理员（`normal` 返回 `403 ADMIN_SUPER_REQUIRED`）
- Path：`media_id` 正整数
- 请求体：

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `video_name` | string | 是 | 1–200 字符，不能含控制字符 | 视频展示名称，保存前去除首尾空白 |

```json
{
  "video_name": "第 1 讲 · 认识禾下"
}
```

- 出参：更新后的 `VodMediaResponse`。
- 说明：封面由 VOD 自动截取视频首帧生成，**不提供修改或上传入口**；请求体带 `cover_url` 会因未知字段返回 422。FileId、时长、转码状态同样以 VOD 为准。
- 错误：`404 VOD_MEDIA_NOT_FOUND`、`422`（名称为空/超长/含控制字符、携带 `cover_url`）、`403 ADMIN_SUPER_REQUIRED`。

### 7.26 删除媒资（仅本地记录）

`DELETE /admin/vod/{media_id}`

- 权限：仅超级管理员
- Path：`media_id` 正整数
- 出参：`MessageResponse`，`{"message": "媒资已删除"}`
- 行为：
  - 只删除本地 `vod_media` 记录，**不删除腾讯云 VOD 原文件**；
  - 若仍有课时绑定该 `file_id`，返回 `409 VOD_MEDIA_IN_USE`，需先解绑课时（或改为其他视频）再删除；
  - 失败或绑定中都不会删除任何数据。
- 错误：`404 VOD_MEDIA_NOT_FOUND`、`409 VOD_MEDIA_IN_USE`、`403 ADMIN_SUPER_REQUIRED`。

### 7.27 用户课程授权查询（只读）

`GET /admin/user-courses`

- 鉴权：Admin JWT
- Query 参数：

| 参数 | 类型 | 必填 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `page` | integer | 否 | 1 | ≥1 | 页码 |
| `page_size` | integer | 否 | 20 | 1–100 | 每页数量 |
| `mobile` | string | 否 | - | 11 位手机号 | 精确匹配用户手机号 |
| `course_id` | integer | 否 | - | >0 | 课程筛选 |
| `status` | string | 否 | - | `valid` / `expired` / `permanent` | 按服务端当前时间计算有效期状态 |

- 出参：`PageResponse<AdminUserCourseResponse>`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 授权记录 ID |
| `user_id` | integer | 用户 ID |
| `user_mobile` | string \| null | 用户手机号展示字段 |
| `course_id` | integer | 课程 ID |
| `course_title` | string \| null | 课程标题展示字段 |
| `source` | string | `buy` / `gift` |
| `valid_start_at` | datetime \| null | 生效时间（UTC）；两列均为 null 表示永久有效 |
| `valid_end_at` | datetime \| null | 过期时间（UTC）；两列均为 null 表示永久有效 |
| `status` | string | `valid` / `expired` / `permanent` |
| `created_at` | datetime | 授权创建时间 |

- 排序：授权创建时间倒序。
- 说明：**只读接口**，不提供修改有效期、补发授权或下单能力；时间由前端换算为 Asia/Shanghai 展示。C 端任何接口都不返回有效期字段或过期标记。

### 7.28 用户课程管理

用户课程管理页使用以下 4 个接口，全部要求 Admin JWT（`super` / `normal` 均可）。
管理员操作免费，不产生订单或支付；一个用户 + 一门课程始终只有一条 `user_courses` 记录。

#### 7.28.1 查找用户

`GET /admin/users/lookup`

- Query 参数：

| 参数 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `keyword` | string | 是 | 11 位手机号或正整数用户 ID | 精确匹配 |

- 出参：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `user_id` | integer | 用户 ID |
| `nickname` | string \| null | 用户昵称 |
| `mobile` | string \| null | 绑定手机号 |
| `avatar_url` | string \| null | 头像地址 |

- 错误：`400 INVALID_USER_KEYWORD`、`404 USER_NOT_FOUND`、`409 MOBILE_AMBIGUOUS`（手机号对应多个用户，请改用用户 ID）。

#### 7.28.2 用户已拥有课程

`GET /admin/users/{user_id}/courses`

- Query 参数：`page`（默认 1，≥1）、`page_size`（默认 20，1–100）
- 出参：`PageResponse<AdminUserCourseItem>`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `course_id` | integer | 课程 ID |
| `course_title` | string | 课程名称 |
| `course_cover` | string \| null | 课程封面（`cover_small`） |
| `source` | string | `purchase`（支付购买）/ `gift`（后台赠课） |
| `valid_start_at` | datetime \| null | 生效时间（UTC） |
| `expire_time` | datetime \| null | 过期时间（UTC）；null 表示永久有效 |
| `expired` | boolean | 是否已过期（按服务端当前 UTC 时间计算） |
| `created_at` | datetime | 授权创建时间 |

- 错误：`404 USER_NOT_FOUND`。

#### 7.28.3 赠课 / 重置有效期

`POST /admin/users/grant-course`

```json
{
  "user_id": 12,
  "course_id": 3,
  "valid_days": 365
}
```

| 参数 | 类型 | 必填 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `user_id` | integer | 是 | - | >0 | 目标用户 |
| `course_id` | integer | 是 | - | >0 | 目标课程 |
| `valid_days` | integer | 否 | 365 | 1–36500 | 从操作时间（UTC）起算的有效天数 |

- 语义：
  - 用户原本不拥有课程：新增一条 `user_courses`，`source=gift`，`action=gift`；
  - 用户已拥有（无论 `buy` 还是 `gift`）：只更新原记录的 `valid_start_at` / `valid_end_at`，并将 `source` 置为 `gift`，`action=reset`；
  - 绝不插入第二条授权。
- 出参：`user_id`、`course_id`、`source`（固定 `gift`）、`valid_start_at`、`expire_time`（UTC）、`expired=false`、`action`（`gift` / `reset`）、`log_id`、`message`。
- 留痕：每次操作写入 `user_course_logs`，包含管理员 ID、用户 ID、课程 ID、操作类型、有效期与操作时间。
- 错误：`404 USER_NOT_FOUND`、`404 COURSE_NOT_FOUND`、`409 GIFT_CONFLICT`。

#### 7.28.4 收回课程授权

`POST /admin/users/revoke-course`

```json
{
  "user_id": 12,
  "course_id": 3
}
```

- 语义：删除匹配的 `user_courses` 行并写入 `action=revoke` 的操作日志；日志中的 `expire_time` 记录被收回的原有效期。
- 出参：`user_id`、`course_id`、`revoked=true`、`log_id`、`message`。
- 错误：`404 USER_NOT_FOUND`、`404 COURSE_NOT_FOUND`、`404 USER_COURSE_NOT_FOUND`。

> 时间字段均为 UTC naive datetime，管理后台换算为 Asia/Shanghai 展示；C 端不展示有效期。

---

## 8. 错误码汇总

### 8.1 认证与权限

| HTTP | code | 说明 |
| --- | --- | --- |
| 401 | `UNAUTHORIZED` | 未携带 Token、Token 无效或过期 |
| 401 | `INVALID_CREDENTIALS` | 管理员账号或密码错误 |
| 403 | `USER_PERMISSION_DENIED` | Admin Token 访问 C 端接口 |
| 403 | `ADMIN_PERMISSION_DENIED` | C 端 Token 访问后台接口 |
| 403 | `ADMIN_SUPER_REQUIRED` | 普通管理员调用仅超级管理员可用的写接口 |
| 403 | `COURSE_NOT_OWNED` | 未购买 / 未获赠课程，禁止播放 |
| 403 | `COURSE_ACCESS_NOT_STARTED` | 课程授权尚未生效，禁止播放 / 下单 |
| 403 | `COURSE_ACCESS_EXPIRED` | 课程观看权限已过期，播放被拦截；下单接口允许重新购买 |

### 8.2 用户与微信

| HTTP | code | 说明 |
| --- | --- | --- |
| 400 | `WECHAT_LOGIN_FAILED` | 微信登录凭证无效 |
| 403 | `WECHAT_LOGIN_RISKY` | 微信账号风险 |
| 429 | `WECHAT_LOGIN_TOO_FREQUENT` | 登录过于频繁 |
| 502 | `WECHAT_UNAVAILABLE` | 微信服务不可用 |
| 400 | `WECHAT_PHONE_CODE_INVALID` | 手机号授权凭证无效 |
| 429 | `WECHAT_PHONE_TOO_FREQUENT` | 手机号操作过于频繁 |
| 502 | `WECHAT_PHONE_FAILED` | 微信手机号服务失败 |
| 400 | `INVALID_MOBILE` | 手机号格式不正确 |
| 400 | `INVALID_USER_KEYWORD` | 用户搜索关键词既不是手机号也不是用户 ID |
| 409 | `MOBILE_ALREADY_BOUND` | 手机号已绑定其他用户 |
| 404 | `USER_NOT_FOUND` | 用户不存在 |
| 404 | `USER_COURSE_NOT_FOUND` | 用户未拥有该课程，无法收回 |

### 8.3 课程、课时、媒资与赠课

| HTTP | code | 说明 |
| --- | --- | --- |
| 404 | `COURSE_NOT_FOUND` | 课程不存在 |
| 404 | `LESSON_NOT_FOUND` | 课时不存在 |
| 409 | `COURSE_IN_USE` | 课程存在课时 / 订单 / 授权 / 赠课记录 |
| 409 | `LESSON_HAS_PROGRESS` | 课时存在学习记录 |
| 409 | `COURSE_ALREADY_OWNED` | 有效期内已拥有课程，不能重复下单 |
| 409 | `COURSE_ACCESS_NOT_STARTED` | 授权尚未生效，不能重复下单 |
| 400 | `COURSE_PRICE_INVALID` | 课程价格 ≤ 0 |
| 400 | `INVALID_UPDATE_FIELD` | 更新至少一个字段且不能为 null |
| 404 | `GIFT_MOBILE_NOT_BOUND` | 手机号未绑定，无法赠课 |
| 409 | `MOBILE_AMBIGUOUS` | 手机号对应多个用户 |
| 409 | `GIFT_CONFLICT` | 赠课并发冲突 |
| 400 / 404 | `VOD_MEDIA_NOT_FOUND` | 媒资不存在（课时绑定返回 400，媒资详情返回 404） |
| 409 | `VOD_MEDIA_NOT_READY` | 视频仍在转码或转码失败，不能绑定课时 |
| 409 | `VOD_MEDIA_IN_USE` | 媒资仍被课时绑定，不能删除 |
| 400 | `INVALID_VIDEO_FILE` | 视频扩展名或文件名不合法 |
| 400 | `EMPTY_VIDEO_FILE` | 上传的视频为空文件 |
| 413 | `VIDEO_TOO_LARGE` | 视频超过 `VOD_UPLOAD_MAX_SIZE_MB` |
| 500 | `VOD_MEDIA_SAVE_FAILED` | VOD 上传成功但媒资落库失败 |
| 502 | `VOD_UPLOAD_FAILED` | VOD 上传 / Commit 失败，未产生媒资记录 |
| 502 | `VOD_SYNC_FAILED` | 查询 VOD 转码状态失败 |

### 8.4 订单、支付与上传

| HTTP | code | 说明 |
| --- | --- | --- |
| 404 | `ORDER_NOT_FOUND` | 订单不存在或不属于当前用户 |
| 502 | `PAYMENT_UNAVAILABLE` | 微信支付服务不可用 |
| 502 | `PAYMENT_CREATE_FAILED` | 微信统一下单失败 |
| 400 | `PAYMENT_OPENID_MISSING` | 用户 openid 缺失 |
| 400 | `PAYMENT_AMOUNT_INVALID` | 订单金额不合法 |
| 400 | `PAYMENT_CALLBACK_INVALID` | 回调验签或报文不合法 |
| 400 | `PAYMENT_MERCHANT_MISMATCH` | 回调商户号不匹配 |
| 400 | `PAYMENT_APPID_MISMATCH` | 回调 AppID 不匹配 |
| 400 | `PAYMENT_AMOUNT_MISMATCH` | 回调金额 / 币种不匹配 |
| 400 | `PAYMENT_PAYER_MISMATCH` | 回调付款人与下单用户不一致 |
| 400 | `PAYMENT_ORDER_REFUNDED` | 订单已退款，不能再发放课程 |
| 404 | `PAYMENT_ORDER_NOT_FOUND` | 回调订单不存在 |
| 403 | `PAYMENT_USER_MISMATCH` | 下单请求体的 user_id 与 JWT 不一致 |
| 403 | `PAYMENT_OPENID_MISMATCH` | 下单请求体的 openid 与 JWT 用户不一致 |
| 409 | `PAYMENT_CLOSE_TOO_EARLY` | 下单未满 30 分钟，暂不能关单 |
| 502 | `PAYMENT_CLOSE_FAILED` | 微信关单失败 |
| 502 | `PAYMENT_QUERY_FAILED` | 主动查询微信订单失败 |
| 502 | `PAYMENT_QUERY_INVALID` | 微信查单返回数据异常 |
| 409 | `PAYMENT_CONFLICT` | 支付结果并发处理冲突 |
| 400 | `INVALID_IMAGE_TYPE` | 图片格式不支持或 MIME 不一致 |
| 400 | `IMAGE_TOO_LARGE` | 头像文件超过 5MB |
| 400 | `INVALID_UPLOAD_EXPIRES` | 预签名有效期不合法 |

### 8.5 配置

| HTTP | code | 说明 |
| --- | --- | --- |
| 404 | `CONFIG_NOT_FOUND` | 配置键不存在 |

---

## 9. 前端对接注意事项

1. C 端所有请求统一携带 `Authorization: Bearer <user token>`；Token 失效时清空本地会话并重新 `wx.login`。
2. Admin 与 C 端 Token 使用不同存储键（后台为 `spark.admin.session.v1`），禁止在同一个请求中同时携带两套 Token。
3. 上传 COS 图片时只使用 `upload_url` 和 `headers`，不要附加业务 Authorization 头。
4. 支付成功后不要只依赖 `requestPayment` 的回调结果：跳转支付成功页并轮询 `GET /payments/query-order/{order_no}`，以服务端 `paid` 为准，确认后停止轮询；取消支付时订单保持 `pending`，可重试。
5. 播放鉴权接口返回的 `play_url` 直接交给原生 `video` 组件；`signature` 仅保留给官方插件方案，前端不得自行拼接 CDN 地址或延长有效期。地址获取失败时展示可重试提示。
6. 课程详情页未拥有时不返回任何视频信息，前端不提供试看入口。
7. 后台不提供任何学员侧操作；订单页没有操作列，课时页没有播放按钮。
8. 生产环境所有请求必须走 HTTPS；Swagger / ReDoc / OpenAPI 由 Nginx 屏蔽。
