import { Tag } from 'antd'

import type {
  AdminUserCourseItem,
  AppointmentStatus,
  CourseStatus,
  OrderStatus,
  VodMediaStatus
} from '../../types'

const tagStyle = { marginInlineEnd: 0, borderRadius: 999 } as const

/** 统一紧凑圆角 Tag：生效绿色、过期红色、待处理琥珀色。 */
export function MediaStatusTag({ status }: { status: VodMediaStatus }) {
  if (status === 1) {
    return (
      <Tag color="success" bordered={false} style={tagStyle}>
        可用
      </Tag>
    )
  }
  if (status === 2) {
    return (
      <Tag color="error" bordered={false} style={tagStyle}>
        转码失败
      </Tag>
    )
  }
  return (
    <Tag color="warning" bordered={false} style={tagStyle}>
      转码中
    </Tag>
  )
}

export function OrderStatusTag({ status }: { status: OrderStatus }) {
  if (status === 'paid') {
    return (
      <Tag color="success" bordered={false} style={tagStyle}>
        已支付
      </Tag>
    )
  }
  if (status === 'pending') {
    return (
      <Tag color="warning" bordered={false} style={tagStyle}>
        待支付
      </Tag>
    )
  }
  if (status === 'refunded') {
    return (
      <Tag color="error" bordered={false} style={tagStyle}>
        已退款
      </Tag>
    )
  }
  return (
    <Tag bordered={false} style={tagStyle}>
      已关闭
    </Tag>
  )
}

export function UserCourseStatusTag({
  item
}: {
  item: Pick<AdminUserCourseItem, 'expired' | 'expire_time'>
}) {
  if (item.expired) {
    return (
      <Tag color="error" bordered={false} style={tagStyle}>
        已过期
      </Tag>
    )
  }
  return (
    <Tag color="success" bordered={false} style={tagStyle}>
      有效
    </Tag>
  )
}

/** 课程上下架状态：已上架绿色、已下架灰色、草稿橙色。 */
export function CourseStatusTag({ status }: { status: CourseStatus }) {
  if (status === 'published') {
    return (
      <Tag color="success" bordered={false} style={tagStyle}>
        已上架
      </Tag>
    )
  }
  if (status === 'draft') {
    return (
      <Tag color="orange" bordered={false} style={tagStyle}>
        草稿
      </Tag>
    )
  }
  return (
    <Tag bordered={false} style={tagStyle}>
      已下架
    </Tag>
  )
}

/** 预约状态：待完成琥珀色、已完成绿色、已过期红色。 */
export function AppointmentStatusTag({
  status
}: {
  status: AppointmentStatus
}) {
  if (status === 'completed') {
    return (
      <Tag color="success" bordered={false} style={tagStyle}>
        已完成
      </Tag>
    )
  }
  if (status === 'expired') {
    return (
      <Tag color="error" bordered={false} style={tagStyle}>
        已过期
      </Tag>
    )
  }
  return (
    <Tag color="warning" bordered={false} style={tagStyle}>
      待完成
    </Tag>
  )
}
