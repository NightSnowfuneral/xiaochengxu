import type { ReactNode } from 'react'
import { Flex, Typography } from 'antd'

interface AdminPageHeaderProps {
  title: string
  description?: ReactNode
  extra?: ReactNode
  eyebrow?: string
}

/** 页面统一标题区：标题 + 说明 + 右侧操作按钮。 */
export default function AdminPageHeader({
  title,
  description,
  extra,
  eyebrow
}: AdminPageHeaderProps) {
  return (
    <Flex
      className="mb-5"
      justify="space-between"
      align="flex-start"
      gap={16}
      wrap
    >
      <div className="min-w-0">
        {eyebrow ? (
          <Typography.Text
            style={{
              display: 'block',
              marginBottom: 4,
              color: '#a47436',
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: '0.18em',
              textTransform: 'uppercase'
            }}
          >
            {eyebrow}
          </Typography.Text>
        ) : null}
        <Typography.Title level={3} style={{ margin: 0 }}>
          {title}
        </Typography.Title>
        {description ? (
          <Typography.Paragraph
            type="secondary"
            style={{ margin: '6px 0 0', maxWidth: 860, fontSize: 13 }}
          >
            {description}
          </Typography.Paragraph>
        ) : null}
      </div>

      {extra ? (
        <Flex gap={8} wrap align="center">
          {extra}
        </Flex>
      ) : null}
    </Flex>
  )
}
