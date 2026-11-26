# 专项指导预约 · 业务逻辑说明

> 适用范围：C 端微信小程序「我的预约」、B 端后台「预约管理」、预约次数账户、
> 时段配置，以及购课 / 赠课 / 后台分配三条次数来源。
>
> 代码位置：
>
> - 后端服务：[appointment_service.py](../backend/app/services/appointment_service.py)、
>   [appointment_admin_service.py](../backend/app/services/appointment_admin_service.py)
> - 接口：[client/appointments.py](../backend/app/api/v1/client/appointments.py)、
>   [admin/appointments.py](../backend/app/api/v1/admin/appointments.py)
> - 数据模型：[appointment.py](../backend/app/models/appointment.py)、
>   [user_appointment_quota.py](../backend/app/models/user_appointment_quota.py)、
>   [appointment_quota_log.py](../backend/app/models/appointment_quota_log.py)、
>   [appointment_slot_config.py](../backend/app/models/appointment_slot_config.py)
> - 迁移：[0010_appointment_consolidation.py](../backend/alembic/versions/0010_appointment_consolidation.py)
> - 小程序：[pages/appointment/index.tsx](../miniprogram/src/pages/appointment/index.tsx)
> - 后台：[AppointmentsPage.tsx](../admin-web/src/pages/admin/AppointmentsPage.tsx)

---

## 1. 业务目标与边界

学员购买 / 获赠 / 被后台分配「专项指导次数」后，可以在后台开放的日期与时段内
预约一次 1 对 1 专项指导；到访后由管理员标记完成，或在开始前由学员 / 管理员取消。
取消退还 1 次，完成不退还。

明确边界：

- 预约不涉及支付：次数在购课支付成功、赠课、后台分配时产生。
- 预约没有试看、退款、评论、优惠券等能力，遵守项目既有功能禁令。
- 后台不能代学员下单，也不能播放视频；后台只做查询、完成、取消、分配、回收和配置。
- C 端 JWT 与 Admin Token 使用不同密钥，权限完全隔离：
  - C 端全部接口依赖 `UserDep`；
  - 后台全部接口由路由器级 `admin_dep` 保护。

### 1.1 架构收敛原则

当前实现只保留**一个学员一个次数账户**：

- 次数账户仅按 `user_id` 唯一，不再区分课程；
- 预约请求、响应、列表、后台表格都不再出现课程维度；
- 取消预约不再是可展示状态，而是直接软删除，记录不再对外展示；
- `appointment.course_id` 仅保留数据库列用于历史追溯，业务代码不写、不读、不返回；
- `appointment.status` 的 `cancelled` 枚举仅为兼容历史数据保留，代码不再写入。

---

## 2. 数据模型

### 2.1 四张预约表

| 表 | 作用 | 关键约束 |
| --- | --- | --- |
| `user_appointment_quota` | 学员的预约次数账户，一人一条 | `UNIQUE(user_id)`（`uk_user`）；`0 <= used_count <= total_count` |
| `appointment_quota_log` | 次数变动流水，只增不改 | `UNIQUE(source, biz_no)`；`quantity` 正数增加、负数消耗 |
| `appointment` | 预约记录 | `UNIQUE(appointment_no)`；`end_time > start_time`；软删除 |
| `appointment_slot_config` | 可预约时段配置 | 单行契约（永远只读取 id 最小的第一行） |

### 2.2 与课程相关的扩展字段

| 表.字段 | 语义 |
| --- | --- |
| `courses.appointment_quota` | 购买 / 赠送该课程时附带的预约次数，默认 0 |
| `user_courses.appointment_quota_count` | 该次购课 / 赠课发生时附带的次数快照，用于展示与审计 |

> 课程只决定「发放多少次」。
> 真正的可用余额只存在 `user_appointment_quota`，由学员全部课程共享。

### 2.3 次数账户语义

- 账户由 `user_id` 唯一确定，不再有通用 / 课程专属之分。
- MySQL `UNIQUE` 对 `NULL` 不去重的问题已通过迁移收敛为 `uk_user(user_id)` 彻底消除。
- 余额不落库，实时计算：

```text
remaining = max(0, total_count - used_count)
```

- 账户不会因为剩余为 0 而删除；后台次数账户列表仍可看到账户。
- 历史迁移时同一用户的多个账户合并为一条：
  `total_count = SUM(total_count)`、`used_count = SUM(used_count)`；
  `used_count` 超出 `[0, total_count]` 的异常值会被钳制并记录 warning 日志；
  原 `appointment.quota_id` 与 `appointment_quota_log.quota_id` 全部改指向合并后的账户。

### 2.4 预约记录字段

| 字段 | 说明 |
| --- | --- |
| `appointment_no` | `APT + YYYYMMDD + 6 位随机数字`，最多重试 3 次 |
| `course_id` | **仅历史追溯**，新预约永远写 NULL，业务不读不返回 |
| `quota_id` | 本次实际消耗的次数账户；取消时按此账户退回 |
| `appointment_date` / `start_time` / `end_time` | 北京时间业务自然时间 |
| `status` | `pending` / `completed` / `expired`；历史数据可能有 `cancelled`，但不再写入与展示 |
| `is_deleted` / `deleted_at` | 软删除标记与时间（UTC）；取消预约时写入 |
| `user_remark` | 学员备注，≤255，空白转 NULL |
| `admin_remark` | 管理员备注，≤255，空白转 NULL |
| `completed_at` / `completed_by` | 完成时间（UTC）与操作管理员 |
| `cancelled_at` | 历史取消时间；新取消流程不再写入，改用 `deleted_at` |
| `created_at` / `updated_at` | UTC naive，由 `UtcTimestampMixin` 写入 |

索引 `idx_appointment_deleted(is_deleted, status)` 服务于「只看未删除记录」的查询。

### 2.5 次数流水字段

| 字段 | 说明 |
| --- | --- |
| `quantity` | 正数增加，负数消耗 |
| `source` | `purchase` 购课赠送 / `admin` 后台分配或赠课 / `consume` 预约消耗 / `cancel` 取消退还 / `reclaim` 后台回收 |
| `biz_no` | 订单号、`GIFT{赠课日志ID}`、`UC{用户课程日志ID}`、预约号；后台直接分配与回收为 NULL |
| `operator_id` | 后台操作人；支付回调与 C 端操作（消耗 / 取消）为空 |
| `remark` | 备注 |

`UNIQUE(source, biz_no)` 是支付回调、赠课、预约消耗 / 取消重试的幂等兜底。
MySQL 的 `UNIQUE` 允许多个 `NULL`，因此后台「直接分配次数」不带业务号时天然
不做幂等——每点一次分配就真的加一次，前端必须防重复提交。

---

## 3. 时间约定（非常重要）

| 数据 | 存储 | 生成方式 |
| --- | --- | --- |
| `appointment_date` | `DATE` 北京时间自然日期 | 业务时区 `UTC+8` |
| `start_time` / `end_time` | `TIME` 北京时间自然时间 | 业务时区 `UTC+8` |
| 时段配置的工作时间 | `TIME` 北京时间 | 后台录入 |
| `created_at` / `updated_at` | UTC naive | `UtcTimestampMixin` |
| `completed_at` / `deleted_at` | UTC naive | `datetime.now(timezone.utc)` 去时区 |
| 次数流水 `created_at` | UTC naive | `UtcCreatedAtMixin` |

- 业务时区固定为 `timezone(timedelta(hours=8))`，不依赖服务器系统时区或
  `Asia/Shanghai` 时区数据库（中国无夏令时）。
- `business_now()` 返回「UTC+8 的 naive datetime」，用于：
  - 判断今天 / 可预约日期范围；
  - 判断「最少提前小时数」；
  - 判断取消截止时间。
- 后台与小程序展示 UTC 时间列时统一 `+8` 小时换算。
- 小程序计算预约开始的毫秒时间戳时使用
  `Date.UTC(year, month-1, day, hour-8, minute)`，与后端业务时区一致。
- 修改服务器宿主机时区不会影响预约业务时间。

---

## 4. 预约次数从哪来

所有来源最终都调用同一个入口：

```python
grant_quota_count(
    session,
    user_id,
    count,
    source,
    biz_no=None,
    operator_id=None,
    remark=None,
) -> UserAppointmentQuota | None
```

该函数**不再接收 `course_id`**；课程只在调用方决定 `count` 时被读取。
`biz_no` 非空时先按 `(source, biz_no)` 查流水，已存在则直接返回当前账户，
不重复加次数；数据库唯一约束是并发下的最后防线。

### 4.1 购课支付成功（purchase）

触发点：微信支付成功回调的订单完成事务。

逻辑：

1. 读取订单对应课程 `courses.appointment_quota`，得到 `N`。
2. 建立或复用学员课程授权，`user_courses.appointment_quota_count = N`。
3. `N <= 0` 直接跳过；否则调用
   `grant_quota_count(count=N, source=purchase, biz_no=order_no)`，
   累加到该学员唯一的次数账户。
4. 重复支付回调或补偿流程再次调用时，先按 `(purchase, order_no)` 查流水：
   已存在则不再累加；数据库唯一约束是并发下的最后防线。
5. 每次新订单都会按该订单号发一次；同一订单永远只发一次。
6. 已拥有课程但支付成功、付款期间被赠课等分支，不覆盖已有播放授权；
   但本订单对应的预约次数仍按订单号发放一次。

### 4.2 后台按手机号赠课（gift）

触发点：后台「赠课」按手机号绑定。

1. 按手机号解析用户；`GiftValidity.ONE_YEAR` 或永久。
2. 若该用户已拥有该课程：**整单跳过**，返回「已拥有」结果，不重复发放次数。
3. 否则创建 `user_courses`（`source=gift`，写入次数快照）与 `gift_log`。
4. 若 `courses.appointment_quota > 0`，调用 `grant_quota_count`：
   - `source=admin`；
   - `biz_no = GIFT{gift_log.id}`；
   - `remark = 后台赠课赠送`。
5. 并发重复赠课由 `user_courses` 唯一约束兜底：捕获 `IntegrityError` 后复查，
   已拥有则返回重复结果，否则报冲突。
6. 因此同手机号 + 同课程不会重复发放，次数也只随第一次成功赠课发放。

### 4.3 后台「赠送 / 重置课程」（admin course grant）

触发点：后台用户课程管理中的赠送 / 重置有效期。

1. 读取课程 `courses.appointment_quota`，写入 / 更新
   `user_courses.appointment_quota_count`。
2. 无论新建授权还是重置已有授权，都会用新的 `user_course_log.id` 生成
   `biz_no = UC{log_id}`，并发放一次课程配置的预约次数。
3. 结果：**重置有效期会再次发放预约次数**。这是当前实现的实际行为，
   本次不改变该策略；若因重复重置多发，管理员用 4.5 的「回收次数」人工冲正。
4. `_apply_grant` 失败重试一次，仍冲突则返回 `GIFT_CONFLICT`。

### 4.4 后台直接分配次数（admin grant）

接口：`POST /admin/appointment-quotas/grant`。

- `user_id` 与 `user_phone` **必须且只能填一个**。
- 手机号查不到 → `USER_NOT_FOUND`；一个手机号对应多个用户 →
  `MOBILE_AMBIGUOUS`，要求改用用户 ID。
- **不再接收 `course_id`**；请求体携带 `course_id` 会因 `extra="forbid"` 返回 422。
- `count` 范围 1–1000。
- 账户不存在时先锁定用户行再创建（`get_or_create_quota`）。
- `total_count += count`，写 `admin` 流水：
  - `biz_no = NULL`，**不幂等**；
  - `operator_id = 管理员 ID`；
  - `remark = 请求备注或「后台分配预约次数」`。
- 回包返回账户累计 / 已用 / 剩余。

### 4.5 后台回收次数（reclaim）

接口：`POST /admin/appointment-quotas/reclaim`。

- 请求：`quota_id`（账户 ID）、`count`（1–1000）、`remark`（可选，≤255）。
- 只允许回收**未使用的剩余次数**：
  - `remaining = total_count - used_count`；
  - `count > remaining` → `409 QUOTA_INSUFFICIENT`，提示「最多可回收 N 次」；
  - `count` 非法 → 422；账户不存在 → `404 QUOTA_NOT_FOUND`。
- 回收在账户行锁内执行：`total_count -= count`，`used_count` 不变，
  保证 `used_count <= total_count` 的数据库约束不被破坏。
- 写一条负向流水：
  - `source = reclaim`；
  - `quantity = -count`；
  - `biz_no = NULL`（不幂等，前端提交期间必须禁用按钮）；
  - `operator_id = 管理员 ID`；
  - `remark = 请求备注或「后台回收预约次数」`。
- 已消耗的次数不会被回收，历史预约与 `consume` / `cancel` 流水保持不变。

### 4.6 次数来源汇总

| 来源 | `source` | `biz_no` | 幂等 |
| --- | --- | --- | --- |
| 购课支付成功 | `purchase` | 订单号 | 是（按订单号） |
| 按手机号赠课 | `admin` | `GIFT{赠课日志 ID}` | 是（同课程已拥有则整单跳过） |
| 后台赠课 / 重置课程 | `admin` | `UC{操作日志 ID}` | 每次操作都会新增 |
| 后台直接分配 | `admin` | `NULL` | 否 |
| 预约消耗 | `consume` | 预约号 | 每张预约最多一次 |
| 取消退还 | `cancel` | 预约号 | 每张预约最多一次（软删除后不可再取消） |
| 后台回收 | `reclaim` | `NULL` | 否（仅能回收剩余次数） |

### 4.7 课程次数配置变更不追溯

`courses.appointment_quota` 只是**发放时读取的配置**，不是账户余额的计算依据：

- 次数在购买支付成功 / 赠课成功的那一刻一次性累加进
  `user_appointment_quota.total_count`，并写一条不可变的流水；
- 此后修改课程次数，**不会**修改任何学员的账户余额、历史流水或
  `user_courses.appointment_quota_count` 快照；
- 同一订单的重复回调仍按 `(purchase, order_no)` 幂等，不会按新配置补发；
- 已赠课学员再次赠课会被「已拥有」规则整单跳过，同样不会按新配置补发；
- 只有**配置变更之后新发生的支付成功 / 赠课**，才按当时读取到的新值发放。

边界：配置读取发生在支付成功回调事务内。因此「变更前下单、变更后才支付成功」
的订单按**变更后的新配置**发放；本需求以支付成功时刻判定「修改后购买」。

---

## 5. 时段配置与可约时段生成

### 5.1 单行配置

`appointment_slot_config` 永远只使用一行。读取时取 `id` 最小的记录；不存在时按
默认值自动补建。后台保存为**全量覆盖**，并在行锁内完成，避免并发覆盖互相踩踏。

| 字段 | 默认值 | 允许范围 |
| --- | --- | --- |
| `weekdays` | `[1,2,3,4,5,6,7]` | 1–7（ISO：1=周一），去重排序后 1–7 个 |
| `work_start_time` | `10:00` | 必须早于结束时间 |
| `work_end_time` | `20:00` | 必须晚于开始时间 |
| `slot_minutes` | `60` | 15–720 分钟 |
| `slot_capacity` | `1` | 1–100 人 / 时段 |
| `advance_days` | `7` | 1–90 天 |
| `min_advance_hours` | `24` | 0–720 小时 |
| `enabled` | `true` | 是否开放预约 |

配置修改立即生效，包括对**已存在**的预约：取消截止时间读取的是当前配置的
`min_advance_hours`，不是预约创建时的快照。

### 5.2 时段生成算法

```text
cursor = work_start_time
end_limit = work_end_time
while cursor + slot_minutes <= end_limit:
    生成 [cursor, cursor + slot_minutes)
    cursor += slot_minutes
```

特点：

- 时段左闭右开；
- 只生成完整落在工作窗口内的时段，最后不足一个时长的尾巴丢弃；
- 例：10:00–20:00、60 分钟 → 10:00–11:00 … 19:00–20:00，共 10 个；
- 例：10:00–20:00、90 分钟 → 10:00–11:30 … 18:30–20:00，共 7 个；
- 时段固定对齐 `work_start_time`，不能任意指定中间时间。

### 5.3 某天有哪些时段可展示

对 `[today, today + advance_days - 1]` 内每一天：

1. 若预约功能关闭，或该 ISO 星期不在 `weekdays` 中 → 当天无时段；
2. 对每个生成的时段，若 `当日开始时间 < 当前业务时间 + min_advance_hours`
   → **不返回该时段**；
3. 统计该 `(日期, 开始时间)` 下 `is_deleted = 0` 且状态为 `pending` 或
   `completed` 的预约数 `booked`；
4. `available = max(0, slot_capacity - booked)`；
5. 日期胶囊的 `has_available = 该天存在 available > 0 的时段`。

注意：

- 取消即软删除，`is_deleted = 1` 的记录不占容量，取消后时段立即重新可约；
- `expired` 不占容量；`completed` 仍计入 booked（但这些时段通常已经过去）；
- 最小提前时间会随时间流逝实时过滤，页面需要重新拉取时段才能看到最新可约状态。

### 5.4 可预约日期范围

- 默认查询：今天；
- 显式传 `?date=`：必须落在 `[today, today + advance_days - 1]`，
  否则 `400 APPOINTMENT_DATE_INVALID`；
- 关闭预约时返回 `enabled=false`、`dates=[]`、`slots=[]`，即使请求日期合法。

---

## 6. C 端接口与业务顺序

全部接口前缀 `/client/appointments`，全部要求 C 端用户 JWT，用户身份只从 JWT 读取，
客户端不能指定 `user_id`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/overview` | 次数概览 + 取消时限 |
| GET | `/available-slots?date=YYYY-MM-DD` | 日期胶囊 + 指定日期时段 |
| GET | `/my-list?status=&page=&page_size=` | 我的预约分页 |
| POST | `/create` | 新增预约 |
| POST | `/{appointment_no}/cancel` | 取消预约（软删除并退还 1 次） |

### 6.1 次数概览

返回：

- `remaining_total`：唯一账户的 `total_count - used_count`（不小于 0）；
- `purchased_total`：唯一账户的 `total_count`；
- `used_total`：唯一账户的 `used_count`（取消后已回退）；
- `pending_count` / `completed_count`：该用户未删除预约的状态计数；
- `min_advance_hours`：当前配置的提前时限，小程序用它决定取消按钮是否可见。

**不再返回 `quotas` 数组**，也不再有任何课程维度明细。页面只展示
「剩余可预约次数 N 次」与「累计获得 X 次 / 已使用 Y 次」。

### 6.2 我的预约列表

- 只查当前用户，且强制 `is_deleted = 0`；
- `status` 仅允许 `pending` / `completed` / `expired` / `all`（或空）；
  - `cancelled` 会被拒绝并返回 **422**（提示改用 `all`）；
- 默认分页 1/20，`page_size` 上限 100；
- 排序：预约日期降序 → 开始时间降序 → id 降序；
- 返回字段不含 `course_id` / `course_title` / `is_deleted`；
  小程序卡片标题固定为「专项指导」。

### 6.3 创建预约（核心）

请求：

```json
{
  "appointment_date": "2026-11-20",
  "start_time": "10:00",
  "user_remark": "想重点了解定价策略"
}
```

- **不再接收 `course_id`**；请求体携带 `course_id` 会因 `extra="forbid"` 返回 422。
- `user_remark` 空白会转 NULL，最长 255。

后端严格按以下顺序校验（任何一步失败都不会扣次数）：

1. **锁定配置行**：`SELECT ... FOR UPDATE` 读取单行配置，串行化所有预约创建，
   使「容量复核 → 落库」之间不被并发穿透。
2. **功能开关**：`enabled=false` → `409 APPOINTMENT_DISABLED`。
3. **日期范围**：必须 `[今天, 今天 + advance_days - 1]` →
   否则 `400 APPOINTMENT_DATE_INVALID`。
4. **开放星期**：`isoweekday()` 不在 `weekdays` →
   `400 APPOINTMENT_DATE_INVALID`（文案「当日不开放预约」）。
5. **时段必须落在网格上**：
   - 秒 / 微秒必须为 0；
   - `start_time` 必须是 `_slot_ranges` 生成的开始时间；
   - 否则 `400 APPOINTMENT_SLOT_INVALID`。
6. **不能预约过去**：`日期 + 开始时间 <= 当前业务时间` →
   `400 APPOINTMENT_SLOT_INVALID`。
7. **最少提前时间**：`开始时间 < 现在 + min_advance_hours` →
   `400 APPOINTMENT_ADVANCE_REQUIRED`。
8. **锁定用户行**：同一用户的预约提交串行化。
9. **重复预约**：同一用户、同一日期、同一起始时间，已存在
   `is_deleted = 0` 且状态为 `pending` / `completed` → `409 APPOINTMENT_DUPLICATE`。
   - 已取消（软删除）的记录不阻止重新预约。
10. **读取唯一账户**：不存在则先锁用户行再建户（`get_or_create_quota`）；
    `remaining <= 0` → `409 APPOINTMENT_QUOTA_INSUFFICIENT`。
    不再有课程账户选择或回退逻辑。
11. **原子扣次数**：

```sql
UPDATE user_appointment_quota
SET used_count = used_count + 1
WHERE id = :quota_id AND used_count < total_count;
```

    影响行数必须为 1，否则 `409 APPOINTMENT_QUOTA_INSUFFICIENT`。
    绝不采用「先查询余额再写回」的方式。

12. **复核容量**：统计同日期、同开始时间下 `is_deleted = 0` 且
    `pending` / `completed` 的数量，若 `>= slot_capacity` →
    `409 APPOINTMENT_SLOT_FULL`。此时异常会让整个事务回滚，第 11 步扣掉的
    次数自动恢复。
13. **生成预约号并落库**：`APT + 当天日期 + 6 位随机数`，`course_id` 写 NULL，
    在嵌套事务（savepoint）中插入；唯一键冲突最多重试 3 次，仍失败 → 500。
14. **写消耗流水**：`quantity=-1`、`source=consume`、
    `biz_no=appointment_no`、备注「预约消耗」。
15. **提交事务**，刷新预约，读取当前用户账户剩余次数。
16. 返回预约详情、`remaining_count`、「预约成功」；响应不含任何课程字段。

关键保证：

- 配置行锁覆盖容量复核与落库，**最后一个时段不会被并发超卖**；
- 用户行锁覆盖重复检查、建户与扣次，**同一用户并发提交不会产生两条 pending**；
- 配额扣减是原子条件更新，多个请求不会把同一账户扣成负数；
- 容量复核失败会回滚已扣次数；
- 预约、消耗流水、次数变更在同一事务内提交，不会出现「扣了次数没预约」或
  「有预约没扣次数」的半完成状态；
- 预约号唯一约束 + 重试避免随机碰撞。

### 6.4 取消预约

请求：`POST /client/appointments/{appointment_no}/cancel`（无 body）。

顺序：

1. 按预约号 + 当前用户 + `is_deleted = 0` 查询并 `SELECT ... FOR UPDATE`
   锁定预约；不属于本人或不存在（含已取消）→ `404 APPOINTMENT_NOT_FOUND`。
2. 状态必须是 `pending`，否则 `409 APPOINTMENT_STATUS_INVALID`。
3. 读取**当前**时段配置，计算截止时间：

```text
deadline = 预约开始时间 - min_advance_hours
若 当前业务时间 > deadline → 409 APPOINTMENT_CANCEL_TOO_LATE
```

4. **软删除**：`is_deleted = 1`、`deleted_at` 写 UTC 时间；
   **状态保持 `pending`**，不写 `cancelled`，也不写 `cancelled_at`。
5. 原子退回 1 次：

```sql
UPDATE user_appointment_quota
SET used_count = used_count - 1
WHERE id = appointment.quota_id AND used_count > 0;
```

    影响行数不为 1 → 500（数据异常，不静默成功）。
6. 写退还流水：`quantity=+1`、`source=cancel`、
   `biz_no=appointment_no`、备注「用户取消预约」。
7. 提交，返回：

```json
{
  "appointment_no": "APT20261120000123",
  "remaining_count": 1,
  "message": "已取消预约，已退还1次预约次数"
}
```

**不返回状态**，列表中该记录立即消失。

特点：

- 取消只退回原账户（`appointment.quota_id`），账户唯一后即学员的唯一账户；
- 管理员在后台取消**不受** `min_advance_hours` 限制；
- 学员端截止时间随后台配置实时变化，前端通过 `/overview` 的
  `min_advance_hours` 获取，不再硬编码 24 小时。

---

## 7. 状态机

```text
                学员 / 管理员取消（退 1 次，软删除，列表不再展示）
        ┌──────────────────────────────────────────────────────► (is_deleted=1)
        │
     pending ──────────────────────────────────────────────────► completed
        │        管理员确认完成（不退次数）
        │
        │  （预留状态，当前无定时任务）
        └──────────────────────────────────────────────────────► expired
```

| 当前状态 | 允许动作 | 次数变化 |
| --- | --- | --- |
| `pending`（未删除） | 学员取消（需在截止时间前） | `-1` 后 `+1`，净 0 |
| `pending`（未删除） | 管理员取消 | `-1` 后 `+1`，净 0 |
| `pending`（未删除） | 管理员完成 | 不变（已消耗） |
| `completed` | 无 | 不变 |
| `expired` | 无 | 不变 |
| 已软删除 | 无（可重新预约同一时段） | 不变 |

关于 `cancelled`：

- 枚举值仍存在于数据库以兼容历史数据；
- 迁移已把历史 `cancelled` 记录转为 `is_deleted = 1`，
  `deleted_at = COALESCE(cancelled_at, updated_at)`；
- 业务代码不再写入该状态，接口也不再接受 `status=cancelled` 筛选。

关于 `expired`：

- 枚举、数据库约束、后台筛选项、标签都已预留；
- 当前**没有**定时任务把过期的 `pending` 自动置为 `expired`；
- 因此过了时间仍未处理的预约会一直显示「待完成 pending」；
- 按设计，`expired` 不退还次数。

---

## 8. 后台接口与逻辑

全部接口前缀 `/admin`，路由器级 Admin Token 保护。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/appointments` | 预约分页列表 |
| POST | `/appointments/{no}/complete` | 标记完成（不退还次数） |
| POST | `/appointments/{no}/cancel` | 强制取消（软删除并退还 1 次） |
| GET | `/appointment-quotas` | 次数账户列表 |
| POST | `/appointment-quotas/grant` | 手工分配次数 |
| POST | `/appointment-quotas/reclaim` | 手工回收未使用的剩余次数 |
| GET | `/appointment-quotas/logs` | 次数变动流水 |
| GET | `/appointment-slot-config` | 读取时段配置（缺失时补建默认行） |
| PUT | `/appointment-slot-config` | 全量保存时段配置 |

### 8.1 预约列表

- 强制 `is_deleted = 0`；
- 状态：`pending` / `completed` / `expired` / 不传或 `all`；
  - `cancelled` 会被拒绝并返回 **422**；
- 关键词：预约号、手机号、昵称，LIKE 通配符已转义，最长 100；
- 日期范围：`date_start <= appointment_date <= date_end`，
  且请求层校验 `date_start <= date_end`；
- 排序：日期降序 → 开始时间降序 → id 降序；
- 默认每页 20，最大 100；
- 返回学员昵称 / 手机号 / 头像、日期时段、状态、学员备注、后台备注、
  完成人与完成时间；
- **不返回课程字段与 `is_deleted`**；页面标题固定「专项指导」。

### 8.2 标记完成

1. 校验管理员存在；
2. 按预约号 + `is_deleted = 0` 行锁；
3. 仅 `pending` 可完成，否则 `409 APPOINTMENT_STATUS_INVALID`；
4. 置为 `completed`，写 `completed_at`（UTC）、`completed_by`；
5. 可选 `admin_remark` 覆盖后台备注；
6. **不退次数、不写次数流水**；
7. 返回最新预约详情。

后台完成弹窗提示：「已标记完成，本次不退还预约次数」。

### 8.3 强制取消

1. 校验管理员、行锁未删除预约；
2. 仅 `pending` 可取消，否则 `409 APPOINTMENT_STATUS_INVALID`；
3. 软删除：`is_deleted = 1`、`deleted_at` 写 UTC；状态保持 `pending`；
4. 可选 `admin_remark`；
5. 原子退回 1 次，失败 → 500；
6. 写 `cancel` 流水：`+1`、`biz_no=预约号`、`operator_id=管理员`、
   备注为管理员备注或「管理员取消预约」；
7. 提交并返回 `{appointment_no, message}`，
   `message = 已取消预约，已退还1次预约次数`。

后台取消**没有**「距开始不足 X 小时」限制，用于处理临时爽约、排期调整等情况。
页面 Popconfirm 提示：「取消后将退还学员1次预约次数，该记录不再展示」。

### 8.4 次数账户列表

- 一人一账户；
- 关键词匹配手机号 / 昵称；纯数字同时按用户 ID 匹配；
- `has_remaining=true`：只显示 `total_count > used_count` 的账户；
- 返回：用户信息、累计 / 已用 / 剩余、账户备注、
  最近一次「正向发放」时间（相关子查询：该账户 `quantity > 0` 的最新流水）；
- **不返回课程字段**；
- 排序：`updated_at` 降序 → id 降序。

### 8.5 分配次数

见 4.4。后台页面在提交期间禁用按钮，避免因接口不幂等造成重复发放。

### 8.6 回收次数

见 4.5。请求体：

```json
{
  "quota_id": 8,
  "count": 3,
  "remark": "重复重置多发，人工冲正"
}
```

- 出参：`quota_id`、`user_id`、`total_count`、`used_count`、`remaining`、
  `message=回收成功`；
- 只回收剩余未用次数；`used_count` 不变；
- 写 `source=reclaim`、`quantity=-count` 的负向流水；
- 错误：`404 QUOTA_NOT_FOUND`、`409 QUOTA_INSUFFICIENT`、`422 VALIDATION_ERROR`。
- 后台页面在提交期间禁用按钮，避免重复回收。

### 8.7 次数流水

- 按 `user_id` / `quota_id` 可选过滤；
- 返回账户 ID、操作管理员、来源、数量、业务号、备注、时间；
- **不返回课程字段**；
- 排序：创建时间降序 → id 降序；
- 只读，不提供修改 / 删除接口。

### 8.8 时段配置

- GET 时若无配置行，按默认值创建并提交；
- PUT 为全量覆盖，行锁保护；
- 保存后立即影响：
  - C 端可预约日期与时段；
  - C 端创建校验；
  - 学员取消截止时间；
  - 时段容量。

---

## 9. 错误码

| HTTP | code | 触发场景 |
| --- | --- | --- |
| 400 | `APPOINTMENT_DATE_INVALID` | 日期不在可预约范围；当天不开放 |
| 400 | `APPOINTMENT_SLOT_INVALID` | 时间不在时段网格、秒/微秒非 0、时段已过 |
| 400 | `APPOINTMENT_ADVANCE_REQUIRED` | 未满足最少提前小时数 |
| 404 | `APPOINTMENT_NOT_FOUND` | 预约不存在、不属于当前用户或已取消 |
| 404 | `USER_NOT_FOUND` | 后台分配时用户不存在 |
| 404 | `QUOTA_NOT_FOUND` | 后台回收时次数账户不存在 |
| 409 | `QUOTA_INSUFFICIENT` | 回收数量超过剩余未使用次数 |
| 409 | `APPOINTMENT_DISABLED` | 预约功能关闭 |
| 409 | `APPOINTMENT_DUPLICATE` | 同用户同日同起始时间已有未删除的 pending / completed |
| 409 | `APPOINTMENT_QUOTA_INSUFFICIENT` | 账户不存在或余额不足 |
| 409 | `APPOINTMENT_SLOT_FULL` | 时段容量已满 |
| 409 | `APPOINTMENT_STATUS_INVALID` | 非 pending 状态执行完成 / 取消 |
| 409 | `APPOINTMENT_CANCEL_TOO_LATE` | 学员取消时已过截止时间 |
| 409 | `MOBILE_AMBIGUOUS` | 手机号对应多个用户 |
| 409 | `GIFT_CONFLICT` | 后台赠课 / 重置写入冲突 |
| 422 | `VALIDATION_ERROR` | 字段缺失、范围越界、`user_id/user_phone` 二选一不满足、请求体携带 `course_id`、状态筛选为 `cancelled` 等 |
| 401 / 403 | 认证 / 权限错误 | 缺少或错误的 C 端 JWT / Admin Token |

说明：

- 预约 / 分配场景**不再出现 `COURSE_NOT_FOUND`**；请求体携带 `course_id`
  直接按参数校验失败返回 422；
- 查询参数依赖模型（`Depends()`）的校验失败也统一由全局异常处理器转为
  422 `VALIDATION_ERROR`，因此 `status=cancelled` 不会再变成 500；
- 小程序对主要错误码有中文文案映射；未知错误回退到通用错误提示。

---

## 10. 并发与幂等设计

### 10.1 已保证

| 场景 | 机制 |
| --- | --- |
| 同一账户并发扣次数 | `UPDATE ... WHERE used_count < total_count` 原子条件更新 |
| 同一账户并发退次数 | `UPDATE ... WHERE used_count > 0` |
| 末位时段并发超卖 | 创建预约先 `SELECT ... FOR UPDATE` 锁单行配置，容量复核与落库串行化 |
| 同一用户并发重复提交 | 用户行 `SELECT ... FOR UPDATE` 后复查重复预约 |
| 支付回调重复 / 并发 | `(source=purchase, biz_no=order_no)` 预检查 + 唯一约束 |
| 赠课重复拨付 | 同课程已拥有直接跳过 + `user_courses` 唯一约束 |
| 次数账户并发创建 | 先 `SELECT ... FOR UPDATE` 锁用户行；`uk_user` 唯一键兜底 |
| 预约号碰撞 | 唯一约束 + savepoint 内最多 3 次重试 |
| 预约与次数一致性 | 预约、扣次、流水同一事务；容量失败整体回滚 |
| 管理员并发完成 / 取消 | 预约行 `SELECT ... FOR UPDATE` + 状态校验 |

### 10.2 保持不变的已知行为

1. **后台直接分配不幂等**
   - `biz_no=NULL`，重复提交会重复增加；依赖前端防抖与操作确认。
2. **重置有效期重复送次数**
   - 每次后台重置课程都会按 `UC{新日志 ID}` 再发一次课程配置的次数；
   - 若产品预期是「重置只刷新有效期、不补次数」，需要业务确认后调整。
3. **`expired` 无自动流转**
   - 没有定时任务；过期未处理记录会永久停留在 pending。
4. **配置变更影响存量预约**
   - 取消截止时间按当前配置计算，不是预约时快照；
   - 小程序已改为读取 `/overview.min_advance_hours`，前后端口径一致。

---

## 11. 小程序端行为

页面：`pages/appointment/index`。

### 11.1 登录与加载

- 未登录展示登录引导，不请求预约数据；
- 已登录并进入页面时并行请求：
  - 次数概览 `/overview`；
  - 我的预约列表 `/my-list`（默认「全部」）；
- 支持下拉刷新、触底加载下一页；
- 列表筛选仅有：全部 / 待完成 / 已完成；
- 状态文案：pending「待完成」、completed「已完成」、expired「已过期」。

### 11.2 次数卡片与预约抽屉

- 顶部只显示：
  - 「剩余可预约次数 N 次」；
  - 「累计获得 X 次 / 已使用 Y 次」；
- 不再展示任何课程维度标签行；
- 只有 `overview.remaining_total > 0` 时才允许打开预约抽屉；
  没有次数时引导购买课程或联系客服；
- 打开抽屉后请求可约日期与时段，默认选第一个有可用时段的日期；
- 日期胶囊显示月-日与星期；时段按钮显示 `HH:MM - HH:MM`；
  可选时段标注「可预约」，约满时段标注「已满」且不可选；
- **不再展示每个时段的剩余可预约人数**（容量仍由后端校验）；
- 抽屉内不再有课程选择控件，提交体固定为：

```json
{
  "appointment_date": "2026-11-20",
  "start_time": "10:00",
  "user_remark": "备注"
}
```

### 11.3 列表与取消

- 卡片标题固定「专项指导」，不再展示课程名；
- 卡片展示日期、星期、时段、状态、学员备注、老师留言；
- 取消窗口从 `/overview` 的 `min_advance_hours` 读取
  （概览尚未加载时暂时回退 24 小时，加载后以服务端配置为准）；
- 仅 pending 且未超过截止时间显示「取消预约」；
  否则显示「距开始不足 X 小时，不可取消」；
- 取消前弹确认框，说明「取消后退还 1 次预约次数」；
- 取消成功后：
  - 列表中该记录立即本地移除，剩余次数减 1；
  - toast 展示后端 `message`（「已取消预约，已退还1次预约次数」）；
  - 随后刷新概览与列表；
- 错误码映射为中文文案，已移除课程相关错误。

### 11.4 个人中心预约次数入口

- 已登录且非 Mock 模式下，个人中心在个人信息卡与「我的课程」之间展示
  「专项指导」卡片（白底、轻金边、柔和投影，与页面其他卡片视觉权重一致）：
  - 左上暖金色小字标题「专项指导」；
  - 中部为 `/overview` 的 `remaining_total`，后接「次可预约」，不做超大数字；
  - 右侧「去预约」按钮进入「我的预约」页；
  - 不展示累计获得 / 已使用等附加文案；
- 首次加载与每次从预约页返回（`useDidShow`）都会刷新，保证预约 / 取消后的次数即时同步；
- 概览请求失败不阻塞页面，保留上一次成功的数据；Mock 模式不请求后端。

---

## 12. 后台页面行为

页面：`/admin/appointments`，两个 Tab。

### 12.1 预约管理

- 默认筛选「全部状态」，进入页面即可看到待完成 / 已完成 / 已过期记录；
- 状态选项：待完成 / 已完成 / 已过期 / 全部状态（默认）；
- 可按状态、关键词（预约号 / 手机号 / 昵称）、预约日期范围筛选；
- 停留在「预约管理」Tab 时每 30 秒静默刷新当前筛选条件与页码的数据：
  - 刷新不清空列表、不显示整表 loading，也不覆盖已打开的详情 / 完成弹窗；
  - 浏览器标签页隐藏时暂停，切回时立即补刷一次；
  - 静默刷新失败保留当前数据，不弹出错误提示；
- 表格展示学员、日期时段、状态、备注、创建 / 完成时间与操作人；
  **不展示课程列与取消时间**；
- pending 行浅琥珀底色；
- pending 行提供「标记完成」与「取消」：
  - 标记完成弹窗宽 420px，可填后台备注，
    提示「已标记完成，本次不退还预约次数」；
  - 取消使用 Popconfirm，提示
    「取消后将退还学员1次预约次数，该记录不再展示」；
  - 提交期间按钮 loading / 禁用，防止重复操作；
- 取消成功后刷新列表，该行立即消失；
- completed 行可打开详情 Drawer；
- 分页默认 20。

### 12.2 次数账户

- 可按关键词（手机号 / 昵称 / 用户 ID）与「仅看有剩余」筛选；
- 表格列：学员 / 累计 / 已用 / 剩余 / 最近发放 / 备注 / 操作；
  - 剩余 > 0 显示绿色 Tag，= 0 显示灰色 Tag；
  - 不再有「次数归属」课程列；
- 每行操作列提供「分配」「回收」「流水」；
  - 剩余为 0 时「回收」禁用；
  - 「回收」弹窗最多只能填当前剩余次数，提交前前端再次校验，后端行锁兜底；
- 顶部提供全局「分配次数」入口：先搜索用户，再填写次数；
- 两个分配 / 回收弹窗都**没有课程选择**；
- 分配 / 回收次数范围 1–1000，手机号格式前端校验；
- 流水 Drawer 不再展示次数归属，来源会显示「后台回收」。

### 12.3 课程管理中的预约次数

- 课程编辑弹窗保留「赠送指导预约次数」`InputNumber`：
  - 默认 0，0–1000 整数；
  - 提示「购买或获赠该课程时自动发放到学员预约次数账户」；
- 这是课程配置预约次数的**唯一入口**，其他页面不再出现课程归属选择。

### 12.4 时段配置

- 在独立面板中配置开放星期、工作起止时间、时段长度、单时段容量、
  可提前预约天数、最少提前小时数、总开关；
- 保存为全量覆盖，保存成功提示并刷新；
- 不提供删除配置或新增第二行的入口。

---

## 13. 测试与验证

自动化测试 `backend/tests/test_appointments.py` 覆盖 19 个用例：

**C 端主流程**

1. 后台分配 → `/overview` → 预约成功 → 剩余次数减 1；
2. 同一时段重复预约拒绝且不扣次数；
3. 时段约满拒绝且不扣次数；
4. 学员取消：列表消失、退还 1 次、只写一条取消流水；
5. 学员取消后同一时段可重新预约成功。

**后台与列表**

6. 后台取消：软删除并退还 1 次、操作人写入流水；
7. 后台完成：状态 completed、剩余次数不变；
8. C 端 / 后台列表均排除软删除记录、不含课程字段、
   `status=cancelled` 均返回 422；
9. 请求体携带 `course_id` 返回 422（创建预约与后台分配各一个）。

**次数来源与配置**

10. 按配置生成可约时段；
11. 后台次数账户筛选、最近发放时间、流水字段；
12. 后台直接分配不幂等（两次分配累加，同一账户）；
13. 时段配置读取与更新；
14. 支付回调只发一次次数；
15. 按手机号赠课只发一次次数；
16. 后台重置课程再次发放配置的次数；
17. C 端 / 后台 Token 隔离；
18. 修改课程次数后，已购学员账户与快照不变、重复回调不补发，
    变更后新购学员按新配置发放；
19. 修改课程次数后，已赠课学员账户与快照不变、重复赠课不补发，
    变更后新赠学员按新配置发放。

完整后端测试套件与两端前端类型检查 / 构建均已通过。

---

## 14. 快速判断规则（运营视角）

1. 学员能不能约？
   - 功能开关打开；
   - 目标日期在 `advance_days` 内且星期开放；
   - 目标时段距现在 ≥ `min_advance_hours`；
   - 该时段 booked < `slot_capacity`；
   - 该学员唯一次数账户有剩余。
2. 学员能不能取消？
   - 状态 pending 且未软删除；
   - 当前时间 ≤ 开始时间 − 当前配置的 `min_advance_hours`。
3. 取消退不退次数？
   - 学员取消：退 1 次；
   - 管理员取消：退 1 次；
   - 管理员完成：不退；
   - 过期：按设计不退（当前无自动过期任务）。
4. 同一个人能不能重复约同一时段？
   - 该时段已有未删除的 pending / completed → 不能；
   - 之前约过但已取消（已软删除） → 可以。
5. 次数从哪来？
   - 买课按订单号发一次；
   - 按手机号赠课只在首次获得课程时发一次；
   - 后台重置课程每次都会再发一次；
   - 后台可直接分配，且每次点击都会增加。
