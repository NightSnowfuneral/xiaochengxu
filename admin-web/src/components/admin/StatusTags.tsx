import { Tag } from 'antd'

import type {
  AdminUserCourseItem,
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
