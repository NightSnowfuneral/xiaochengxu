import {
  useCallback,
  useEffect,
  useRef,
  useState
} from 'react'
import {
  Alert,
  App as AntdApp,
  Avatar,
  Button,
  Card,
  Empty,
  Form,
  Image,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  GiftOutlined,
  ReloadOutlined,
  SearchOutlined
} from '@ant-design/icons'

import { getErrorMessage } from '../../api/request'
import {
  fetchAdminUserCoursesByUser,
  grantAdminUserCourse,
  lookupAdminUser,
  revokeAdminUserCourse
} from '../../api/userCourseAdminApi'
import AdminCourseSelect from '../../components/admin/CourseSelect'
import AdminPageHeader from '../../components/admin/PageHeader'
import { UserCourseStatusTag } from '../../components/admin/StatusTags'
import type {
  AdminUserCourseItem,
  AdminUserSummary
} from '../../types'
import {
  formatNumber,
  formatShanghaiDate,
  formatShanghaiDateTime
} from '../../utils/format'
import { isValidMobile, parsePositiveInt } from '../../utils/validation'

const DEFAULT_PAGE_SIZE = 20
const DEFAULT_VALID_DAYS = 365
const MAX_VALID_DAYS = 36500

const COVER_FALLBACK =
  'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI3NiIgaGVpZ2h0PSI0OCI+PHJlY3Qgd2lkdGg9Ijc2IiBoZWlnaHQ9IjQ4IiBmaWxsPSIjZjVmNWY0Ii8+PC9zdmc+'

interface ResetFormValues {
  courseId?: number | null
  valid_days: number | null
}

function userInitial(user: AdminUserSummary): string {
  return user.nickname?.trim().slice(0, 1) || '用'
}

/** 前端预览：现在 + N 天，按 Asia/Shanghai 展示日期。 */
function previewExpireDate(days: number | null | undefined): string {
  if (!days || !Number.isInteger(days) || days < 1 || days > MAX_VALID_DAYS) {
    return '—'
  }
  return formatShanghaiDate(
    new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString()
  )
}

export default function UserCourseManagePage() {
  const { message } = AntdApp.useApp()
  const [keyword, setKeyword] = useState('')
  const [user, setUser] = useState<AdminUserSummary | null>(null)
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)

  const [items, setItems] = useState<AdminUserCourseItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [listLoading, setListLoading] = useState(false)
  const [listError, setListError] = useState<string | null>(null)
  const requestSeq = useRef(0)

  const [modalOpen, setModalOpen] = useState(false)
  const [presetCourse, setPresetCourse] =
    useState<AdminUserCourseItem | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [modalError, setModalError] = useState<string | null>(null)
  const [revokingCourseId, setRevokingCourseId] = useState<number | null>(null)
  const [form] = Form.useForm<ResetFormValues>()
  const validDays = Form.useWatch('valid_days', form) ?? DEFAULT_VALID_DAYS

  useEffect(() => {
    return () => {
      requestSeq.current += 1
    }
  }, [])

  const loadCourses = useCallback(
    async (userId: number, nextPage: number, nextPageSize: number) => {
      const seq = requestSeq.current + 1
      requestSeq.current = seq
      setListLoading(true)
      setListError(null)
      try {
        const response = await fetchAdminUserCoursesByUser(
          userId,
          nextPage,
          nextPageSize
        )
        if (seq !== requestSeq.current) {
          return
        }
        setItems(response.items)
        setTotal(response.total)
        setPage(response.page)
        setPageSize(response.page_size)
      } catch (loadError) {
        if (seq !== requestSeq.current) {
          return
        }
        setListError(getErrorMessage(loadError))
      } finally {
        if (seq === requestSeq.current) {
          setListLoading(false)
        }
      }
    },
    []
  )

  const runSearch = async (rawValue?: string) => {
    const value = (rawValue ?? keyword).trim()
    const userId = parsePositiveInt(value)
    const mobile = isValidMobile(value)

    if (!value) {
      setSearchError('请输入手机号或用户 ID')
      return
    }
    if (!mobile && !userId) {
      setSearchError('请输入 11 位手机号或正整数用户 ID')
      return
    }

    setSearching(true)
    setSearchError(null)
    setListError(null)
    try {
      const found = await lookupAdminUser(value)
      setUser(found)
      setItems([])
      setTotal(0)
      setPage(1)
      await loadCourses(found.user_id, 1, pageSize)
    } catch (lookupError) {
      setUser(null)
      setItems([])
      setTotal(0)
      setSearchError(getErrorMessage(lookupError))
    } finally {
      setSearching(false)
    }
  }

  const refreshCurrentPage = () => {
    if (!user) {
      return
    }
    void loadCourses(user.user_id, page, pageSize)
  }

  const openGiftModal = () => {
    if (!user) {
      return
    }
    setPresetCourse(null)
    setModalError(null)
    setModalOpen(true)
  }

  const openResetModal = (item: AdminUserCourseItem) => {
    setPresetCourse(item)
    setModalError(null)
    setModalOpen(true)
  }

  useEffect(() => {
    if (!modalOpen) {
      return
    }
    form.setFieldsValue({
      courseId: presetCourse?.course_id ?? null,
      valid_days: DEFAULT_VALID_DAYS
    })
  }, [modalOpen, presetCourse, form])

  const closeModal = () => {
    if (!submitting) {
      setModalOpen(false)
      setModalError(null)
    }
  }

  const handleSubmit = async (values: ResetFormValues) => {
    if (!user) {
      return
    }
    const courseId = presetCourse?.course_id ?? values.courseId
    if (!courseId) {
      setModalError('请选择要赠送的课程')
      return
    }
    if (
      !values.valid_days ||
      !Number.isInteger(values.valid_days) ||
      values.valid_days < 1 ||
      values.valid_days > MAX_VALID_DAYS
    ) {
      setModalError(`有效天数需为 1-${MAX_VALID_DAYS} 的整数`)
      return
    }

    setSubmitting(true)
    setModalError(null)
    try {
      const result = await grantAdminUserCourse({
        user_id: user.user_id,
        course_id: courseId,
        valid_days: values.valid_days
      })
      setModalOpen(false)
      message.success(
        `${result.message}，有效期至 ${formatShanghaiDateTime(result.expire_time)}`
      )
      await loadCourses(user.user_id, page, pageSize)
    } catch (grantFailure) {
      setModalError(getErrorMessage(grantFailure))
    } finally {
      setSubmitting(false)
    }
  }

  const handleRevoke = async (item: AdminUserCourseItem) => {
    if (!user || revokingCourseId !== null) {
      return
    }
    setRevokingCourseId(item.course_id)
    try {
      const result = await revokeAdminUserCourse({
        user_id: user.user_id,
        course_id: item.course_id
      })
      const nextPage = items.length === 1 && page > 1 ? page - 1 : page
      message.success(result.message)
      await loadCourses(user.user_id, nextPage, pageSize)
    } catch (revokeFailure) {
      message.error(getErrorMessage(revokeFailure))
    } finally {
      setRevokingCourseId(null)
    }
  }

  const columns: ColumnsType<AdminUserCourseItem> = [
    {
      title: '封面',
      key: 'cover',
      width: 100,
      render: (_value, item) =>
        item.course_cover ? (
          <Image
            src={item.course_cover}
            alt={`${item.course_title}封面`}
            width={76}
            height={48}
            preview={false}
            style={{ objectFit: 'cover', borderRadius: 8 }}
            fallback={COVER_FALLBACK}
          />
        ) : (
          <div
            style={{
              display: 'flex',
              width: 76,
              height: 48,
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: 8,
              background: '#f5f5f4',
              color: '#a8a29e',
              fontSize: 11
            }}
          >
            暂无封面
          </div>
        )
    },
    {
      title: '课程名称',
      key: 'course',
      ellipsis: true,
      render: (_value, item) => (
        <div style={{ minWidth: 0 }}>
          <Typography.Text
            strong
            ellipsis
            style={{ display: 'block', maxWidth: 320 }}
          >
            {item.course_title}
          </Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            课程 #{item.course_id}
          </Typography.Text>
        </div>
      )
    },
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      width: 100,
      render: (source: AdminUserCourseItem['source']) =>
        source === 'purchase' ? (
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
      title: '有效期至',
      dataIndex: 'expire_time',
      key: 'expire_time',
      width: 180,
      render: (value: string | null) => (
        <Typography.Text
          style={{ fontSize: 12, color: value ? '#57534e' : '#78716c' }}
        >
          {value ? formatShanghaiDateTime(value) : '永久有效'}
        </Typography.Text>
      )
    },
    {
      title: '状态',
      key: 'status',
      width: 110,
      render: (_value, item) => <UserCourseStatusTag item={item} />
    },
    {
      title: '操作',
      key: 'actions',
      width: 190,
      fixed: 'right',
      render: (_value, item) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            onClick={() => openResetModal(item)}
          >
            重置有效期
          </Button>
          <Popconfirm
            title="收回课程授权？"
            description="收回后用户将无法观看该课程。购买来源的收回不会产生退款；操作会写入日志。"
            okText="确认收回"
            cancelText="取消"
            okButtonProps={{
              danger: true,
              loading: revokingCourseId === item.course_id
            }}
            onConfirm={() => handleRevoke(item)}
          >
            <Button
              type="link"
              size="small"
              danger
              disabled={revokingCourseId !== null}
            >
              收回
            </Button>
          </Popconfirm>
        </Space>
      )
    }
  ]

  return (
    <div>
      <AdminPageHeader
        eyebrow="USER COURSES"
        title="用户课程管理"
        description="按手机号或用户 ID 精确查找用户，查看已拥有课程，赠送课程或重置有效期，也可收回授权。同一用户 + 课程始终只有一条授权记录。"
        extra={
          user ? (
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
                loading={listLoading}
                onClick={refreshCurrentPage}
              >
                刷新
              </Button>
            </>
          ) : null
        }
      />

      <Card className="mb-4">
        <div style={{ maxWidth: 640 }}>
          <Input.Search
            value={keyword}
            onChange={(event) => {
              setKeyword(event.target.value)
              setSearchError(null)
            }}
            onSearch={(value) => void runSearch(value)}
            placeholder="输入 11 位手机号或用户 ID，回车搜索"
            maxLength={64}
            size="large"
            loading={searching}
            enterButton={
              <>
                <SearchOutlined /> 搜索用户
              </>
            }
            allowClear
            disabled={searching}
          />
          <Typography.Text
            type="secondary"
            style={{ display: 'block', marginTop: 8, fontSize: 12 }}
          >
            精确匹配：手机号对应多个用户时请改用用户 ID。
          </Typography.Text>
        </div>

        {searchError ? (
          <Alert
            type="error"
            showIcon
            style={{ marginTop: 14 }}
            message="未找到用户"
            description={searchError}
          />
        ) : null}
      </Card>

      {user ? (
        <Card className="mb-4" styles={{ body: { padding: '18px 20px' } }}>
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              alignItems: 'center',
              gap: 16
            }}
          >
            <Avatar
              size={64}
              src={user.avatar_url || undefined}
              style={{
                flexShrink: 0,
                background: '#0d1526',
                color: '#dbbd7d',
                fontSize: 22
              }}
            >
              {userInitial(user)}
            </Avatar>

            <div style={{ minWidth: 0, flex: 1 }}>
              <Typography.Text strong style={{ fontSize: 16 }}>
                {user.nickname || '未设置昵称'}
              </Typography.Text>
              <div style={{ marginTop: 2 }}>
                <Space size={12} wrap>
                  <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                    {user.mobile || '未绑定手机号'}
                  </Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    用户 #{user.user_id}
                  </Typography.Text>
                </Space>
              </div>
            </div>

            <div style={{ textAlign: 'right' }}>
              <Typography.Text
                style={{ display: 'block', fontSize: 22, fontWeight: 600 }}
              >
                {formatNumber(total)}
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                已拥有课程
              </Typography.Text>
            </div>
          </div>
        </Card>
      ) : (
        <Card className="mb-4">
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <div>
                <Typography.Text strong>
                  输入手机号或用户 ID 开始管理
                </Typography.Text>
                <div
                  style={{ marginTop: 4, fontSize: 12, color: '#a8a29e' }}
                >
                  查找到用户后可查看课程授权、赠送课程或重置有效期。
                </div>
              </div>
            }
          />
        </Card>
      )}

      {listError ? (
        <Alert
          type="error"
          showIcon
          className="mb-4"
          message="课程列表查询失败"
          description={listError}
          action={
            <Button size="small" onClick={refreshCurrentPage}>
              重试
            </Button>
          }
        />
      ) : null}

      {user ? (
        <Card styles={{ body: { padding: 0 } }}>
          <Table<AdminUserCourseItem>
            rowKey="course_id"
            columns={columns}
            dataSource={items}
            loading={listLoading}
            scroll={{ x: 900 }}
            onRow={(item) => ({
              style: item.expired ? { background: '#fef2f2' } : undefined
            })}
            title={() => (
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                已拥有课程 · 共 {formatNumber(total)} 门
                {items.some((item) => item.expired)
                  ? ' · 浅红行为已过期授权'
                  : ''}
              </Typography.Text>
            )}
            locale={{
              emptyText: listLoading
                ? '正在查询课程授权…'
                : '该用户暂未拥有课程，可点击右上角「赠送课程」'
            }}
            pagination={{
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              pageSizeOptions: ['10', '20', '50'],
              showTotal: (count) => `共 ${count} 门`,
              onChange: (nextPage, nextPageSize) =>
                void loadCourses(user.user_id, nextPage, nextPageSize)
            }}
          />
        </Card>
      ) : null}

      <Typography.Paragraph
        type="secondary"
        style={{ marginTop: 14, fontSize: 11, lineHeight: '20px' }}
      >
        有效期仅管理后台可见，用户端不展示。赠课与重置不会产生订单或支付；
        同一用户与课程重复操作只更新有效期，并将授权来源标记为「赠课」
        （后端既有规则）。
      </Typography.Paragraph>

      <Modal
        open={modalOpen}
        title={presetCourse ? '重置课程有效期' : '赠送课程'}
        width={presetCourse ? 420 : 580}
        okText={presetCourse ? '重置有效期' : '确认赠送'}
        cancelText="取消"
        confirmLoading={submitting}
        onOk={() => form.submit()}
        onCancel={closeModal}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={
            presetCourse
              ? '已拥有时只更新有效期，不会新增重复授权；操作会写入日志。'
              : '同一用户 + 课程只保留一条授权。重复赠送只更新有效期，并写入操作日志。'
          }
        />

        {user ? (
          <Typography.Paragraph
            type="secondary"
            style={{ marginBottom: 14, fontSize: 12 }}
          >
            目标用户：{user.nickname || '未设置昵称'}（
            {user.mobile || `用户 #${user.user_id}`}）
          </Typography.Paragraph>
        ) : null}

        <Form<ResetFormValues>
          form={form}
          layout="vertical"
          initialValues={{ valid_days: DEFAULT_VALID_DAYS }}
          onFinish={(values) => void handleSubmit(values)}
          preserve={false}
        >
          {presetCourse ? (
            <Form.Item label="课程">
              <div
                style={{
                  padding: '8px 12px',
                  border: '1px solid #e7e5e4',
                  borderRadius: 8,
                  background: '#fafaf9'
                }}
              >
                <Typography.Text strong>
                  {presetCourse.course_title}
                </Typography.Text>
                <Typography.Text
                  type="secondary"
                  style={{ display: 'block', fontSize: 11 }}
                >
                  课程 #{presetCourse.course_id}
                </Typography.Text>
              </div>
            </Form.Item>
          ) : (
            <Form.Item
              name="courseId"
              label="课程"
              rules={[{ required: true, message: '请选择要赠送的课程' }]}
            >
              <AdminCourseSelect disabled={submitting} />
            </Form.Item>
          )}

          <Form.Item
            name="valid_days"
            label="有效天数"
            extra={`从操作当日起算（UTC），预计到期：${previewExpireDate(validDays)}（Asia/Shanghai）`}
            rules={[
              { required: true, message: '请输入有效天数' },
              {
                type: 'number',
                min: 1,
                max: MAX_VALID_DAYS,
                message: `有效天数需为 1-${MAX_VALID_DAYS} 的整数`
              }
            ]}
          >
            <InputNumber
              min={1}
              max={MAX_VALID_DAYS}
              precision={0}
              placeholder="默认 365"
              style={{ width: '100%' }}
              disabled={submitting}
            />
          </Form.Item>

          {modalError ? (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 12 }}
              message="操作失败"
              description={modalError}
            />
          ) : null}

          <Typography.Text
            type="secondary"
            style={{ fontSize: 11, lineHeight: '18px' }}
          >
            操作将记录管理员、用户、课程、操作类型与有效期；不产生订单、
            支付或退款。
          </Typography.Text>
        </Form>
      </Modal>
    </div>
  )
}
