import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import dayjs, { type Dayjs } from 'dayjs'
import {
  Alert,
  App as AntdApp,
  Avatar,
  Button,
  Card,
  Col,
  Collapse,
  DatePicker,
  Descriptions,
  Form,
  Input,
  Modal,
  Radio,
  Row,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  GiftOutlined,
  ReloadOutlined,
  UserOutlined
} from '@ant-design/icons'

import AdminCourseSelect from '../../components/admin/CourseSelect'
import AdminPageHeader from '../../components/admin/PageHeader'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  clearGrantFeedback,
  fetchGiftLogs,
  grantGift,
  selectGift
} from '../../store/slices/giftSlice'
import type { GiftLog, GiftLogFilters, GiftValidity } from '../../types'
import { formatDateTime } from '../../utils/format'
import { isValidMobile, parsePositiveInt } from '../../utils/validation'

const { RangePicker } = DatePicker

interface GiftFilterValues {
  mobile?: string
  courseId?: number | null
  range?: [Dayjs | null, Dayjs | null] | null
}

interface GiftFormValues {
  mobile: string
  courseId: number
  validity: GiftValidity
}

/** 展示「当前时间 + 1 年」的预计到期日，实际以服务端 UTC 起算为准。 */
function oneYearLaterDate(): string {
  return dayjs().add(1, 'year').format('YYYY-MM-DD')
}

export default function GiftManagePage() {
  const dispatch = useAppDispatch()
  const { message } = AntdApp.useApp()
  const [searchParams] = useSearchParams()
  const courseParam = searchParams.get('courseId')
  const initialCourseId = courseParam ? parsePositiveInt(courseParam) : null

  const {
    logs,
    total,
    page,
    pageSize,
    filters,
    loading,
    error,
    granting,
    grantError
  } = useAppSelector(selectGift)

  const [filterForm] = Form.useForm<GiftFilterValues>()
  const [giftForm] = Form.useForm<GiftFormValues>()
  const [adminIdInput, setAdminIdInput] = useState('')
  const [giftOpen, setGiftOpen] = useState(false)
  const validity = Form.useWatch('validity', giftForm) ?? 'one_year'

  const loadLogs = (
    nextPage = 1,
    nextPageSize = pageSize,
    nextFilters: GiftLogFilters = {}
  ) => {
    void dispatch(
      fetchGiftLogs({
        page: nextPage,
        pageSize: nextPageSize,
        filters: nextFilters
      })
    )
  }

  useEffect(() => {
    loadLogs(1, 20, {})
    // 首次进入加载默认日志。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dispatch])

  const handleSearch = (values: GiftFilterValues) => {
    const nextFilters: GiftLogFilters = {}
    const mobile = values.mobile?.trim() ?? ''

    if (mobile) {
      if (!isValidMobile(mobile)) {
        message.warning('日志筛选手机号必须是 11 位中国大陆手机号')
        return
      }
      nextFilters.mobile = mobile
    }
    if (values.courseId) {
      nextFilters.course_id = values.courseId
    }
    if (adminIdInput.trim()) {
      const adminId = parsePositiveInt(adminIdInput)
      if (!adminId) {
        message.warning('管理员 ID 必须是正整数')
        return
      }
      nextFilters.admin_id = adminId
    }
    const [from, to] = values.range ?? []
    if (from && to) {
      if (from.isAfter(to, 'day')) {
        message.warning('开始日期不能晚于结束日期')
        return
      }
      nextFilters.created_from = `${from.format('YYYY-MM-DD')}T00:00:00`
      nextFilters.created_to = `${to.format('YYYY-MM-DD')}T23:59:59`
    }
    loadLogs(1, pageSize, nextFilters)
  }

  const handleReset = () => {
    filterForm.resetFields()
    setAdminIdInput('')
    loadLogs(1, pageSize, {})
  }

  const openGiftModal = () => {
    dispatch(clearGrantFeedback())
    setGiftOpen(true)
  }

  useEffect(() => {
    if (!giftOpen) {
      return
    }
    giftForm.setFieldsValue({
      mobile: '',
      courseId: initialCourseId ?? undefined,
      validity: 'one_year'
    })
  }, [giftOpen, initialCourseId, giftForm])

  const handleGrant = async (values: GiftFormValues) => {
    const mobile = values.mobile.trim()
    if (!values.courseId) {
      return
    }
    try {
      const result = await dispatch(
        grantGift({
          mobile,
          course_id: values.courseId,
          validity: values.validity
        })
      ).unwrap()

      setGiftOpen(false)
      if (result.gifted) {
        message.success(
          `赠课成功：手机号 ${result.mobile} 已获得课程 #${result.course_id}`
        )
      } else {
        message.info('该用户已拥有该课程，本次为幂等请求，未重复发放')
      }

      // 成功后自动把日志筛选定位到该手机号 + 课程，便于核对本次结果。
      filterForm.setFieldsValue({
        mobile: result.mobile,
        courseId: result.course_id
      })
      filterForm.resetFields(['range'])
      setAdminIdInput('')
      loadLogs(1, pageSize, {
        mobile: result.mobile,
        course_id: result.course_id
      })
    } catch {
      // 失败详情使用弹窗内 grantError Alert 持续展示。
    }
  }

  const handlePageChange = (nextPage: number, nextPageSize: number) => {
    loadLogs(nextPage, nextPageSize, filters)
  }

  const columns: ColumnsType<GiftLog> = [
    {
      title: '领取用户',
      key: 'receiver',
      width: 240,
      render: (_value, log) => (
        <Space size={10}>
          <Avatar
            shape="square"
            size={36}
            icon={<UserOutlined />}
            style={{ background: '#f4f1ea', color: '#a47436' }}
          />
          <div style={{ minWidth: 0 }}>
            <Typography.Text
              strong
              copyable={{ text: log.mobile }}
              style={{ fontSize: 13 }}
            >
              {log.mobile}
            </Typography.Text>
            <div style={{ fontSize: 11, color: '#a8a29e' }}>
              赠课日志未返回昵称与头像
            </div>
          </div>
        </Space>
      )
    },
    {
      title: '课程',
      key: 'course',
      ellipsis: true,
      render: (_value, log) => (
        <div style={{ minWidth: 0 }}>
          <Tooltip title={log.course_title || `课程 #${log.course_id}`}>
            <Typography.Text
              ellipsis
              style={{ display: 'block', maxWidth: 280 }}
            >
              {log.course_title || '—'}
            </Typography.Text>
          </Tooltip>
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            课程 #{log.course_id}
          </Typography.Text>
        </div>
      )
    },
    {
      title: '有效期',
      key: 'validity',
      width: 150,
      render: () => (
        <Tooltip title="赠课日志接口未返回有效期；可在「用户课程管理」按手机号查看当前授权">
          <Tag bordered={false} style={{ borderRadius: 999 }}>
            以用户课程为准
          </Tag>
        </Tooltip>
      )
    },
    {
      title: '操作管理员',
      key: 'admin',
      width: 180,
      render: (_value, log) => (
        <div>
          <Typography.Text style={{ fontSize: 13 }}>
            {log.admin_username || '—'}
          </Typography.Text>
          <div style={{ fontSize: 11, color: '#a8a29e' }}>
            管理员 #{log.admin_id}
          </div>
        </div>
      )
    },
    {
      title: '发放时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (value: string) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {formatDateTime(value)}
        </Typography.Text>
      )
    },
    {
      title: '日志 ID',
      dataIndex: 'id',
      key: 'id',
      width: 90,
      render: (value: number) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          #{value}
        </Typography.Text>
      )
    }
  ]

  return (
    <div>
      <AdminPageHeader
        eyebrow="GIFTS"
        title="赠课管理"
        description="按手机号向已绑定用户发放整门课程。赠课只依赖手机号匹配；同一手机号 + 课程重复提交为幂等请求，不重复发放、不新增日志。"
        extra={
          <>
            <Button
              type="primary"
              icon={<GiftOutlined />}
              onClick={openGiftModal}
            >
              赠送课程
            </Button>
            <Button
              icon={<ReloadOutlined />}
              loading={loading}
              onClick={() => loadLogs(page, pageSize, filters)}
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
        message="后台赠课不会短信通知用户；用户下次进入小程序即可看到课程。赠课日志只记录手机号、课程、操作管理员与时间，接口不返回昵称、头像、天数与到期日。"
      />

      <Card className="mb-4">
        <Form<GiftFilterValues>
          form={filterForm}
          layout="vertical"
          initialValues={{ mobile: '', courseId: null, range: null }}
          onFinish={handleSearch}
        >
          <Row gutter={[16, 0]}>
            <Col xs={24} sm={12} lg={6}>
              <Form.Item name="mobile" label="手机号">
                <Input
                  allowClear
                  placeholder="输入完整手机号"
                  maxLength={11}
                />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} lg={8}>
              <Form.Item name="courseId" label="课程">
                <AdminCourseSelect allowClear placeholder="全部课程" />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} lg={7}>
              <Form.Item name="range" label="赠送时间">
                <RangePicker allowEmpty={[true, true]} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} lg={3}>
              <Form.Item label=" " colon={false}>
                <Space>
                  <Button type="primary" htmlType="submit" loading={loading}>
                    查询
                  </Button>
                  <Button onClick={handleReset}>重置</Button>
                </Space>
              </Form.Item>
            </Col>
          </Row>
        </Form>

        <Collapse
          ghost
          size="small"
          style={{ marginTop: 8 }}
          items={[
            {
              key: 'advanced',
              label: '高级筛选',
              children: (
                <div style={{ maxWidth: 300 }}>
                  <Typography.Text
                    type="secondary"
                    style={{ display: 'block', marginBottom: 4, fontSize: 12 }}
                  >
                    管理员 ID
                  </Typography.Text>
                  <Input
                    allowClear
                    placeholder="可选，按操作管理员筛选"
                    inputMode="numeric"
                    maxLength={12}
                    value={adminIdInput}
                    onChange={(event) =>
                      setAdminIdInput(event.target.value.replace(/\D/g, ''))
                    }
                    onPressEnter={() => filterForm.submit()}
                  />
                </div>
              )
            }
          ]}
        />
      </Card>

      {error ? (
        <Alert
          type="error"
          showIcon
          className="mb-4"
          message="赠课日志查询失败"
          description={error}
          action={
            <Button size="small" onClick={() => loadLogs(page, pageSize, filters)}>
              重试
            </Button>
          }
        />
      ) : null}

      <Card styles={{ body: { padding: 0 } }}>
        <Table<GiftLog>
          rowKey="id"
          columns={columns}
          dataSource={logs}
          loading={loading}
          scroll={{ x: 1000 }}
          title={() => (
            <Space size={8} wrap>
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                赠课日志 · 共 {total} 条
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                只读留痕，点击行首箭头展开完整字段
              </Typography.Text>
            </Space>
          )}
          expandable={{
            expandedRowRender: (log) => (
              <Descriptions
                size="small"
                column={3}
                items={[
                  {
                    key: 'log',
                    label: '日志 ID',
                    children: `#${log.id}`
                  },
                  {
                    key: 'mobile',
                    label: '手机号',
                    children: log.mobile
                  },
                  {
                    key: 'course',
                    label: '课程',
                    children: log.course_title
                      ? `${log.course_title}（#${log.course_id}）`
                      : `#${log.course_id}`
                  },
                  {
                    key: 'admin',
                    label: '操作管理员',
                    children: log.admin_username
                      ? `${log.admin_username}（#${log.admin_id}）`
                      : `#${log.admin_id}`
                  },
                  {
                    key: 'created',
                    label: '发放时间',
                    children: formatDateTime(log.created_at)
                  },
                  {
                    key: 'note',
                    label: '说明',
                    children: '仅记录真实新增授权的赠课操作'
                  }
                ]}
              />
            )
          }}
          locale={{
            emptyText: loading
              ? '正在查询赠课日志…'
              : '暂无符合条件的赠课日志'
          }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: ['10', '20', '50'],
            showTotal: (count) => `共 ${count} 条`,
            onChange: handlePageChange
          }}
        />
      </Card>

      <Modal
        open={giftOpen}
        title="赠送课程"
        width={580}
        okText="确认赠课"
        cancelText="取消"
        confirmLoading={granting}
        onOk={() => giftForm.submit()}
        onCancel={() => {
          if (!granting) {
            setGiftOpen(false)
          }
        }}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          className="mb-4"
          message="幂等规则"
          description="同一手机号 + 同一课程只保留一条授权。若用户已拥有该课程，本次提交不会重复发放，也不会新增日志；只有真实新增授权时才写入赠课日志。"
        />

        {grantError ? (
          <Alert
            type="error"
            showIcon
            className="mb-4"
            message="赠课失败"
            description={grantError}
          />
        ) : null}

        <Form<GiftFormValues>
          form={giftForm}
          layout="vertical"
          initialValues={{ mobile: '', validity: 'one_year' }}
          onFinish={(values) => void handleGrant(values)}
          onValuesChange={() => {
            if (grantError) {
              dispatch(clearGrantFeedback())
            }
          }}
          preserve={false}
        >
          <Form.Item
            name="mobile"
            label="用户手机号"
            normalize={(value: string) => (value ?? '').replace(/\D/g, '')}
            rules={[
              { required: true, whitespace: true, message: '请输入用户手机号' },
              {
                validator: (_rule, value: string) =>
                  !value || isValidMobile(value)
                    ? Promise.resolve()
                    : Promise.reject(new Error('请输入 11 位中国大陆手机号'))
              }
            ]}
            extra="仅匹配已通过微信授权绑定手机号的用户；未绑定用户无法被赠课。"
          >
            <Input
              inputMode="numeric"
              maxLength={11}
              placeholder="请输入 11 位手机号"
              disabled={granting}
            />
          </Form.Item>

          <Form.Item
            name="courseId"
            label="赠送课程"
            rules={[{ required: true, message: '请选择要赠送的课程' }]}
            extra="课程 ID 与手机号共同构成幂等键。"
          >
            <AdminCourseSelect disabled={granting} />
          </Form.Item>

          <Form.Item
            name="validity"
            label="赠送后有效期"
            rules={[{ required: true, message: '请选择有效期' }]}
          >
            <Radio.Group disabled={granting}>
              <Space direction="vertical" size={8}>
                <Radio value="one_year">
                  一年有效期
                  <Typography.Text
                    type="secondary"
                    style={{ marginLeft: 8, fontSize: 12 }}
                  >
                    从赠课操作时间起算，预计到期 {oneYearLaterDate()}
                  </Typography.Text>
                </Radio>
                <Radio value="permanent">
                  永久有效
                  <Typography.Text
                    type="secondary"
                    style={{ marginLeft: 8, fontSize: 12 }}
                  >
                    不受时间限制
                  </Typography.Text>
                </Radio>
              </Space>
            </Radio.Group>
          </Form.Item>

          <Alert
            type={validity === 'permanent' ? 'warning' : 'info'}
            showIcon
            style={{ marginTop: 4 }}
            message={
              validity === 'permanent'
                ? '永久有效仅表示没有到期时间；收回权限仍需在「用户课程管理」中操作。'
                : '一年有效期以后端 UTC 时间 +1 年计算，页面日期为 Asia/Shanghai 的预估。'
            }
          />
        </Form>
      </Modal>
    </div>
  )
}
