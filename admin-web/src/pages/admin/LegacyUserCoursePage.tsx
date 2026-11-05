import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ReloadOutlined } from '@ant-design/icons'

import {
  fetchAdminUserCourses
} from '../../api/adminApi'
import { getErrorMessage } from '../../api/request'
import AdminCourseSelect from '../../components/admin/CourseSelect'
import AdminPageHeader from '../../components/admin/PageHeader'
import type {
  AdminUserCourse,
  AdminUserCourseQueryParams,
  UserCourseValidityStatus
} from '../../types'
import {
  formatShanghaiDateRange,
  formatShanghaiDateTime
} from '../../utils/format'
import { isValidMobile } from '../../utils/validation'

const INITIAL_QUERY: AdminUserCourseQueryParams = { page: 1, page_size: 20 }

const STATUS_OPTIONS: Array<{
  label: string
  value: UserCourseValidityStatus
}> = [
  { label: '有效', value: 'valid' },
  { label: '已过期', value: 'expired' },
  { label: '永久有效', value: 'permanent' }
]

interface LegacyFilterValues {
  mobile?: string
  courseId?: number | null
  status?: UserCourseValidityStatus
}

function LegacyStatusTag({ status }: { status: UserCourseValidityStatus }) {
  if (status === 'expired') {
    return (
      <Tag color="error" bordered={false} style={{ borderRadius: 999 }}>
        已过期
      </Tag>
    )
  }
  if (status === 'permanent') {
    return (
      <Tag bordered={false} style={{ borderRadius: 999 }}>
        永久有效
      </Tag>
    )
  }
  return (
    <Tag color="success" bordered={false} style={{ borderRadius: 999 }}>
      有效
    </Tag>
  )
}

export default function LegacyUserCoursePage() {
  const [form] = Form.useForm<LegacyFilterValues>()
  const [items, setItems] = useState<AdminUserCourse[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [query, setQuery] = useState<AdminUserCourseQueryParams>(INITIAL_QUERY)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filterError, setFilterError] = useState<string | null>(null)
  const requestSeq = useRef(0)

  const loadUserCourses = useCallback(
    async (params: AdminUserCourseQueryParams) => {
      const seq = requestSeq.current + 1
      requestSeq.current = seq
      setLoading(true)
      setError(null)
      try {
        const response = await fetchAdminUserCourses(params)
        if (seq !== requestSeq.current) {
          return
        }
        setItems(response.items)
        setTotal(response.total)
        setPage(response.page)
        setPageSize(response.page_size)
        setQuery(params)
      } catch (loadError) {
        if (seq !== requestSeq.current) {
          return
        }
        setError(getErrorMessage(loadError))
      } finally {
        if (seq === requestSeq.current) {
          setLoading(false)
        }
      }
    },
    []
  )

  useEffect(() => {
    void loadUserCourses(INITIAL_QUERY)
    return () => {
      requestSeq.current += 1
    }
  }, [loadUserCourses])

  const handleSearch = (values: LegacyFilterValues) => {
    const params: AdminUserCourseQueryParams = {
      page: 1,
      page_size: pageSize
    }
    const mobile = values.mobile?.trim() ?? ''
    if (mobile) {
      if (!isValidMobile(mobile)) {
        setFilterError('手机号必须是 11 位中国大陆手机号')
        return
      }
      params.mobile = mobile
    }
    if (values.courseId) {
      params.course_id = values.courseId
    }
    if (values.status) {
      params.status = values.status
    }
    setFilterError(null)
    void loadUserCourses(params)
  }

  const handleReset = () => {
    form.resetFields()
    setFilterError(null)
    void loadUserCourses(INITIAL_QUERY)
  }

  const refresh = () => {
    void loadUserCourses({ ...query, page, page_size: pageSize })
  }

  const columns: ColumnsType<AdminUserCourse> = [
    {
      title: '用户',
      key: 'user',
      width: 180,
      render: (_value, item) => (
        <div>
          <Typography.Text style={{ fontSize: 13 }}>
            用户 #{item.user_id}
          </Typography.Text>
          <div style={{ fontSize: 11, color: '#a8a29e' }}>
            {item.user_mobile || '未绑定手机号'}
          </div>
        </div>
      )
    },
    {
      title: '课程',
      key: 'course',
      ellipsis: true,
      render: (_value, item) => (
        <div style={{ minWidth: 0 }}>
          <Tooltip title={item.course_title || `课程 #${item.course_id}`}>
            <Typography.Text
              ellipsis
              style={{ display: 'block', maxWidth: 300 }}
            >
              {item.course_title || '—'}
            </Typography.Text>
          </Tooltip>
          <div style={{ fontSize: 11, color: '#a8a29e' }}>
            课程 #{item.course_id}
          </div>
        </div>
      )
    },
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      width: 90,
      render: (source: AdminUserCourse['source']) =>
        source === 'buy' ? (
          <Tag color="processing" bordered={false} style={{ borderRadius: 999 }}>
            购买
          </Tag>
        ) : (
          <Tag color="gold" bordered={false} style={{ borderRadius: 999 }}>
            赠课
          </Tag>
        )
    },
    {
      title: '有效期',
      key: 'validity',
      width: 270,
      render: (_value, item) => (
        <Typography.Text style={{ fontSize: 12, color: '#57534e' }}>
          {formatShanghaiDateRange(item.valid_start_at, item.valid_end_at)}
        </Typography.Text>
      )
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (status: UserCourseValidityStatus) => (
        <LegacyStatusTag status={status} />
      )
    },
    {
      title: '授权时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (value: string) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {formatShanghaiDateTime(value)}
        </Typography.Text>
      )
    }
  ]

  return (
    <div>
      <AdminPageHeader
        eyebrow="ACCESS · LEGACY"
        title="用户课程（兼容只读）"
        description="保留旧链接的只读查询页面，不在导航中展示。赠课、重置有效期与收回授权请前往「用户课程管理」。"
        extra={
          <>
            <Tag bordered={false} style={{ borderRadius: 999, marginInlineEnd: 0 }}>
              只读
            </Tag>
            <Button
              icon={<ReloadOutlined />}
              loading={loading}
              onClick={refresh}
            >
              刷新
            </Button>
          </>
        }
      />

      <Alert
        type="info"
        showIcon
        className="mb-4"
        message="兼容页面"
        description="本页仅按授权记录扁平查询，不支持按用户聚合查看、修改有效期、补发授权或收回权限。所有写操作请使用导航中的「用户课程管理」。有效期以 UTC 存储，本页按 Asia/Shanghai 展示。"
      />

      <Card className="mb-4">
        <Form<LegacyFilterValues>
          form={form}
          layout="inline"
          initialValues={{ mobile: '', courseId: null, status: undefined }}
          onFinish={handleSearch}
          style={{ rowGap: 12 }}
        >
          <Form.Item name="mobile" label="用户手机号">
            <Input
              allowClear
              inputMode="numeric"
              maxLength={11}
              placeholder="已绑定手机号"
              style={{ width: 180 }}
            />
          </Form.Item>
          <Form.Item name="courseId" label="课程">
            <div style={{ width: 300 }}>
              <AdminCourseSelect allowClear placeholder="全部课程" />
            </div>
          </Form.Item>
          <Form.Item name="status" label="授权状态">
            <Select
              allowClear
              placeholder="全部状态"
              options={STATUS_OPTIONS}
              style={{ width: 140 }}
            />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={loading}>
                查询
              </Button>
              <Button onClick={handleReset}>重置</Button>
            </Space>
          </Form.Item>
        </Form>

        <Typography.Text
          type="secondary"
          style={{ display: 'block', marginTop: 10, fontSize: 11 }}
        >
          手机号与课程均为精确匹配，状态由服务端按当前 UTC 时间计算。
        </Typography.Text>

        {filterError ? (
          <Alert
            type="error"
            showIcon
            style={{ marginTop: 10 }}
            message={filterError}
          />
        ) : null}
      </Card>

      {error ? (
        <Alert
          type="error"
          showIcon
          className="mb-4"
          message="用户课程查询失败"
          description={error}
          action={
            <Button size="small" onClick={refresh}>
              重试
            </Button>
          }
        />
      ) : null}

      <Card styles={{ body: { padding: 0 } }}>
        <Table<AdminUserCourse>
          rowKey="id"
          columns={columns}
          dataSource={items}
          loading={loading}
          scroll={{ x: 1000 }}
          title={() => (
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              共 {total} 条授权记录
            </Typography.Text>
          )}
          locale={{
            emptyText: loading ? '正在查询授权记录…' : '暂无符合条件的授权记录'
          }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: ['10', '20', '50'],
            showTotal: (count) => `共 ${count} 条`,
            onChange: (nextPage, nextPageSize) =>
              void loadUserCourses({
                ...query,
                page: nextPage,
                page_size: nextPageSize
              })
          }}
        />
      </Card>
    </div>
  )
}
