# 禾下美学院｜API 接口文档

本文档以 `backend/app/api/v1` 的实际实现为准，覆盖 C 端、管理后台、公开接口与微信支付回调。除 C 端认证接口（`/auth/*` 使用 `camelCase`）外，字段命名统一使用 `snake_case`；时间、金额、分页约定见「通用约定」。

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
| C 端用户 | `Authorization: Bearer <user access_token>` | `POST /auth/wx-login` | 7 天（10080 分钟） |
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
| 订单状态 `status` | `pending` / `paid` / `closed` | 对外只有三种状态：`pending` 待支付；`paid` 已支付；`closed` 已取消（用户主动取消、超时自动关闭或微信侧已关闭）。历史 `refunded` 数据仅保留在库内，C 端列表与详情均不返回，也不支持按该状态筛选 |
| 课程授权来源 | `buy` / `gift` | 内部字段，不对外返回；购买与赠课都写入统一授权表 |
| 课程状态 `status` | `published` / `draft` / `offline` | 仅后台接口返回；C 端课程接口不返回该字段。`published` 已上架、`draft` 草稿（新建默认）、`offline` 已下架 |

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
| GET | `/client/courses` | 课程广场列表（公开只读，可选 Bearer） |
| GET | `/client/courses/{course_id}` | 课程详情（公开只读，可选 Bearer） |
| POST | `/auth/wx-login` | 微信一键登录（同时授权手机号） |
| POST | `/auth/token-check` | 冷启动校验 Token（无效返回 `valid=false`，不是 401） |
| POST | `/auth/logout` | 退出登录，吊销当前业务 Token（幂等成功） |
| POST | `/admin/auth/login` | 管理员账号密码登录 |
| POST | `/payments/wechat/notify` | 微信支付异步回调（仅微信签名校验） |
| GET | `/api/wx/xpay/callback` | 微信虚拟支付消息推送首次接入校验（固定路径，不带 `/v1`，免 JWT） |
| POST | `/api/wx/xpay/callback` | 微信虚拟支付消息推送（发货 / iOS 退款问询，仅微信签名校验） |

### 4.2 C 端接口（C 端用户 JWT）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/client/user/profile` | 个人中心用户信息 |
| PUT | `/client/user/profile` | 更新个人资料（昵称） |
| POST | `/client/user/avatar` | 上传个人头像（multipart） |
| GET | `/client/courses/mine` | 我的课程 |
| GET | `/client/lessons/{lesson_id}/play-auth` | 获取 VOD 临时播放鉴权 |
| POST | `/client/study/progress` | 上报播放进度 |
| POST | `/api/vod/finish-lesson` | 播放器完成回调（固定路径，不带 `/v1`） |
| GET | `/client/orders` | 我的订单列表（仅当前用户，分页，可按状态筛选） |
| POST | `/client/orders` | 创建订单并获取支付参数（兼容接口） |
| GET | `/client/orders/{order_no}` | 订单详情（仅本人，含课程标题与封面） |
| POST | `/client/orders/{order_no}/pay` | 待支付订单重新获取支付参数 |
| POST | `/client/orders/{order_no}/cancel` | 取消待支付订单；微信侧已支付时自动发课 |
| POST | `/payments/create-order` | 创建订单并获取微信 V3 支付参数（无虚拟支付映射时使用） |
| POST | `/payments/virtual/create-order` | 虚拟支付下单，返回 `wx.requestVirtualPayment` 参数 |
| POST | `/api/wx/xpay/create_order` | 虚拟支付下单兼容接口（`product_id` + `openid`，固定路径，不带 `/v1`） |
| GET | `/payments/query-order/{order_no}` | 查询订单；`pending` 时主动向微信查单并同步 |
| POST | `/payments/close-order/{order_no}` | 关闭超过 30 分钟未支付的订单（超时关单） |

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
| PUT | `/admin/course/{course_id}/change-status` | 课程上下架（单数路径，需求约定） |
| DELETE | `/admin/courses/{course_id}` | 删除空课程 |
| POST | `/admin/vod/upload` | 上传本地视频到 VOD 媒资库（仅超级管理员） |
| GET | `/admin/vod/list` | 媒资库分页列表（名称模糊 / FileId 精确） |
| GET | `/admin/vod/remote-list` | 腾讯云 VOD 视频库与本地媒资对比 |
| POST | `/admin/vod/import` | 远程视频手动入库（仅超级管理员） |
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
| POST | `/admin/gifts` | 按手机号赠课（已注册直发 / 未注册预赠，幂等） |
| GET | `/admin/gifts/pregifts` | 手机号预赠记录（待认领 / 已认领） |
| GET | `/admin/gifts/logs` | 赠课日志 |
| GET | `/admin/orders` | 订单只读查询 |
| GET | `/admin/users/search` | 按手机号 / 昵称片段或用户 ID 模糊搜索用户 |
| GET | `/admin/users/lookup` | 按手机号或用户 ID 精确查找用户 |
| GET | `/admin/users/{user_id}/courses` | 用户已拥有课程分页查询（购买 + 赠课） |
| POST | `/admin/users/grant-course` | 赠课 / 重置有效期（同一用户 + 课程仅一条授权） |
| POST | `/admin/users/revoke-course` | 收回课程授权 |
| GET | `/admin/user-courses` | 用户课程授权与有效期只读查询 |
| GET | `/admin/user-courses/logs` | 用户课程操作日志（赠课 / 重置有效期 / 收回） |
| GET | `/admin/configs` | 系统配置列表 |
| POST | `/admin/configs/reset` | 全部配置恢复默认 |
| PUT | `/admin/configs/{config_key}` | 修改单个配置值 |
| POST | `/admin/configs/{config_key}/reset` | 单个配置恢复默认 |

后台**不提供**下单、支付、退款、修改订单状态、视频播放、修改学习进度能力；订单接口只读。
管理员分 `super`（超级管理员）与 `normal`（普通管理员）两种角色：上传视频、远程视频手动入库、同步转码状态、新建 / 编辑 / 删除课时仅 `super` 可调用，`normal` 仅可读取课程、课时、本地媒资、VOD 视频库与订单。

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
    "home_subtitle": "以系统课程，点亮每一次成长",
    "tab_home_text": "首页",
    "tab_course_text": "课程"
  }
}
```

说明：

- 配置只承载展示文案，不承载权限、价格或业务开关。
- 首页主标题与副标题分别由 `home_title`、`home_subtitle` 控制，后台「站点文案 → 首页文案」可修改。
- 缺失的配置由前端内置默认值兜底；接口异常时前端仍可渲染。
- 底部 Tab 固定两个，仅 `tab_home_text` / `tab_course_text` 两段文字可调整。

### 5.3 微信一键登录（openid + 手机号）

`POST /auth/wx-login`

- 鉴权：无
- 请求体（`camelCase`）：

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `loginCode` | string | 是 | 1–128 字符 | `Taro.login()` / `wx.login` 获取的临时 code |
| `phoneCode` | string | 是 | 0–128 字符 | `getPhoneNumber` 回调 `e.detail.code`；拒绝授权时为空，返回 `PHONE_DENIED` |

```json
{ "loginCode": "081abcDEFghiJklMnoPQRsTuvWXYz123", "phoneCode": "<getPhoneNumber-code>" }
```

- 出参：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `token` | string | C 端用户 JWT（7 天） |
| `userInfo` | object | 登录用户信息，见下 |

`userInfo` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `userId` | integer | 主账号 ID |
| `phoneMasked` | string \| null | 脱敏手机号，如 `138****8000` |
| `nickname` | string \| null | 用户主动设置的昵称 |
| `avatar` | string \| null | 头像 COS 公网地址 |
| `openid` | string \| null | 本次登录微信的 openid，仅供本机记录，不作鉴权凭证 |
| `isNewUser` | boolean | 本次是否新建主账号 |
| `isMerged` | boolean | 本次是否把新微信合并到已有手机号账号 |

```json
{
  "token": "<user-jwt>",
  "userInfo": {
    "userId": 1,
    "phoneMasked": "138****8000",
    "nickname": null,
    "avatar": null,
    "openid": "oXyz...",
    "isNewUser": false,
    "isMerged": true
  }
}
```

- 账号规则：手机号是唯一信任基准，`openid` 只存在于绑定表，不存放在用户主表。
  - 【分支A】openid 已绑定：复用原主账号；手机号变化时更新为最新手机号并记录 `login_update`。
  - 【分支B-1】openid 未绑定、手机号已存在：把新 openid 绑定到老账号，记录 `merge`，`isMerged=true`；课程、订单、预约次数全部继承。
  - 【分支B-2】两者都不存在：新建主账号并绑定 openid，记录 `create`，`isNewUser=true`。
  - 不同手机号不会合并；openid 唯一索引 + 手机号唯一索引 + Redis 锁 `lock:wxlogin:{phone}`（TTL 10s，等待 3s）保证并发安全。
- 错误：
  - `400 PHONE_DENIED`：未授权手机号（`phoneCode` 为空）
  - `400 WX_PHONE_DECRYPT_FAIL`：手机号解密 / 获取失败
  - `400 WX_LOGIN_FAIL`：`code2session` 失败
  - `409 ACCOUNT_CONFLICT`：并发登录冲突或手机号归属冲突，稍后重试
- 幂等：同一 openid 重复登录返回同一 `userId`，不会重复创建用户。

### 5.4 冷启动校验与退出登录

`POST /auth/token-check`

- 鉴权：无（`token` 放在请求体或 `Authorization: Bearer` 头，二选一）
- 请求体：`{ "token": "<user-jwt>" }`
- 出参：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `valid` | boolean | Token 是否有效 |
| `userInfo` | object \| null | 有效时返回与 5.3 相同的 `userInfo` |

- 语义：Token 过期、签名错误或已被吊销时**仍返回 HTTP 200** 且 `valid=false`，由小程序自行清理本地登录态；不抛 401。
- 用途：仅小程序冷启动调用；后台切前台（热启动）不调用本接口。

`POST /auth/logout`

- 鉴权：无（`token` 放在请求体或 `Authorization: Bearer` 头，二选一）
- 请求体：`{ "token": "<user-jwt>" }`
- 出参：`{ "success": true }`
- 行为：把当前 Token 的 SHA-256 摘要写入 Redis 吊销名单，TTL 与 Token 有效期一致。此后携带同一 Token 的请求一律返回 401；其他 Token（例如另一台设备）不受影响。
- 幂等：Token 为空、已过期、已吊销或不是 C 端 Token 时同样返回 `success=true`，避免阻塞小程序本地清理。
- 说明：只处理业务 JWT，不涉及微信 `session_key`。

### 5.5 管理员登录

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

### 5.6 微信支付异步回调

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
4. 以 `out_trade_no` 对订单加行锁；重复已支付回调直接返回成功，不重复发课。若授权已不存在（通常是后台已收回），重复回调只更新支付流水，**不会补发或复活授权**。
5. 首次成功：同一事务内订单置为 `paid`、写入 `pay_time` 与唯一 `pay_transaction_id`，并写入 / 续期课程授权，有效期为「支付完成时间 + `COURSE_VALID_DAY` 天」（默认 365 天）。
6. 微信侧已关闭或已退款的交易不会把课程授权写入用户账号。

回调相关错误码：`PAYMENT_MERCHANT_MISMATCH`、`PAYMENT_APPID_MISMATCH`、`PAYMENT_AMOUNT_MISMATCH`、`PAYMENT_PAYER_MISMATCH`、`PAYMENT_ORDER_NOT_FOUND`、`PAYMENT_ORDER_REFUNDED`、`PAYMENT_CALLBACK_INVALID`。这些错误均返回给微信侧，不会暴露给小程序用户。

### 5.7 微信小程序虚拟支付消息推送（xpay）

`GET|POST /api/wx/xpay/callback`

- 该路径**不跟随 `/api/v1` 版本前缀**，固定为 `https://<域名>/api/wx/xpay/callback`。
- 鉴权：**无 JWT / Admin Token**，只信任微信消息推送签名；后台与 C 端身份体系不参与。
- 消息格式：XML，安全模式（AES）；支持正式与沙箱两套 Token / EncodingAESKey，按签名自动命中。
- 只处理两类事件：
  - `xpay_goods_deliver_notify`：支付成功发货（主流程）；
  - `xpay_subscribe_ios_refund_query_notify`：iOS 退款问询应答。

#### 5.7.1 GET：首次接入校验

微信配置服务器地址时会发起：

```text
GET /api/wx/xpay/callback?signature=<sha1>&timestamp=<ts>&nonce=<nonce>&echostr=<echo>
```

- `signature = SHA1(sort(token, timestamp, nonce))`，任一环境配置命中即通过。
- 通过：HTTP 200，`text/plain`，**原样返回 `echostr`**，不做 AES 解密。
- 失败：HTTP 403，空响应。

#### 5.7.2 POST：安全模式消息

查询参数（微信发送）：

| 参数 | 说明 |
| --- | --- |
| `timestamp` | 时间戳 |
| `nonce` | 随机串 |
| `msg_signature` | `SHA1(sort(token, timestamp, nonce, Encrypt))` |
| `encrypt_type` | `aes`（安全模式） |

外层请求体：

```xml
<xml>
  <ToUserName><![CDATA[gh_xxx]]></ToUserName>
  <Encrypt><![CDATA[<base64 密文>]]></Encrypt>
</xml>
```

服务端规则：

1. 校验 `msg_signature`；使用 `EncodingAESKey` 做 AES-256-CBC 解密，并校验明文尾部 AppID 与本小程序 `WECHAT_APP_ID` 一致。
2. 解密后再次校验明文 `signature`（若存在）；不合法返回失败 XML，不写任何业务数据。
3. 兼容明文模式（无 `Encrypt` / `msg_signature`）：仅用 `signature` 校验。
4. POST 无论业务成功或失败均返回 **HTTP 200 + `application/xml`**；失败使用非零 `ErrCode`，微信按官方策略重试（最多 15 次）。
5. 报文上限 48 KiB（`WECHAT_XPAY_MAX_BODY_BYTES`），超限直接失败。

成功应答（必须完全一致）：

```xml
<xml><ErrCode>0</ErrCode><ErrMsg><![CDATA[success]]></ErrMsg></xml>
```

失败应答：

```xml
<xml><ErrCode>-1</ErrCode><ErrMsg><![CDATA[<原因>]]></ErrMsg></xml>
```

#### 5.7.3 发货字段与业务规则

`xpay_goods_deliver_notify` 关键字段：

| 字段 | 位置 | 说明 |
| --- | --- | --- |
| `OpenId` | 顶层 | 付款微信 openid |
| `OutTradeNo` | 顶层 | 微信业务订单号，8–32 位 `[0-9A-Za-z_-|*@]`，全局唯一 |
| `Env` | 顶层 | `0` 正式 / `1` 沙箱 |
| `WeChatPayInfo.MchOrderNo` | 嵌套，可缺失 | 商户订单号，存在时优先作为幂等键 |
| `WeChatPayInfo.TransactionId` | 嵌套，可缺失 | 微信支付流水号 |
| `WeChatPayInfo.PaidTime` | 嵌套，可缺失 | 支付时间；支持 ISO / Unix 秒 / `YYYYMMDDHHMMSS`，无时区按北京时间转 UTC |
| `GoodsInfo.ProductId` | 嵌套 | 商品 ID，对应 `vpay_products.product_id` |
| `GoodsInfo.Quantity` | 嵌套 | 必须为 `1` |
| `GoodsInfo.ActualPrice` | 嵌套 | 实付金额（分），必须等于映射表价格 |

处理顺序：

1. 验签/解密 → 解析字段 → 环境策略：生产收到 `Env=1` 记审计 `ignored` 并返回成功，不建用户/订单/授权；开发/测试要求报文 `Env` 与命中的配置环境一致。
2. 按 `(product_id, env)` 查 `vpay_products`；无映射或价格不一致直接失败（返回非零 `ErrCode`，留出修配置窗口）。
3. 幂等快路径：Redis `xpay:deliver:{env}:{mch_order_no|out_trade_no}`，命中直接成功；Redis 故障时继续，由数据库兜底。
4. 按 openid 查 `user_bind_openid`；不存在则创建**无手机号**静默用户并绑定 openid。该用户后续用同一微信手机号登录时，登录服务会复用并补手机号，订单与课程自然继承。
5. 数据库订单幂等：`orders.mch_order_no` 唯一、`orders.order_no = OutTradeNo` 唯一、`pay_transaction_id` 唯一；已 `paid` 不重复发课；已 `refunded` 不补发；`pending/closed` 置为 `paid` 并发放。
6. 发课：写 `user_course(source=buy)`，有效期 = 支付时间 + `COURSE_VALID_DAY` 天，并幂等发放课程预约次数。
7. 审计明细异步写入 `xpay_push_logs`（Redis 队列，不阻塞回调）。

#### 5.7.4 iOS 退款问询应答

`xpay_subscribe_ios_refund_query_notify` 必须 3 秒内应答。服务端按本地发货状态 + 渠道 `provide_status`（`0` 未发货 / `1` 已发货 / `2` 发货中）自动决策：

| 本地状态 | `provide_status` | `result_code` | 说明 |
| --- | --- | --- | --- |
| 订单 paid 且授权当前有效 | 任意（含 0） | 1 拦截 | 权益已真实发放 |
| 订单 paid，授权过期/缺失 | 1 / 2 | 1 拦截 | 渠道称已发货 |
| 订单 paid，授权过期/缺失 | 0 | 0 放行 | 渠道未发货 |
| 无本地订单 | 1 / 2 | 1 拦截 | 保守 |
| 无本地订单 | 0 | 0 放行 | 渠道未发货 |
| 订单已退款 | 任意 | 0 放行 | 已退过 |
| 字段异常 / 查询超时 / DB 异常 | 任意 | 1 拦截 | 保守，附错误证据 |

安全模式回复同样加密，外层为：

```xml
<xml>
  <Encrypt><![CDATA[<base64 密文>]]></Encrypt>
  <MsgSignature><![CDATA[<sha1>]]></MsgSignature>
  <TimeStamp>1700000000</TimeStamp>
  <Nonce><![CDATA[<nonce>]]></Nonce>
</xml>
```

加密前的内层明文：

```xml
<xml>
  <ErrCode>0</ErrCode>
  <ErrMsg><![CDATA[success]]></ErrMsg>
  <IosRefundQueryResponse>
    <result_code>0|1</result_code>
    <result_info><![CDATA[<简短结论>]]></result_info>
    <evidence><![CDATA[<订单状态、授权有效期、provide_status 等证据>]]></evidence>
  </IosRefundQueryResponse>
</xml>
```

明文模式直接返回上述内层 XML。证据中不含 openid、手机号等与退款无关的个人信息。

#### 5.7.5 商品映射维护（上线初期用 SQL）

管理后台暂不提供映射维护页面。上线前在正式库执行：

```sql
INSERT INTO vpay_products (product_id, env, course_id, price, enabled, remark)
VALUES ('<微信后台商品ID>', 0, <课程ID>, <价格，单位分>, 1, '正式商品');
```

- `env=0` 正式环境，`env=1` 沙箱；`(product_id, env)` 唯一。
- `price` 必须与微信后台商品实付价**完全一致**，否则回调拒绝发货。
- 课程已存在虚拟支付映射时，后台删除课程会被 `409 COURSE_IN_USE` 阻止。

#### 5.7.6 回调审计错误码（仅落库/日志，不返回 JSON）

| code | 说明 |
| --- | --- |
| `XPAY_NOT_CONFIGURED` / `XPAY_CONFIG_INVALID` | 未配置推送凭据或配置不完整 |
| `XPAY_BODY_TOO_LARGE` | 报文超过 `WECHAT_XPAY_MAX_BODY_BYTES` |
| `XPAY_XML_INVALID` | XML 为空、格式错误或含 DTD/实体 |
| `XPAY_SIGNATURE_INVALID` | GET / 明文 POST 签名不匹配，或安全模式 `msg_signature` 不匹配 |
| `XPAY_ENCRYPT_MISSING` | 安全模式报文缺少 `Encrypt` |
| `XPAY_DECRYPT_FAILED` | AES 解密失败、密文非法或填充错误 |
| `XPAY_APPID_MISMATCH` | 解密后 AppID 与本小程序不一致 |
| `XPAY_FIELD_MISSING` / `XPAY_FIELD_INVALID` | 必填字段缺失或格式非法 |
| `XPAY_ENV_INVALID` / `XPAY_ENV_MISMATCH` | `Env` 非法或与配置/运行环境不一致 |
| `XPAY_PRICE_INVALID` / `XPAY_QUANTITY_INVALID` | 金额或数量不合法 |
| `XPAY_PRODUCT_NOT_MAPPED` | `(product_id, env)` 无课程映射 |
| `XPAY_PRICE_MISMATCH` | `ActualPrice` 与映射价格不一致 |
| `XPAY_ORDER_MISMATCH` | 既有订单的用户/课程/金额/渠道等与本次推送不一致 |
| `XPAY_CONFLICT` / `XPAY_USER_CONFLICT` | 并发写库冲突 |
| `XPAY_INTERNAL_ERROR` | 未预期异常（返回通用失败文案，不泄露内部信息） |

---

## 6. C 端接口

以下接口除特别说明外，均要求 `Authorization: Bearer <user access_token>`。

### 6.1 获取个人中心信息

`GET /client/user/profile`

- 鉴权：C 端用户 JWT
- 入参：无
- 出参：`user` 对象（`id` / `mobile` / `nickname` / `avatar_url` / `created_at` / `updated_at`）；`mobile` 为已授权手机号，前端展示时自行脱敏。
- 错误：`404 USER_NOT_FOUND`（Token 对应用户已被删除）

### 6.2 课程广场列表

`GET /client/courses`

- 鉴权：公开只读，可匿名访问；可选 Bearer（有效 C 端 JWT）。带无效 Token 返回 401，Admin Token 返回 403 `USER_PERMISSION_DENIED`。
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
- 只返回 `status=published`（已上架）的课程；草稿与已下架课程不出现在课程广场、热门板块与搜索结果中。

### 6.3 我的课程

`GET /client/courses/mine`

- 鉴权：C 端用户 JWT
- Query 参数：`page`（默认 1）、`page_size`（默认 20，1–100）
- 出参：`PageResponse<CourseListItem>`，字段同 6.2。
- 说明：仅返回当前用户已购买或已获赠的课程；按授权时间倒序。课程上下架状态不影响本接口，已下架课程仍在【我的课程】中可见可学。

### 6.4 课程详情

`GET /client/courses/{course_id}`

- 鉴权：公开只读，可匿名访问；可选 Bearer（有效 C 端 JWT）。带无效 Token 返回 401，Admin Token 返回 403 `USER_PERMISSION_DENIED`。
- 匿名请求：`is_owned=false`，`lessons[].is_finished` 恒为 `false`；带有效用户 Token 时按 `user_id` 计算归属与完成状态。
- 可见性：草稿 / 已下架课程仅对已拥有该课程的用户可见；匿名或未购用户访问返回 `404 COURSE_NOT_FOUND`。
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

### 6.5 获取播放鉴权

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

### 6.6 上报播放进度

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

### 6.7 标记课时已看完（播放器完成回调）

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

### 6.8 创建订单并获取支付参数（微信支付 V3 JSAPI）

`POST /payments/create-order`

> **合规说明**：小程序内课程属于虚拟商品，购买与支付必须走官方「小程序虚拟支付」。
> 小程序端已不再调用本接口，所有购买入口只使用 `POST /payments/virtual/create-order` +
> `wx.requestVirtualPayment`；本接口仅为历史兼容保留，不得新增前端调用。

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
  - `409 COURSE_NOT_AVAILABLE`：课程为草稿或已下架，暂不可购买
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
  - `payment` 字段原设计用于 `Taro.requestPayment`；小程序端已按虚拟支付合规要求下线该调用，禁止新增使用。
  - 最终支付状态以微信异步回调为准；用户取消支付时订单保持 `pending`，可重新下单或在超时后关单。
  - 兼容接口 `POST /client/orders` 入参与出参相同，仅请求体不接收 `user_id` / `openid`。

### 6.8.1 我的订单（订单中心）

`GET /client/orders?page=1&page_size=20&status=pending`

- 鉴权：C 端用户 JWT（管理员 Token 会被拒绝）
- 只返回当前 JWT 用户的订单，按 `created_at` 倒序；对外状态为 `pending / paid / closed`。
- 可选筛选：`status=pending|paid|closed`；不传返回全部。传 `refunded` 返回 `422 VALIDATION_ERROR`；历史退款订单在任何筛选下都不会返回。
- 分页参数：`page` ≥ 1，`page_size` 1–100，默认 20。
- 请求头：`Authorization: Bearer <C端JWT>`
- 出参：`PageResponse<ClientOrderResponse>`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `items[].order_no` | string | 商户订单号 |
| `items[].course_id` | integer | 课程 ID |
| `items[].course_title` | string \| null | 课程标题，供订单中心展示 |
| `items[].course_cover` | string \| null | 课程封面地址，供订单卡片展示 |
| `items[].amount` | integer | 订单金额，单位分 |
| `items[].status` | string | `pending`（待支付）/ `paid`（已支付）/ `closed`（已取消） |
| `items[].source` | string | `wechat_pay`（微信支付 V3）/ `wx_vpay`（小程序虚拟支付）；`wx_vpay` 待支付订单不可「去支付」或「取消」，需返回课程页重新发起 |
| `items[].paid_at` | string \| null | 支付成功时间；未支付为 `null` |
| `items[].created_at` | string | 下单时间 |
| `total` / `page` / `page_size` | integer | 分页信息 |

- 不返回 openid、支付流水号、课程有效期等敏感字段。
- 微信订单中心 path 固定填写：`pages/orders/index`（主路径，不拼参数）。

### 6.8.2 订单详情

`GET /client/orders/{order_no}`

- 鉴权：C 端用户 JWT；只能查询自己的订单。
- 出参：`ClientOrderResponse`，字段与 6.8.1 列表项一致（含 `course_title` / `course_cover`）。
- 错误：订单不存在或不属于当前用户统一返回 `404 ORDER_NOT_FOUND`，不区分两种情况。
- 说明：详情接口只读本地状态，不主动向微信查单；需要主动同步时使用
  `GET /payments/query-order/{order_no}`。

### 6.8.3 待支付订单继续支付

`POST /client/orders/{order_no}/pay`

- 鉴权：C 端用户 JWT；只能操作自己的订单。
- 复用原订单号与下单时固化的金额，**不创建新订单**，返回与创建订单相同的 `payment` 支付参数。
- 仅 `pending` 订单可支付；已支付或已取消返回 `409 ORDER_NOT_PAYABLE`。
- 当前用户已拥有该课程时返回 `409 COURSE_ALREADY_OWNED`，避免重复扣款。
- 其他用户的订单返回 `404 ORDER_NOT_FOUND`。
- 说明：支付结果仍以微信异步回调为准；小程序在拉起支付前会先调用
  `GET /payments/query-order/{order_no}` 主动同步一次状态。

### 6.8.4 取消待支付订单

`POST /client/orders/{order_no}/cancel`

- 鉴权：C 端用户 JWT；只能取消自己的订单。
- 仅 `pending` 订单可取消；`paid` / `closed` 返回 `409 ORDER_NOT_PENDING`。
- 出参：取消后的 `ClientOrderResponse`（`status` 为 `closed`；若微信侧已支付则为 `paid`）。
- 处理顺序（始终以微信侧状态为准）：
  1. 先向微信查单；`trade_state=SUCCESS` 时**放弃取消**，按支付成功走正常发课流程（课程授权、有效期、预约次数），返回 `paid`；
  2. 微信返回 `CLOSED` / `REVOKED` / `PAYERROR` / `ORDER_NOT_EXIST` 时，同步本地为 `closed`；
  3. 微信返回 `NOTPAY` / `USERPAYING` 时调用微信 V3 关单接口，关单成功后本地置 `closed` 并写操作日志；
  4. 关单异常时重新查单，以微信最新状态为准；仍无法确认则本地状态保持不变并返回 `502`，不做臆测性修改。
- 取消成功只关闭订单，**不发放课程权益、不触发预赠认领、不产生退款**。
- 错误：
  - `404 ORDER_NOT_FOUND`
  - `409 ORDER_NOT_PENDING`：非待支付订单
  - `409 ORDER_STATE_UNSUPPORTED`：微信交易状态不支持取消
  - `502 PAYMENT_QUERY_FAILED` / `PAYMENT_CLOSE_FAILED`：查单或关单失败
- 并发：取消、支付回调、超时关单、对账共用 `lock:order:{order_no}` 分布式锁与订单行锁；重复取消不会重复写日志或重复发课。
- 操作日志：每次取消尝试都写入 `order_operation_logs`，包含订单号、操作类型（`manual_cancel`）、微信交易状态、操作时间与微信原始响应；查单/关单失败额外记录错误信息。

### 6.8.5 虚拟支付下单（小程序道具直购）

`POST /payments/virtual/create-order`

- 鉴权：C 端用户 JWT（管理员 Token 会被拒绝）
- 请求体：

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `product_id` | string | 是 | 1–64 字符 | 课程详情返回的 `vpay_product_id`，仅作课程提示 |
| `platform` | string | 否 | `ios` / `android`，默认 `android` | 仅决定购买环境，不是安全边界：iOS 恒为正式环境；安卓只在非生产后端使用沙箱 |
| `login_code` | string | 是 | 1–256 字符 | 下单当下新取的 `wx.login` code，服务端换取 `session_key` 后立即丢弃 |

```json
{
  "product_id": "100001",
  "platform": "android",
  "login_code": "<wx.login code>"
}
```

- 出参：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `order_no` | string | 本地订单号，`HH` 开头 |
| `out_trade_no` | string | 微信 `OutTradeNo`，与 `order_no` 相同；8–32 位、一次性 |
| `course_id` | integer | 服务端按商品映射解析出的课程 ID |
| `amount` | integer | 金额（分），固定取 `vpay_products.price`，且必须等于课程价 |
| `status` | string | 新订单固定 `pending` |
| `sign_data` | string | 紧凑 JSON 字符串，必须原样传给微信，不得重新序列化 |
| `pay_sig` | string | AppKey 对 `requestVirtualPayment&sign_data` 的 HMAC-SHA256 |
| `signature` | string | `session_key` 对 `sign_data` 的 HMAC-SHA256 |
| `mode` | string | 固定 `short_series_goods` |
| `env` | integer | `0` 正式环境，`1` 沙箱环境 |

```json
{
  "order_no": "HH202611241030001234567890abcdef12",
  "out_trade_no": "HH202611241030001234567890abcdef12",
  "course_id": 1,
  "amount": 19900,
  "status": "pending",
  "sign_data": "{\"offerId\":\"1450000000\",\"buyQuantity\":1,\"env\":1,\"currencyType\":\"CNY\",\"productId\":\"100001\",\"goodsPrice\":19900,\"outTradeNo\":\"HH...\",\"attach\":\"1\"}",
  "pay_sig": "<pay-sig>",
  "signature": "<signature>",
  "mode": "short_series_goods",
  "env": 1
}
```

- 客户端调起：

```js
wx.requestVirtualPayment({
  signData: res.sign_data,   // 原样透传
  mode: res.mode,
  paySig: res.pay_sig,
  signature: res.signature,
  success: () => { /* 跳转支付成功页轮询，不在此发权限 */ },
  fail: (err) => { /* -2 取消；其余按错误码提示 */ }
})
```

- 服务端校验顺序：
  1. 商品映射存在且启用（`vpay_products`）；
  2. 课程在当前 `env` 下存在可用映射；
  3. `vpay_products.price > 0` 且等于 `courses.price`；
  4. 课程已上架（`409 COURSE_NOT_AVAILABLE`）；
  5. 用户当前未拥有课程（`409 COURSE_ALREADY_OWNED` / `409 COURSE_ACCESS_NOT_STARTED`）；
  6. `code2session` 得到的 openid 必须绑定在当前 JWT 用户下（`403 PAYMENT_OPENID_MISMATCH`）。
- 安全约束：
  - 金额只取 `vpay_products.price`，请求体不能指定金额、课程或订单状态；
  - AppKey 与 `session_key` 绝不返回前端、不落库、不写日志；响应只有签名结果；
  - 客户端支付成功回调**不发放任何课程权限**，发货只认 `/api/wx/xpay/callback` 推送。
- 订单生命周期：
  - 下单即写入 `source=wx_vpay` 的 `pending` 订单，`mch_order_no` 为空，由推送补齐；
  - 每次支付使用新的 `out_trade_no`；取消 / 失败后重试会生成新订单，旧订单由超时关单任务**仅本地**置为 `closed`，晚到推送仍按 `closed → paid` 发课；
  - 下单接口有 Redis 连点锁（`lock:vpay:create:{user_id}:{course_id}`，5 秒 TTL，请求结束即释放），并发重复请求返回 `409 ORDER_CREATE_TOO_FREQUENT`。
- 错误：

| HTTP | code | 说明 |
| --- | --- | --- |
| 404 | `VPAY_PRODUCT_NOT_FOUND` | 商品不存在或已下架 |
| 409 | `VPAY_PRODUCT_DISABLED` | 商品映射已停用 |
| 409 | `VPAY_PRODUCT_ENV_MISMATCH` | 该课程未配置当前购买环境的商品 |
| 409 | `VPAY_PRICE_MISMATCH` | 商品价与课程价不一致或 ≤ 0（配置错误） |
| 409 | `ORDER_CREATE_TOO_FREQUENT` | 下单请求处理中（连点保护） |
| 503 | `PAYMENT_UNAVAILABLE` | `WECHAT_XPAY_OFFER_ID` 或对应环境 AppKey 未配置 |
| 403 | `PAYMENT_OPENID_MISMATCH` | code2session openid 与 JWT 用户不一致 |

- 配置要求：`WECHAT_XPAY_OFFER_ID` 与 `WECHAT_XPAY_{PROD|SANDBOX}_APP_KEY` 必须成对可用；缺失时只记日志，不向前端回显缺失项。iOS 无沙箱，正式扣款前必须在微信后台开通虚拟支付并发布道具（`productId` + 价格分）。

### 6.8.6 虚拟支付下单兼容接口（product_id + openid）

`POST /api/wx/xpay/create_order`（固定路径，不带 `/v1`）

与 6.8.5 共用同一套商品校验、建单与签名逻辑，区别只在入参：以
`openid` 声明付款人，`login_code` 可选。

- 鉴权：C 端用户 JWT（管理员 Token 会被拒绝）。`openid` 属于客户端
  声明，**不是鉴权凭证**：必须与当前 JWT 用户绑定的微信 openid 一致，
  否则 `403 PAYMENT_OPENID_MISMATCH`，服务端不会据此创建订单。
- 请求体：

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `product_id` | string | 是 | 1–64 字符 | 课程详情返回的 `vpay_product_id`，仅作课程提示 |
| `openid` | string | 是 | 1–128 字符 | 付款人 openid，必须与 JWT 用户绑定一致 |
| `platform` | string | 否 | `ios` / `android`，默认 `android` | 仅决定购买环境 |
| `login_code` | string | 否 | 1–256 字符 | 传入时服务端换取 `session_key` 并返回 `signature` |

```json
{
  "product_id": "100001",
  "openid": "<当前用户 openid>"
}
```

- 出参：与 6.8.5 相同（`order_no` / `out_trade_no` / `course_id` /
  `amount` / `status` / `sign_data` / `pay_sig` / `signature` / `mode` /
  `env`）。
  - **未传 `login_code` 时 `signature` 为 `null`**：微信要求
    `wx.requestVirtualPayment` 必须携带用户态签名，此时返回的参数不足以
    拉起支付，仅适用于服务端预下单/对账场景；前端真实支付请传
    `login_code` 或使用 6.8.5。
- 错误：与 6.8.5 一致；额外注意 `403 PAYMENT_OPENID_MISMATCH` 也会在
  `openid` 与 JWT 用户不一致时直接返回（早于商品校验）。

### 6.9 查询订单状态（微信支付 V3 JSAPI）

`GET /payments/query-order/{order_no}`

- 鉴权：C 端用户 JWT
- Path 参数：`order_no`，1–64 字符
- 出参：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `order_no` | string | 商户订单号 |
| `course_id` | integer | 课程 ID |
| `course_title` | string \| null | 课程标题（仅展示，不含有效期） |
| `appointment_quota` | integer | 课程当前配置的赠送预约次数 |
| `amount` | integer | 金额，单位分 |
| `status` | string | `pending` / `paid` / `closed`（`closed` 对外展示为已取消） |
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
  - 已支付或已取消订单直接返回本地状态，不重复发课。
  - 虚拟支付（`wx_vpay`）订单**不调用微信支付 V3 查单**，只返回本地状态；支付结果由 `/api/wx/xpay/callback` 推送发货，支付成功页轮询本接口确认即可。
  - 虚拟支付 pending 订单超过关单时长后会被任务本地置为 `closed`；若用户实际已付款，晚到推送仍会按 `closed → paid` 发课，前端超时提示应引导稍后查看「我的课程」。
  - 不提供退款接口；取消待支付订单见 6.8.4，查询他人订单始终返回 404。
  - 订单详情 `GET /client/orders/{order_no}`（6.8.2）只读本地状态，不会主动向微信查单。

### 6.10 关闭未支付订单（微信支付 V3 JSAPI）

`POST /payments/close-order/{order_no}`

- 鉴权：C 端用户 JWT
- Path 参数：`order_no`，1–64 字符
- 出参：同 6.9 的订单对象。
- 错误：
  - `404 ORDER_NOT_FOUND`
  - `409 PAYMENT_CLOSE_TOO_EARLY`：下单未满 30 分钟，暂不允许关闭
  - `502 PAYMENT_CLOSE_FAILED`：微信关单失败
- 说明：
  - 仅允许关闭下单超过 `ORDER_CLOSE_TIMEOUT_MINUTES`（默认 30）分钟且仍为 `pending` 的订单；未满时长返回 `409 PAYMENT_CLOSE_TOO_EARLY`。
  - 微信返回订单已支付时，会先查单同步为 `paid` 并发课，不会误关闭已付款订单。
  - 已支付、已取消订单直接返回当前状态，不重复处理。
  - 后端定时任务同样调用该关单逻辑：默认每 `ORDER_CLOSE_SCAN_INTERVAL_SECONDS`（300 秒）扫描一次，批量关闭超时 `pending` 订单并写 `timeout_close` 操作日志；重复执行幂等，不会重复关单或重复发课。
  - 每日对账任务默认每 `ORDER_RECONCILE_INTERVAL_SECONDS`（86400 秒）执行，回看 `ORDER_RECONCILE_LOOKBACK_DAYS`（默认 7）天内的 `pending` / `paid` 订单，向微信同步真实状态：微信已支付而本地未支付则补发课，微信已关闭而本地待支付则同步取消，并写入对账日志；不会回收已发放的课程权益。
  - 系统不提供退款接口，也不会因取消或关单产生任何退款动作。

### 6.11 更新个人资料（昵称）

`PUT /client/user/profile`

- 鉴权：C 端用户 JWT
- 请求体：

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `nickname` | string | 是 | 1–32 字符，去首尾空白后不能为空 | 用户主动设置或修改的昵称 |

```json
{ "nickname": "禾下学员" }
```

- 出参：`user` 对象，字段见 6.1。
- 错误：
  - `401 UNAUTHORIZED`：未携带或 Token 无效
  - `403 USER_PERMISSION_DENIED`：使用 Admin Token 调用
  - `404 USER_NOT_FOUND`：Token 对应用户已被删除
  - `422 VALIDATION_ERROR`：昵称空白、超长、包含换行/控制字符，或携带 `avatar_url` 等未声明字段
- 说明：
  - 微信已不支持静默获取昵称，昵称只能由用户在小程序内主动设置（小程序使用 `Input type="nickname"` 触发微信键盘快捷填入）。
  - `avatar_url` 不能通过本接口写入，只能由 6.12 头像上传接口产生。

### 6.12 上传个人头像

`POST /client/user/avatar`

- 鉴权：C 端用户 JWT
- 请求格式：`multipart/form-data`

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `file` | file | 是 | ≤ 5MB；JPG / PNG / WebP | 头像图片，服务端按魔术字节校验真实格式 |

- 出参：`user` 对象（含最新 `avatar_url`），字段见 6.1。
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

- Query：`page`、`page_size`、`keyword`（课程标题模糊搜索）、`is_hot_topic`、`status`（`draft` / `published` / `offline`；不传返回全部状态）
- 出参：`PageResponse<AdminCourseResponse>`
- `AdminCourseResponse`（= `CourseResponse` + `status`）：

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
| `status` | string | 上下架状态：`published` 已上架 / `draft` 草稿 / `offline` 已下架 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

- 排序：创建时间倒序。
- 说明：后台列表默认返回全部状态，供课程下拉（赠课、课时）等场景复用；无效 `status` 返回 `422 VALIDATION_ERROR`。

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

- 出参：`AdminCourseResponse`，HTTP 200。
- 说明：新建课程默认 `status=draft`（草稿），小程序不可见，需通过上下架接口上架后才会对外展示；课程创建后才能添加课时；课时没有价格，不可单独售卖。

### 7.6 后台课程详情

`GET /admin/courses/{course_id}`

- Path：`course_id` 正整数
- 出参：`AdminCourseResponse`
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

- 出参：更新后的 `AdminCourseResponse`
- 错误：`404 COURSE_NOT_FOUND`、`400 INVALID_UPDATE_FIELD`（空对象或字段为 null）
- 说明：更新价格只影响后续新订单，不修改历史订单金额；本接口不能修改 `status`，上下架只能走 7.8.1。

### 7.8 删除课程

`DELETE /admin/courses/{course_id}`

- 出参：`{ "message": "课程已删除" }`
- 错误：
  - `404 COURSE_NOT_FOUND`
  - `409 COURSE_IN_USE`：课程下存在课时、订单、课程授权或赠课记录
- 说明：只允许删除完全空的课程，避免破坏交易记录与学习历史。

### 7.8.1 课程上下架

`PUT /admin/course/{course_id}/change-status`

- 鉴权：Admin JWT（`super` / `normal` 均可）；C 端 Token 返回 `403 ADMIN_PERMISSION_DENIED`
- Path：`course_id` 正整数
- 请求体：

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `status` | string | 是 | `draft` / `published` / `offline` | 目标状态 |

```json
{ "status": "published" }
```

- 出参：更新后的 `AdminCourseResponse`，HTTP 200。
- 错误：
  - `404 COURSE_NOT_FOUND`：课程不存在
  - `422 VALIDATION_ERROR`：`status` 缺失或不是合法枚举
- 说明：
  - 状态流转：`draft` → `published`（上架）→ `offline`（下架）→ `published`（重新上架）。
  - 目标状态与当前一致时幂等成功，不写日志。
  - 每次真实状态变更写入 `course_status_logs`（管理员、课程、原状态、新状态、创建时间），与状态更新同事务。
  - 上架后小程序课程广场 / 热门 / 搜索可见并可购买；下架后公开列表隐藏、下单返回 `409 COURSE_NOT_AVAILABLE`，已购用户在【我的课程】仍可观看学习。
  - 后台列表只通过本接口改变状态；`PUT /admin/courses/{course_id}` 不接受 `status` 字段。

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
| `user_id` | integer \| null | 实际到账用户 ID；预赠待认领时为 null |
| `gifted` | boolean | 本次是否真实新增授权或预赠记录 |
| `gift_log_id` | integer \| null | 常规赠课日志 ID；预赠待认领时为 null |
| `pregift_id` | integer \| null | 手机号预赠记录 ID；直发时为 null |
| `mode` | string | `direct`（已注册直发）/ `pre_gift`（手机号预赠） |
| `status` | string | `delivered` / `pending` / `claimed` / `duplicate` |
| `message` | string | 结果说明 |

已注册手机号直发（HTTP 200）：

```json
{
  "mobile": "13800138000",
  "course_id": 1,
  "user_id": 7,
  "gifted": true,
  "gift_log_id": 12,
  "pregift_id": null,
  "mode": "direct",
  "status": "delivered",
  "message": "赠课成功"
}
```

未注册手机号预赠（HTTP 200，不创建任何课程授权）：

```json
{
  "mobile": "13700137000",
  "course_id": 1,
  "user_id": null,
  "gifted": true,
  "gift_log_id": null,
  "pregift_id": 3,
  "mode": "pre_gift",
  "status": "pending",
  "message": "手机号预赠成功，用户首次授权该手机号登录后自动到账"
}
```

重复请求（HTTP 200，幂等）：

```json
{
  "mobile": "13800138000",
  "course_id": 1,
  "user_id": 7,
  "gifted": false,
  "gift_log_id": null,
  "pregift_id": null,
  "mode": "direct",
  "status": "duplicate",
  "message": "该用户已拥有该课程，无需重复赠课"
}
```

- 错误：
  - `404 COURSE_NOT_FOUND`
  - `409 MOBILE_AMBIGUOUS`：同一手机号对应多个用户，拒绝任意选择
  - `409 GIFT_CONFLICT`：并发写入冲突
- 硬性规则：
  - **赠课入口只有手机号，不支持按 openid 赠送。**
  - 手机号命中唯一已注册用户：直接写入 `user_courses`，按 `user_id + course_id` 去重。
  - 手机号未注册：写入 `course_pregifts`，按 `phone + course_id` 去重；此时不绑定 `user_id`、不归属任何账号。
  - 预赠在用户首次用该手机号微信授权登录时自动认领：绑定当前 `user_id`、写入 `user_courses`、按预赠快照发放预约次数，并写赠课日志与认领日志；一个手机号的多条待认领预赠会一次性全部到账。
  - 预赠一旦认领即永久归属该用户，不会再次匹配其他账号；后续登录不重复认领。
  - 认领与账号合并共用手机号信任基准，同手机号的多微信最终只对应一个 `user_id`。
  - 同一手机号 + 课程不可重复发放；重复请求不新增授权、不新增日志。
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
| `user_id` | integer \| null | 实际到账用户；历史日志可能为空 |
| `pregift_id` | integer \| null | 由手机号预赠认领生成时的来源预赠 ID |
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
      "user_id": 7,
      "pregift_id": null,
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
- 说明：直发在赠课时写日志；预赠在用户首次登录认领时写日志（`user_id`、`pregift_id` 均有值）。
- 用户课程管理中的「赠课 / 重置有效期」在**首次新增授权**时也写一条赠课日志（`user_id` 必填）；重置有效期与收回只写 `user_course_logs`，不重复记赠课日志。
- 迁移 `0013_quota_reclaim_gift_backfill` 会按手机号回填历史 `gift_logs.user_id`：仅当该手机号在 `users` 中唯一对应一个账号时才回填，无法唯一确定或已回填的记录保持不变。

### 7.16 手机号预赠记录

`GET /admin/gifts/pregifts`

- Query 参数：

| 参数 | 类型 | 必填 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `page` | integer | 否 | 1 | ≥1 | 页码 |
| `page_size` | integer | 否 | 20 | 1–100 | 每页数量 |
| `mobile` | string | 否 | - | 11 位手机号 | 精确匹配 |
| `course_id` | integer | 否 | - | >0 | 课程筛选 |
| `admin_id` | integer | 否 | - | >0 | 赠送管理员筛选 |
| `status` | string | 否 | - | `pending` / `claimed` | 待认领 / 已认领 |

- 出参：`PageResponse<AdminPregiftItem>`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 预赠记录 ID |
| `mobile` | string | 预赠手机号 |
| `course_id` | integer | 课程 ID |
| `course_title` | string \| null | 课程标题展示字段 |
| `admin_id` | integer | 赠送管理员 ID |
| `admin_username` | string \| null | 管理员账号展示字段 |
| `valid_start_at` | datetime \| null | 有效期开始；永久有效为 null |
| `valid_end_at` | datetime \| null | 有效期结束；永久有效为 null |
| `appointment_quota_count` | integer | 认领时随课程发放的预约次数快照 |
| `claimed_user_id` | integer \| null | 认领后的用户 ID；待认领为 null |
| `claimed_at` | datetime \| null | 认领时间 |
| `claim_ip` | string \| null | 认领来源 IP |
| `status` | string | `pending` / `claimed` |
| `created_at` | datetime | 预赠创建时间 |

```json
{
  "items": [
    {
      "id": 3,
      "mobile": "13700137000",
      "course_id": 1,
      "course_title": "禾下美学院第一课",
      "admin_id": 1,
      "admin_username": "admin",
      "valid_start_at": null,
      "valid_end_at": null,
      "appointment_quota_count": 2,
      "claimed_user_id": null,
      "claimed_at": null,
      "claim_ip": null,
      "status": "pending",
      "created_at": "2026-11-11T10:00:00"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

- 排序：创建时间倒序。

### 7.17 后台订单查询（只读）

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

### 7.26.1 腾讯云 VOD 视频库（对比）

`GET /admin/vod/remote-list`

- 权限：所有管理员（普通管理员只读）
- 数据来源：腾讯云 `SearchMedia`（`Categories=["Video"]`、`Offset` / `Limit` 分页、`CreateTime` 倒序），按 `FileId` 与本地 `vod_media` 对比。
- Query 参数：

| 参数 | 类型 | 必填 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `page` | integer | 否 | 1 | ≥1 | 页码（内存分页） |
| `page_size` | integer | 否 | 20 | 1–100 | 每页条数 |
| `keyword` | string | 否 | - | ≤100 字符 | 按视频名称或 FileId 模糊搜索 |
| `imported` | string | 否 | `all` | `all` / `imported` / `not_imported` | 按本地入库状态筛选 |

- 出参：`PageResponse<RemoteVodItem>`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `file_id` | string | 腾讯云 VOD FileId，对比键 |
| `video_name` | string | VOD 视频名称（控制字符已清理，空名称显示「未命名视频」） |
| `duration_seconds` | integer | VOD 返回的时长；未返回时为 0 |
| `cover_url` | string \| null | VOD 自动截取的首帧封面 |
| `remote_created_at` | string \| null | VOD 创建时间（ISO8601 UTC） |
| `imported` | object \| null | 已入库时返回 `{ media_id, video_name, status, fail_reason }`；未入库为 `null` |

- 排序：VOD 创建时间倒序。
- 说明：
  - `SearchMedia` 的 `TotalCount` / `Offset` 上限为 5000，超出部分无法翻页获取；
  - 只读对比，不会因为 VOD 中已删除而自动清理本地 `vod_media` 记录；
  - 不返回 VOD 播放地址，后台不加载、不播放视频。
- 错误：`502 VOD_LIST_FAILED`（VOD 调用失败，响应只含通用提示）、`401 UNAUTHORIZED`、`422`。

### 7.26.2 远程视频手动入库

`POST /admin/vod/import`

- 权限：仅超级管理员（`normal` 返回 `403 ADMIN_SUPER_REQUIRED`）
- 请求体：

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `file_id` | string | 是 | 1–128 字符 | 必须存在于当前 VOD 应用 |
| `video_name` | string | 否 | 1–200 字符，不能含控制字符 | 本地展示名称；不传或为空时使用 VOD 名称 |

```json
{
  "file_id": "<tencent-vod-file-id>",
  "video_name": "第 1 讲 · 认识禾下"
}
```

- 处理规则：
  - 以 `file_id` 幂等：本地已存在时直接返回原记录，不重复入库、不覆盖本地名称；
  - 入库前调用 `DescribeMediaInfos` 校验远程仍存在，不存在时返回 404 且**不写入任何记录**；
  - 状态按 VOD 转码结果写入 `0` / `1` / `2`，时长、封面取自 VOD，`uploader_id` 记录本次操作管理员；
  - 并发导入同一 FileId 由唯一约束兜底，冲突后返回已存在记录。
- 出参：`VodMediaResponse`，HTTP 200。
- 错误：
  - `404 VOD_REMOTE_NOT_FOUND`：VOD 中不存在或已删除
  - `502 VOD_IMPORT_FAILED`：VOD 查询失败（不透传 VOD 错误码与密钥）
  - `500 VOD_MEDIA_SAVE_FAILED`：本地入库失败
  - `403 ADMIN_SUPER_REQUIRED`

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

用户课程管理页使用以下 6 个接口，全部要求 Admin JWT（`super` / `normal` 均可）。
管理员操作免费，不产生订单或支付；一个用户 + 一门课程始终只有一条 `user_courses` 记录。

#### 7.28.1 模糊搜索用户

`GET /admin/users/search`

- Query 参数：

| 参数 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `keyword` | string | 是 | 1–64 字符 | 手机号片段、昵称片段或用户 ID |
| `page` | integer | 否 | 默认 1，≥1 | 页码 |
| `page_size` | integer | 否 | 默认 20，1–100 | 每页数量 |

- 匹配规则：
  - 手机号、昵称均使用包含匹配（`%keyword%`）；输入中的 `%`、`_`、`\` 会被转义；
  - 纯数字关键词同时匹配用户 ID；
  - 精确手机号 / 昵称、前缀命中优先，其余按用户 ID 倒序。
- 出参：`PageResponse<AdminUserListItem>`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `user_id` | integer | 用户 ID |
| `nickname` | string \| null | 用户昵称 |
| `mobile` | string \| null | 微信授权手机号（历史数据可能为空） |
| `avatar_url` | string \| null | 头像地址 |
| `owned_course_count` | integer | 已拥有课程数（购买 + 赠课） |

- 无匹配时返回 `total=0` 与空 `items`，不返回 404。

#### 7.28.2 精确查找用户

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
| `mobile` | string \| null | 微信授权手机号（历史数据可能为空） |
| `avatar_url` | string \| null | 头像地址 |

- 错误：`400 INVALID_USER_KEYWORD`、`404 USER_NOT_FOUND`、`409 MOBILE_AMBIGUOUS`（手机号对应多个用户，请改用用户 ID）。

#### 7.28.3 用户已拥有课程

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

#### 7.28.4 赠课 / 重置有效期

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
- 留痕：每次操作写入 `user_course_logs`，包含管理员 ID、用户 ID、课程 ID、操作类型、有效期与操作时间；首次新增授权时同时写一条 `gift_logs`（手机号取目标用户当前手机号，可能为空），重置有效期不重复写赠课日志。
- 错误：`404 USER_NOT_FOUND`、`404 COURSE_NOT_FOUND`、`409 GIFT_CONFLICT`。

#### 7.28.5 收回课程授权

`POST /admin/users/revoke-course`

```json
{
  "user_id": 12,
  "course_id": 3
}
```

- 语义：删除匹配的 `user_courses` 行并写入 `action=revoke` 的操作日志；日志中的 `expire_time` 记录被收回的原有效期。
- 收回立即生效：C 端播放鉴权、我的课程均以 `user_courses` 为准；用户端返回「我的课程」时会重新拉取。
- 收回后同一订单的微信重复支付回调**不会**补发授权，因此课程不会再次出现。
- 出参：`user_id`、`course_id`、`revoked=true`、`log_id`、`message`。
- 错误：`404 USER_NOT_FOUND`、`404 COURSE_NOT_FOUND`、`404 USER_COURSE_NOT_FOUND`。

#### 7.28.6 用户课程操作日志

`GET /admin/user-courses/logs`

- 鉴权：Admin JWT
- Query 参数：

| 参数 | 类型 | 必填 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `page` | integer | 否 | 1 | ≥1 | 页码 |
| `page_size` | integer | 否 | 20 | 1–100 | 每页数量 |
| `user_id` | integer | 否 | - | >0 | 用户筛选 |
| `course_id` | integer | 否 | - | >0 | 课程筛选 |
| `admin_id` | integer | 否 | - | >0 | 操作管理员筛选 |
| `action` | string | 否 | - | `gift` / `reset` / `revoke` | 操作类型筛选 |

- 出参：`PageResponse<AdminUserCourseLog>`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 操作日志 ID |
| `admin_id` | integer | 操作管理员 ID |
| `admin_username` | string \| null | 管理员账号展示字段 |
| `user_id` | integer | 目标用户 ID |
| `user_nickname` | string \| null | 用户昵称展示字段 |
| `user_mobile` | string \| null | 用户手机号展示字段 |
| `course_id` | integer | 课程 ID |
| `course_title` | string \| null | 课程标题展示字段 |
| `action` | string | `gift` 新增授权 / `reset` 重置有效期 / `revoke` 收回授权 |
| `valid_days` | integer \| null | 本次授予的有效天数；收回时为空 |
| `expire_time` | datetime \| null | 本次授权到期时间（UTC）；收回时为被收回的原到期时间 |
| `created_at` | datetime | 操作时间（服务器本地时间 +8） |

- 排序：操作时间倒序，同一时间按 ID 倒序。
- 说明：本接口覆盖赠课、重置有效期与收回三类操作；`gift_logs` 只记录首次新增授权，重置与收回以本接口为准。

> 除本节的 `created_at` 外，其余时间字段均为 UTC naive datetime，管理后台换算为 Asia/Shanghai 展示；C 端不展示有效期。

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
| 400 | `WX_LOGIN_FAIL` | 微信 `code2session` 失败，需重新进入小程序 |
| 400 | `PHONE_DENIED` | 未授权手机号（`phoneCode` 为空） |
| 400 | `WX_PHONE_DECRYPT_FAIL` | 微信手机号授权凭证无效或换取失败 |
| 409 | `ACCOUNT_CONFLICT` | 同一手机号并发登录冲突，稍后重试 |
| 400 | `INVALID_USER_KEYWORD` | 用户搜索关键词为空，或精确查找时既不是 11 位手机号也不是用户 ID |
| 404 | `USER_NOT_FOUND` | 用户不存在 |
| 404 | `USER_COURSE_NOT_FOUND` | 用户未拥有该课程，无法收回 |

### 8.3 课程、课时、媒资与赠课

| HTTP | code | 说明 |
| --- | --- | --- |
| 404 | `COURSE_NOT_FOUND` | 课程不存在 |
| 404 | `LESSON_NOT_FOUND` | 课时不存在 |
| 409 | `COURSE_IN_USE` | 课程存在课时 / 订单 / 授权 / 赠课记录 |
| 409 | `LESSON_HAS_PROGRESS` | 课时存在学习记录 |
| 409 | `COURSE_NOT_AVAILABLE` | 课程为草稿或已下架，不能下单 |
| 409 | `COURSE_ALREADY_OWNED` | 有效期内已拥有课程，不能重复下单 |
| 409 | `COURSE_ACCESS_NOT_STARTED` | 授权尚未生效，不能重复下单 |
| 400 | `COURSE_PRICE_INVALID` | 课程价格 ≤ 0 |
| 400 | `INVALID_UPDATE_FIELD` | 更新至少一个字段且不能为 null |
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
| 502 | `VOD_LIST_FAILED` | 获取腾讯云 VOD 视频库失败 |
| 502 | `VOD_IMPORT_FAILED` | 手动入库前查询 VOD 视频信息失败 |
| 404 | `VOD_REMOTE_NOT_FOUND` | 视频在腾讯云 VOD 中不存在或已删除，未写入本地记录 |

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
| 409 | `ORDER_NOT_PENDING` | 仅待支付订单可以取消 / 继续支付 |
| 409 | `ORDER_NOT_PAYABLE` | 虚拟支付（wx_vpay）订单不能走微信支付 v3 继续支付 / 取消 |
| 404 | `VPAY_PRODUCT_NOT_FOUND` | 虚拟支付商品不存在或已下架 |
| 409 | `VPAY_PRODUCT_DISABLED` | 虚拟支付商品映射已停用 |
| 409 | `VPAY_PRODUCT_ENV_MISMATCH` | 课程未配置当前购买环境（正式 / 沙箱）的商品 |
| 409 | `VPAY_PRICE_MISMATCH` | 虚拟支付商品价与课程价不一致 |
| 409 | `ORDER_CREATE_TOO_FREQUENT` | 虚拟支付下单请求处理中（连点保护） |
| 503 | `PAYMENT_UNAVAILABLE` | 虚拟支付 offerId / AppKey 未配置（v3 下单失败为 502） |
| 409 | `ORDER_STATE_UNSUPPORTED` | 微信交易状态不支持取消 |
| 409 | `PAYMENT_CLOSE_TOO_EARLY` | 下单未满配置的关单时长，暂不能关单 |
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
4. 虚拟商品只允许 `wx.requestVirtualPayment`；支付成功后不要只依赖支付面板回调：跳转支付成功页并轮询 `GET /payments/query-order/{order_no}`，以服务端 `paid`（由 xpay 推送发货）为准，确认后停止轮询；取消支付时订单保持 `pending`，返回课程页重新下单。
5. 播放鉴权接口返回的 `play_url` 直接交给原生 `video` 组件；`signature` 仅保留给官方插件方案，前端不得自行拼接 CDN 地址或延长有效期。地址获取失败时展示可重试提示。
6. 课程详情页未拥有时不返回任何视频信息，前端不提供试看入口。
7. 后台不提供任何学员侧操作；订单页没有操作列，课时页没有播放按钮。
8. 生产环境所有请求必须走 HTTPS；Swagger / ReDoc / OpenAPI 由 Nginx 屏蔽。
