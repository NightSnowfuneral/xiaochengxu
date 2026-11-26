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
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  GiftOutlined,
  HistoryOutlined,
  ReloadOutlined,
  SearchOutlined,
  SettingOutlined
} from '@ant-design/icons'

import {
  ApiError,
  getErrorMessage
} from '../../api/request'
import {
  fetchAdminUserCourseLogs,
  fetchAdminUserCoursesByUser,
  grantAdminUserCourse,
  revokeAdminUserCourse,
  searchAdminUsers
} from '../../api/userCourseAdminApi'
import AdminCourseSelect from '../../components/admin/CourseSelect'
import AdminPageHeader from '../../components/admin/PageHeader'
import { UserCourseStatusTag } from '../../components/admin/StatusTags'
import type {
  AdminUserCourseAction,
  AdminUserCourseItem,
  AdminUserCourseLog,
  AdminUserListItem
} from '../../types'
import {
  formatDateTime,
  formatNumber,
  formatShanghaiDate,
  formatShanghaiDateTime
} from '../../utils/format'

const DEFAULT_PAGE_SIZE = 10
const DRAWER_PAGE_SIZE = 10
const DEFAULT_VALID_DAYS = 365
const MAX_VALID_DAYS = 36500

interface ResetFormValues {
  courseId?: number | null
  valid_days: number | null
}

function userInitial(user: Pick<AdminUserListItem, 'nickname'>): string {
  return user.nickname?.trim().slice(0, 1) || '用'
}

const COURSE_ACTION_LABELS: Record<AdminUserCourseAction, string> = {
  gift: '赠课',
  reset: '重置有效期',
  revoke: '收回'
}

const COURSE_ACTION_COLORS: Record<AdminUserCourseAction, string> = {
  gift: 'gold',
  reset: 'blue',
  revoke: 'red'
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

  // 模糊搜索：手机号片段 / 昵称片段 / 用户 ID。
  const [keyword, setKeyword] = useState('')
  const [activeKeyword, setActiveKeyword] = useState('')
  const [results, setResults] = useState<AdminUserListItem[]>([])
  const [resultTotal, setResultTotal] = useState(0)
  const [resultPage, setResultPage] = useState(1)
  const [resultPageSize, setResultPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [resultLoading, setResultLoading] = useState(false)
  const [resultError, setResultError] = useState<string | null>(null)
  const [searched, setSearched] = useState(false)
  const searchSeq = useRef(0)

  // 右侧抽屉：选中用户的授权课程。
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerUser, setDrawerUser] = useState<AdminUserListItem | null>(null)
  const [items, setItems] = useState<AdminUserCourseItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DRAWER_PAGE_SIZE)
  const [listLoading, setListLoading] = useState(false)
  const [listError, setListError] = useState<string | null>(null)
  const drawerSeq = useRef(0)

  // 用户课程操作日志抽屉：赠课 / 重置 / 收回统一审计。
  const [logOpen, setLogOpen] = useState(false)
  const [logs, setLogs] = useState<AdminUserCourseLog[]>([])
  const [logTotal, setLogTotal] = useState(0)
  const [logPage, setLogPage] = useState(1)
  const [logPageSize, setLogPageSize] = useState(20)
  const [logAction, setLogAction] = useState<AdminUserCourseAction | undefined>(
    undefined
  )
  const [logLoading, setLogLoading] = useState(false)
  const [logError, setLogError] = useState<string | null>(null)
  const logSeq = useRef(0)

  // 赠课 / 重置有效期弹窗。
  const [modalOpen, setModalOpen] = useState(false)
  const [modalUser, setModalUser] = useState<AdminUserListItem | null>(null)
  const [presetCourse, setPresetCourse] =
    useState<AdminUserCourseItem | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [modalError, setModalError] = useState<string | null>(null)
  const [revokingCourseId, setRevokingCourseId] = useState<number | null>(null)
  const [form] = Form.useForm<ResetFormValues>()
  const validDays = Form.useWatch('valid_days', form) ?? DEFAULT_VALID_DAYS

  useEffect(() => {
    return () => {
      searchSeq.current += 1
      drawerSeq.current += 1
      logSeq.current += 1
    }
  }, [])

  const runSearch = useCallback(
    async (
      rawValue: string,
      nextPage: number,
      nextPageSize: number
    ) => {
      const value = rawValue.trim()
      if (!value) {
        setResultError('请输入手机号片段、昵称或用户 ID')
        return
      }

      const seq = searchSeq.current + 1
      searchSeq.current = seq
      setActiveKeyword(value)
      setSearched(true)
      setResultLoading(true)
      setResultError(null)
      try {
        const response = await searchAdminUsers(
          value,
          nextPage,
          nextPageSize
        )
        if (seq !== searchSeq.current) {
          return
        }
        setResults(response.items)
        setResultTotal(response.total)
        setResultPage(response.page)
        setResultPageSize(response.page_size)
      } catch (searchFailure) {
        if (seq !== searchSeq.current) {
          return
        }
        setResults([])
        setResultTotal(0)
        setResultError(getErrorMessage(searchFailure))
      } finally {
        if (seq === searchSeq.current) {
          setResultLoading(false)
        }
      }
    },
    []
  )

  const refreshResults = useCallback(() => {
    if (!activeKeyword) {
      return
    }
    void runSearch(activeKeyword, resultPage, resultPageSize)
  }, [activeKeyword, resultPage, resultPageSize, runSearch])

  const loadLogs = useCallback(
    async (
      nextPage: number,
      nextPageSize: number,
      action: AdminUserCourseAction | undefined
    ) => {
      const seq = logSeq.current + 1
      logSeq.current = seq
      setLogLoading(true)
      setLogError(null)
      try {
        const response = await fetchAdminUserCourseLogs({
          page: nextPage,
          page_size: nextPageSize,
          action
        })
        if (seq !== logSeq.current) {
          return
        }
        setLogs(response.items)
        setLogTotal(response.total)
        setLogPage(response.page)
        setLogPageSize(response.page_size)
      } catch (failure) {
        if (seq !== logSeq.current) {
          return
        }
        setLogs([])
        setLogTotal(0)
        setLogError(getErrorMessage(failure))
      } finally {
        if (seq === logSeq.current) {
          setLogLoading(false)
        }
      }
    },
    []
  )

  const openLogs = () => {
    setLogOpen(true)
    void loadLogs(1, logPageSize, logAction)
  }

  const loadCourses = useCallback(
    async (userId: number, nextPage: number, nextPageSize: number) => {
      const seq = drawerSeq.current + 1
      drawerSeq.current = seq
      setListLoading(true)
      setListError(null)
      try {
        const response = await fetchAdminUserCoursesByUser(
          userId,
          nextPage,
          nextPageSize
        )
        if (seq !== drawerSeq.current) {
          return
        }
        setItems(response.items)
        setTotal(response.total)
        setPage(response.page)
        setPageSize(response.page_size)
      } catch (loadFailure) {
        if (seq !== drawerSeq.current) {
          return
        }
        setListError(getErrorMessage(loadFailure))
      } finally {
        if (seq === drawerSeq.current) {
          setListLoading(false)
        }
      }
    },
    []
  )

  const openDrawer = (user: AdminUserListItem) => {
    setDrawerUser(user)
    setDrawerOpen(true)
    setItems([])
    setTotal(0)
    setPage(1)
    setListError(null)
    void loadCourses(user.user_id, 1, DRAWER_PAGE_SIZE)
  }

  const closeDrawer = () => {
    if (revokingCourseId !== null) {
      return
    }
    setDrawerOpen(false)
  }

  const openGiftModal = (user: AdminUserListItem) => {
    setModalUser(user)
    setPresetCourse(null)
    setModalError(null)
    setModalOpen(true)
  }

  const openResetModal = (item: AdminUserCourseItem) => {
    if (!drawerUser) {
      return
    }
    setModalUser(drawerUser)
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
    if (!modalUser) {
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
        user_id: modalUser.user_id,
        course_id: courseId,
        valid_days: values.valid_days
      })
      setModalOpen(false)
      message.success(
        `${result.message}，有效期至 ${formatShanghaiDateTime(result.expire_time)}`
      )
      refreshResults()
      if (drawerOpen && drawerUser?.user_id === modalUser.user_id) {
        await loadCourses(drawerUser.user_id, page, pageSize)
      }
    } catch (grantFailure) {
      setModalError(getErrorMessage(grantFailure))
    } finally {
      setSubmitting(false)
    }
  }

  const handleRevoke = async (item: AdminUserCourseItem) => {
    if (!drawerUser || revokingCourseId !== null) {
      return
    }
    const userId = drawerUser.user_id
    setRevokingCourseId(item.course_id)
    try {
      const result = await revokeAdminUserCourse({
        user_id: userId,
        course_id: item.course_id
      })
      const nextPage = items.length === 1 && page > 1 ? page - 1 : page
      message.success(result.message)
      await loadCourses(userId, nextPage, pageSize)
      refreshResults()
    } catch (revokeFailure) {
      if (
        revokeFailure instanceof ApiError &&
        revokeFailure.code === 'USER_COURSE_NOT_FOUND'
      ) {
        message.warning('该课程授权已不存在，列表已刷新')
      } else {
        message.error(getErrorMessage(revokeFailure))
      }
      await loadCourses(userId, page, pageSize)
      refreshResults()
    } finally {
      setRevokingCourseId(null)
    }
  }

  const resultColumns: ColumnsType<AdminUserListItem> = [
    {
      title: '用户',
      key: 'user',
      render: (_value, user) => (
        <Space size={10}>
          <Avatar
            size={40}
            src={user.avatar_url || undefined}
            style={{
              flexShrink: 0,
              background: '#0d1526',
              color: '#dbbd7d',
              fontSize: 15
            }}
          >
            {userInitial(user)}
          </Avatar>
          <div style={{ minWidth: 0 }}>
            <Typography.Text
              strong
              ellipsis
              style={{ display: 'block', maxWidth: 220 }}
            >
              {user.nickname || '未设置昵称'}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              用户 #{user.user_id}
            </Typography.Text>
          </div>
        </Space>
      )
    },
    {
      title: '手机号',
      dataIndex: 'mobile',
      key: 'mobile',
      width: 170,
      render: (mobile: string | null) => (
        <Typography.Text
          style={{ fontSize: 12, color: mobile ? '#57534e' : '#a8a29e' }}
        >
          {mobile || '未绑定手机号'}
        </Typography.Text>
      )
    },
    {
      title: '已拥有课程',
      dataIndex: 'owned_course_count',
      key: 'owned_course_count',
      width: 130,
      render: (count: number) =>
        count > 0 ? (
          <Tag
            color="gold"
            bordered={false}
            style={{ borderRadius: 999 }}
          >
            {formatNumber(count)} 门
          </Tag>
        ) : (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            0 门
          </Typography.Text>
        )
    },
    {
      title: '操作',
      key: 'actions',
      width: 230,
      render: (_value, user) => (
        <Space size={8}>
          <Button
            size="small"
            icon={<GiftOutlined />}
            onClick={() => openGiftModal(user)}
          >
            赠送课程
          </Button>
          <Button
            size="small"
            icon={<SettingOutlined />}
            onClick={() => openDrawer(user)}
          >
            管理课程
          </Button>
        </Space>
      )
    }
  ]

  const courseColumns: ColumnsType<AdminUserCourseItem> = [
    {
      title: '课程名称',
      key: 'course',
      ellipsis: true,
      render: (_value, item) => (
        <div style={{ minWidth: 0 }}>
          <Typography.Text
            strong
            ellipsis
            style={{ display: 'block', maxWidth: 280 }}
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
      width: 90,
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
      width: 165,
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
      width: 100,
      render: (_value, item) => <UserCourseStatusTag item={item} />
    },
    {
      title: '操作',
      key: 'actions',
      width: 180,
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
            description="收回后用户将立即失去该课程的播放权限。购买来源的收回不会产生退款；操作会写入日志。"
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

  const renderDrawerTitle = () => {
    if (!drawerUser) {
      return '课程管理'
    }
    return (
      <Space size={12}>
        <Avatar
          size={40}
          src={drawerUser.avatar_url || undefined}
          style={{
            background: '#0d1526',
            color: '#dbbd7d',
            fontSize: 15
          }}
        >
          {userInitial(drawerUser)}
        </Avatar>
        <div>
          <Typography.Text strong style={{ fontSize: 15 }}>
            {drawerUser.nickname || '未设置昵称'}
          </Typography.Text>
          <Typography.Text
            type="secondary"
            style={{ display: 'block', fontSize: 12 }}
          >
            {drawerUser.mobile || '未绑定手机号'} · 用户 #
            {drawerUser.user_id}
          </Typography.Text>
        </div>
      </Space>
    )
  }

  const logColumns: ColumnsType<AdminUserCourseLog> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (value: string) => formatDateTime(value)
    },
    {
      title: '学员',
      key: 'user',
      width: 200,
      render: (_value, item) => (
        <div style={{ fontSize: 12 }}>
          <div>{item.user_nickname || '未设置昵称'}</div>
          <div style={{ color: '#a8a29e' }}>
            {item.user_mobile || `用户 #${item.user_id}`}
          </div>
        </div>
      )
    },
    {
      title: '课程',
      key: 'course',
      width: 200,
      render: (_value, item) =>
        item.course_title
          ? `${item.course_title}（#${item.course_id}）`
          : `#${item.course_id}`
    },
    {
      title: '操作',
      dataIndex: 'action',
      key: 'action',
      width: 110,
      render: (value: AdminUserCourseAction) => (
        <Tag color={COURSE_ACTION_COLORS[value]} bordered={false}>
          {COURSE_ACTION_LABELS[value]}
        </Tag>
      )
    },
    {
      title: '有效期',
      key: 'validity',
      width: 200,
      render: (_value, item) => (
        <div style={{ fontSize: 12 }}>
          <div>{item.valid_days ? `${item.valid_days} 天` : '—'}</div>
          <div style={{ color: '#a8a29e' }}>
            {item.expire_time
              ? `至 ${formatShanghaiDateTime(item.expire_time)}`
              : '—'}
          </div>
        </div>
      )
    },
    {
      title: '操作管理员',
      key: 'admin',
      width: 140,
      render: (_value, item) =>
        item.admin_username
          ? `${item.admin_username}（#${item.admin_id}）`
          : `#${item.admin_id}`
    }
  ]

  return (
    <div>
      <AdminPageHeader
        eyebrow="USER COURSES"
        title="用户课程管理"
        description="按手机号片段、昵称或用户 ID 模糊搜索用户；搜索结果可直接赠送课程，或打开右侧抽屉管理已拥有课程、重置有效期与收回授权。"
        extra={
          <Button icon={<HistoryOutlined />} onClick={openLogs}>
            操作日志
          </Button>
        }
      />

      <Card className="mb-4">
        <div style={{ maxWidth: 720 }}>
          <Input.Search
            value={keyword}
            onChange={(event) => {
              setKeyword(event.target.value)
              setResultError(null)
            }}
            onSearch={(value) => {
              void runSearch(value, 1, resultPageSize)
            }}
            placeholder="手机号片段、昵称或用户 ID，支持模糊搜索"
            maxLength={64}
            size="large"
            loading={resultLoading}
            enterButton={
              <>
                <SearchOutlined /> 搜索用户
              </>
            }
            allowClear
            disabled={resultLoading}
          />
          <Typography.Text
            type="secondary"
            style={{ display: 'block', marginTop: 8, fontSize: 12 }}
          >
            模糊匹配手机号与昵称，例如「1380013」「小王」；纯数字同时匹配用户 ID。
          </Typography.Text>
        </div>

        {resultError ? (
          <Alert
            type="error"
            showIcon
            style={{ marginTop: 14 }}
            message="搜索失败"
            description={resultError}
            action={
              activeKeyword ? (
                <Button
                  size="small"
                  onClick={() =>
                    void runSearch(
                      activeKeyword,
                      resultPage,
                      resultPageSize
                    )
                  }
                >
                  重试
                </Button>
              ) : null
            }
          />
        ) : null}
      </Card>

      {searched ? (
        <Card styles={{ body: { padding: 0 } }}>
          <Table<AdminUserListItem>
            rowKey="user_id"
            columns={resultColumns}
            dataSource={results}
            loading={resultLoading}
            scroll={{ x: 760 }}
            title={() => (
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                搜索结果 · 关键词「{activeKeyword}」· 共{' '}
                {formatNumber(resultTotal)} 位用户
              </Typography.Text>
            )}
            locale={{
              emptyText: resultLoading
                ? '正在搜索用户…'
                : `未找到与「${activeKeyword}」匹配的用户`
            }}
            pagination={{
              current: resultPage,
              pageSize: resultPageSize,
              total: resultTotal,
              showSizeChanger: true,
              pageSizeOptions: ['10', '20', '50'],
              showTotal: (count) => `共 ${count} 位用户`,
              onChange: (nextPage, nextPageSize) => {
                setResultPageSize(nextPageSize)
                void runSearch(activeKeyword, nextPage, nextPageSize)
              }
            }}
          />
        </Card>
      ) : (
        <Card>
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <div>
                <Typography.Text strong>
                  输入手机号片段、昵称或用户 ID 开始搜索
                </Typography.Text>
                <div style={{ marginTop: 4, fontSize: 12, color: '#a8a29e' }}>
                  搜索结果支持直接赠送课程，或进入课程管理查看授权、重置有效期与收回。
                </div>
              </div>
            }
          />
        </Card>
      )}

      <Typography.Paragraph
        type="secondary"
        style={{ marginTop: 14, fontSize: 11, lineHeight: '20px' }}
      >
        有效期仅管理后台可见，用户端不展示。赠课与重置不会产生订单或支付；
        同一用户与课程重复操作只更新有效期，并将授权来源标记为「赠课」。
        收回后即删除授权，重复支付回调也不会重新发放已收回的课程。
      </Typography.Paragraph>

      <Drawer
        open={drawerOpen}
        onClose={closeDrawer}
        width={880}
        destroyOnClose
        title={renderDrawerTitle()}
        extra={
          drawerUser ? (
            <Space>
              <Button
                type="primary"
                icon={<GiftOutlined />}
                onClick={() => openGiftModal(drawerUser)}
              >
                赠送课程
              </Button>
              <Button
                icon={<ReloadOutlined />}
                loading={listLoading}
                onClick={() =>
                  void loadCourses(drawerUser.user_id, page, pageSize)
                }
              >
                刷新
              </Button>
            </Space>
          ) : null
        }
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 14 }}
          message="收回后用户立即失去播放权限；授权删除后，微信重复支付回调也不会补发。"
        />

        {listError ? (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 14 }}
            message="课程列表查询失败"
            description={listError}
            action={
              drawerUser ? (
                <Button
                  size="small"
                  onClick={() =>
                    void loadCourses(
                      drawerUser.user_id,
                      page,
                      pageSize
                    )
                  }
                >
                  重试
                </Button>
              ) : null
            }
          />
        ) : null}

        <Table<AdminUserCourseItem>
          rowKey="course_id"
          columns={courseColumns}
          dataSource={items}
          loading={listLoading}
          size="middle"
          scroll={{ x: 780 }}
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
              : '该用户暂未拥有课程，可点击「赠送课程」'
          }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: ['10', '20', '50'],
            showTotal: (count) => `共 ${count} 门`,
            onChange: (nextPage, nextPageSize) => {
              if (drawerUser) {
                void loadCourses(
                  drawerUser.user_id,
                  nextPage,
                  nextPageSize
                )
              }
            }
          }}
        />
      </Drawer>

      <Modal
        open={modalOpen}
        title={presetCourse ? '重置课程有效期' : '赠送课程'}
        width={presetCourse ? 460 : 580}
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

        {modalUser ? (
          <Typography.Paragraph
            type="secondary"
            style={{ marginBottom: 14, fontSize: 12 }}
          >
            目标用户：{modalUser.nickname || '未设置昵称'}（
            {modalUser.mobile || `用户 #${modalUser.user_id}`}）
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

      <Drawer
        open={logOpen}
        width={980}
        title="用户课程操作日志"
        onClose={() => setLogOpen(false)}
        destroyOnClose
        extra={
          <Space>
            <Select
              allowClear
              size="small"
              placeholder="全部操作"
              style={{ width: 130 }}
              value={logAction}
              options={[
                { label: '赠课', value: 'gift' },
                { label: '重置有效期', value: 'reset' },
                { label: '收回', value: 'revoke' }
              ]}
              onChange={(value) => {
                const next = value as AdminUserCourseAction | undefined
                setLogAction(next)
                void loadLogs(1, logPageSize, next)
              }}
            />
            <Button
              size="small"
              icon={<ReloadOutlined />}
              loading={logLoading}
              onClick={() => void loadLogs(logPage, logPageSize, logAction)}
            >
              刷新
            </Button>
          </Space>
        }
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 14 }}
          message="赠课、重置有效期、收回都会写入操作日志；赠课日志只记录新增授权，重置与收回请在本页核对。"
        />
        {logError ? (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 14 }}
            message="操作日志加载失败"
            description={logError}
            action={
              <Button
                size="small"
                onClick={() => void loadLogs(logPage, logPageSize, logAction)}
              >
                重试
              </Button>
            }
          />
        ) : null}
        <Table<AdminUserCourseLog>
          rowKey="id"
          size="small"
          columns={logColumns}
          dataSource={logs}
          loading={logLoading}
          scroll={{ x: 860 }}
          pagination={{
            current: logPage,
            pageSize: logPageSize,
            total: logTotal,
            showSizeChanger: true,
            pageSizeOptions: ['10', '20', '50'],
            showTotal: (count) => `共 ${count} 条`,
            onChange: (nextPage, nextPageSize) => {
              void loadLogs(nextPage, nextPageSize, logAction)
            }
          }}
          locale={{
            emptyText: logLoading ? '正在加载操作日志…' : '暂无操作日志'
          }}
        />
      </Drawer>
    </div>
  )
}
