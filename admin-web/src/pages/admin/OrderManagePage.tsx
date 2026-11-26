import {
  useCallback,
  useEffect,
  useRef,
  useState
} from 'react'
import type { Dayjs } from 'dayjs'
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  DatePicker,
  Descriptions,
  Drawer,
  Form,
  Input,
  Row,
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
  fetchAdminOrders,
  type AdminOrderQueryParams
} from '../../api/adminApi'
import { getErrorMessage } from '../../api/request'
import AdminPageHeader from '../../components/admin/PageHeader'
import { OrderStatusTag } from '../../components/admin/StatusTags'
import type { AdminOrder, OrderStatus } from '../../types'
import {
  formatDateTime,
  formatMoney
} from '../../utils/format'
import { isValidMobile, parsePositiveInt } from '../../utils/validation'

const { RangePicker } = DatePicker

const INITIAL_QUERY: AdminOrderQueryParams = { page: 1, page_size: 20 }

const STATUS_OPTIONS: Array<{ label: string; value: OrderStatus }> = [
  { label: '待支付 pending', value: 'pending' },
  { label: '已支付 paid', value: 'paid' },
  { label: '已关闭 closed', value: 'closed' },
  { label: '已退款 refunded', value: 'refunded' }
]

interface OrderFilterValues {
  order_no?: string
  mobile?: string
  user_id?: string
  status?: OrderStatus
  range?: [Dayjs | null, Dayjs | null] | null
}

export default function OrderManagePage() {
  const [form] = Form.useForm<OrderFilterValues>()
  const [orders, setOrders] = useState<AdminOrder[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [query, setQuery] = useState<AdminOrderQueryParams>(INITIAL_QUERY)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filterError, setFilterError] = useState<string | null>(null)
  const [selectedOrder, setSelectedOrder] = useState<AdminOrder | null>(null)
  const requestSeq = useRef(0)

  const loadOrders = useCallback(async (params: AdminOrderQueryParams) => {
    const seq = requestSeq.current + 1
    requestSeq.current = seq
    setLoading(true)
    setError(null)
    try {
      const response = await fetchAdminOrders(params)
      if (seq !== requestSeq.current) {
        return
      }
      setOrders(response.items)
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
  }, [])

  useEffect(() => {
    void loadOrders(INITIAL_QUERY)
    return () => {
      requestSeq.current += 1
    }
  }, [loadOrders])

  const handleSearch = (values: OrderFilterValues) => {
    const params: AdminOrderQueryParams = { page: 1, page_size: pageSize }
    const orderNo = values.order_no?.trim() ?? ''
    const mobile = values.mobile?.trim() ?? ''

    if (orderNo) {
      params.order_no = orderNo
    }
    if (mobile) {
      if (!isValidMobile(mobile)) {
        setFilterError('手机号必须是 11 位中国大陆手机号')
        return
      }
      params.mobile = mobile
    }
    if (values.user_id?.trim()) {
      const userId = parsePositiveInt(values.user_id)
      if (!userId) {
        setFilterError('用户 ID 必须是正整数')
        return
      }
      params.user_id = userId
    }
    if (values.status) {
      params.status = values.status
    }
    const [from, to] = values.range ?? []
    if (from && to && from.isAfter(to)) {
      setFilterError('开始时间不能晚于结束时间')
      return
    }
    if (from) {
      params.created_from = from.format('YYYY-MM-DDTHH:mm:ss')
    }
    if (to) {
      params.created_to = to.format('YYYY-MM-DDTHH:mm:ss')
    }

    setFilterError(null)
    void loadOrders(params)
  }

  const handleReset = () => {
    form.resetFields()
    setFilterError(null)
    void loadOrders(INITIAL_QUERY)
  }

  const refresh = () => {
    void loadOrders({ ...query, page, page_size: pageSize })
  }

  const pagePaidCount = orders.filter((order) => order.status === 'paid').length
  const pagePendingCount = orders.filter(
    (order) => order.status === 'pending'
  ).length

  const columns: ColumnsType<AdminOrder> = [
    {
      title: '订单号',
      key: 'order_no',
      width: 260,
      render: (_value, order) => (
        <div onClick={(event) => event.stopPropagation()}>
          <Typography.Text
            copyable={{ text: order.order_no, tooltips: ['复制订单号', '已复制'] }}
            style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 11 }}
          >
            {order.order_no}
          </Typography.Text>
          <div style={{ fontSize: 11, color: '#a8a29e' }}>订单 #{order.id}</div>
        </div>
      )
    },
    {
      title: '用户',
      key: 'user',
      width: 170,
      render: (_value, order) => (
        <div>
          <Typography.Text style={{ fontSize: 13 }}>
            用户 #{order.user_id}
          </Typography.Text>
          <div style={{ fontSize: 11, color: '#a8a29e' }}>
            {order.user_mobile || '未绑定手机号'}
          </div>
        </div>
      )
    },
    {
      title: '课程',
      key: 'course',
      ellipsis: true,
      render: (_value, order) => (
        <div style={{ minWidth: 0 }}>
          <Tooltip title={order.course_title || `课程 #${order.course_id}`}>
            <Typography.Text
              ellipsis
              style={{ display: 'block', maxWidth: 260 }}
            >
              {order.course_title || '—'}
            </Typography.Text>
          </Tooltip>
          <div style={{ fontSize: 11, color: '#a8a29e' }}>
            课程 #{order.course_id}
          </div>
        </div>
      )
    },
    {
      title: '金额',
      dataIndex: 'amount',
      key: 'amount',
      width: 110,
      render: (value: number) => (
        <Typography.Text strong>{formatMoney(value)}</Typography.Text>
      )
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (status: OrderStatus) => <OrderStatusTag status={status} />
    },
    {
      title: '支付时间',
      dataIndex: 'paid_at',
      key: 'paid_at',
      width: 165,
      render: (value: string | null) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {formatDateTime(value)}
        </Typography.Text>
      )
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 165,
      render: (value: string) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {formatDateTime(value)}
        </Typography.Text>
      )
    }
  ]

  return (
    <div>
      <AdminPageHeader
        eyebrow="ORDERS"
        title="订单查询"
        description="订单仅由学员在小程序内通过微信支付产生。后台只做只读查询，不支持下单、支付、改价、修改状态或退款。"
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
        type="warning"
        showIcon
        className="mb-4"
        message="后台订单能力边界"
        description="订单状态由支付系统自动流转：待支付、已支付、已关闭（超时或微信侧关闭）与已退款（历史数据）。课程授权与学习进度由支付回调和学员行为产生，后台不提供补单或退款入口。"
      />

      <Card className="mb-4">
        <Form<OrderFilterValues>
          form={form}
          layout="vertical"
          initialValues={{ order_no: '', mobile: '' }}
          onFinish={handleSearch}
        >
          <Row gutter={[16, 12]} align="bottom">
            <Col xs={24} md={10} xl={8}>
              <Form.Item name="order_no" label="订单号">
                <Input
                  allowClear
                  placeholder="完整订单号（精确匹配）"
                  maxLength={64}
                  autoComplete="off"
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={10} xl={8}>
              <Form.Item name="mobile" label="用户手机号">
                <Input
                  allowClear
                  inputMode="numeric"
                  placeholder="已绑定手机号（精确匹配）"
                  maxLength={11}
                />
              </Form.Item>
            </Col>
            <Col xs={24} xl={8}>
              <Form.Item label=" " colon={false} style={{ marginBottom: 0 }}>
                <Space>
                  <Button type="primary" htmlType="submit" loading={loading}>
                    查询
                  </Button>
                  <Button onClick={handleReset}>重置</Button>
                </Space>
              </Form.Item>
            </Col>
          </Row>

          <Collapse
            ghost
            size="small"
            style={{ marginTop: 4 }}
            items={[
              {
                key: 'advanced',
                label: '高级筛选',
                children: (
                  <Row gutter={[16, 12]}>
                    <Col xs={24} md={8} xl={6}>
                      <Form.Item
                        name="user_id"
                        label="用户 ID"
                        style={{ marginBottom: 0 }}
                      >
                        <Input
                          allowClear
                          inputMode="numeric"
                          placeholder="正整数用户 ID"
                          maxLength={12}
                        />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={8} xl={6}>
                      <Form.Item
                        name="status"
                        label="订单状态"
                        style={{ marginBottom: 0 }}
                      >
                        <Select
                          allowClear
                          placeholder="全部状态"
                          options={STATUS_OPTIONS}
                        />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={8} xl={10}>
                      <Form.Item
                        name="range"
                        label="创建时间范围"
                        style={{ marginBottom: 0 }}
                      >
                        <RangePicker
                          showTime={{ format: 'HH:mm' }}
                          format="YYYY-MM-DD HH:mm"
                          style={{ width: '100%' }}
                        />
                      </Form.Item>
                    </Col>
                  </Row>
                )
              }
            ]}
          />
        </Form>

        <Typography.Text
          type="secondary"
          style={{ display: 'block', marginTop: 10, fontSize: 11 }}
        >
          时间筛选按服务器本地时间（MySQL DATETIME）。订单号、用户 ID、手机号均为精确匹配。
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
          message="订单查询失败"
          description={error}
          action={
            <Button size="small" onClick={refresh}>
              重试
            </Button>
          }
        />
      ) : null}

      <Card styles={{ body: { padding: 0 } }}>
        <Table<AdminOrder>
          rowKey="id"
          columns={columns}
          dataSource={orders}
          loading={loading}
          scroll={{ x: 1100 }}
          onRow={(order) => ({
            onClick: () => setSelectedOrder(order),
            style: { cursor: 'pointer' }
          })}
          title={() => (
            <Space size={10} wrap>
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                共 {total} 笔订单
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                当前页已支付 {pagePaidCount} · 待支付 {pagePendingCount}
              </Typography.Text>
            </Space>
          )}
          locale={{
            emptyText: loading ? '正在查询订单…' : '暂无符合条件的订单'
          }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: ['10', '20', '50'],
            showTotal: (count) => `共 ${count} 笔`,
            onChange: (nextPage, nextPageSize) =>
              void loadOrders({
                ...query,
                page: nextPage,
                page_size: nextPageSize
              })
          }}
        />
      </Card>

      <Typography.Paragraph
        type="secondary"
        style={{ marginTop: 14, fontSize: 11, lineHeight: '20px' }}
      >
        订单金额以分为单位存储、按元展示。后台不提供退款、关闭订单或补单能力；
        待支付订单超时关闭由支付侧处理。如遇异常订单，请通过后端运维手段核验
        微信支付回调记录。
      </Typography.Paragraph>

      <Drawer
        open={selectedOrder !== null}
        width={640}
        title="订单详情"
        onClose={() => setSelectedOrder(null)}
        extra={
          <Button size="small" onClick={() => setSelectedOrder(null)}>
            关闭
          </Button>
        }
      >
        {selectedOrder ? (
          <>
            <Descriptions
              bordered
              size="small"
              column={1}
              items={[
                {
                  key: 'order_no',
                  label: '订单号',
                  children: (
                    <Typography.Text
                      copyable
                      style={{
                        fontFamily:
                          'ui-monospace, SFMono-Regular, Menlo, monospace',
                        fontSize: 12
                      }}
                    >
                      {selectedOrder.order_no}
                    </Typography.Text>
                  )
                },
                {
                  key: 'id',
                  label: '订单记录 ID',
                  children: `#${selectedOrder.id}`
                },
                {
                  key: 'user',
                  label: '用户',
                  children: `用户 #${selectedOrder.user_id} · ${
                    selectedOrder.user_mobile || '未绑定手机号'
                  }`
                },
                {
                  key: 'course',
                  label: '课程',
                  children: `${
                    selectedOrder.course_title || '—'
                  }（#${selectedOrder.course_id}）`
                },
                {
                  key: 'appointment_quota',
                  label: '赠送指导预约',
                  children:
                    selectedOrder.appointment_quota_count > 0
                      ? `${selectedOrder.appointment_quota_count} 次`
                      : '无'
                },
                {
                  key: 'amount',
                  label: '订单金额',
                  children: (
                    <Typography.Text strong>
                      {formatMoney(selectedOrder.amount)}
                    </Typography.Text>
                  )
                },
                {
                  key: 'status',
                  label: '订单状态',
                  children: <OrderStatusTag status={selectedOrder.status} />
                },
                {
                  key: 'created',
                  label: '创建时间',
                  children: formatDateTime(selectedOrder.created_at)
                },
                {
                  key: 'paid',
                  label: '支付时间',
                  children: formatDateTime(selectedOrder.paid_at)
                }
              ]}
            />

            <Alert
              type="info"
              showIcon
              style={{ marginTop: 16 }}
              message="接口未下发的字段"
              description="后台订单接口不返回微信交易号、用户 openid 与支付回调原始报文。这些数据只保存在服务端支付回调日志中，前端与浏览器不会接触；如需核查，请通过后端运维日志按订单号检索。"
            />

            <Alert
              type="warning"
              showIcon
              style={{ marginTop: 12 }}
              message="只读页面"
              description={
                <>
                  后台不提供支付、退款、关闭订单或修改状态能力。
                  {selectedOrder.status === 'pending'
                    ? '待支付订单超过 30 分钟可由小程序侧或微信支付侧关闭。'
                    : '订单状态由支付回调自动流转。'}
                </>
              }
            />
          </>
        ) : null}
      </Drawer>
    </div>
  )
}
