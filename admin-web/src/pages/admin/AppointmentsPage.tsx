import { useCallback, useEffect, useRef, useState } from 'react'
import type { Dayjs } from 'dayjs'
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
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Steps,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined
} from '@ant-design/icons'

import {
  cancelAdminAppointment,
  completeAdminAppointment,
  fetchAdminAppointmentQuotaLogs,
  fetchAdminAppointmentQuotas,
  fetchAdminAppointments,
  grantAdminAppointmentQuota,
  reclaimAdminAppointmentQuota
} from '../../api/appointmentApi'
import { getErrorMessage } from '../../api/request'
import { lookupAdminUser } from '../../api/userCourseAdminApi'
import AdminPageHeader from '../../components/admin/PageHeader'
import { AppointmentStatusTag } from '../../components/admin/StatusTags'
import type {
  AdminAppointment,
  AdminAppointmentQuota,
  AdminAppointmentQuotaLog,
  AdminAppointmentQueryParams,
  AdminUserSummary,
  AppointmentStatus
} from '../../types'
import {
  formatShanghaiDateTime,
  formatNumber
} from '../../utils/format'
import { isValidMobile, parsePositiveInt } from '../../utils/validation'

const { RangePicker } = DatePicker

const DEFAULT_PAGE_SIZE = 20
const MAX_GRANT_COUNT = 1000
/** 停留页面期间的静默刷新间隔。 */
const APPOINTMENT_AUTO_REFRESH_MS = 30_000

const WEEKDAY_LABELS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

const STATUS_OPTIONS: Array<{ label: string; value: AppointmentStatus | 'all' }> =
  [
    { label: '待完成 pending', value: 'pending' },
    { label: '已完成 completed', value: 'completed' },
    { label: '已过期 expired', value: 'expired' },
    { label: '全部状态', value: 'all' }
  ]

const SOURCE_LABELS: Record<AdminAppointmentQuotaLog['source'], string> = {
  purchase: '购买赠送',
  admin: '后台分配',
  consume: '预约消耗',
  cancel: '取消退还',
  reclaim: '后台回收'
}

interface AppointmentFilterValues {
  status: AppointmentStatus | 'all'
  keyword?: string
  range?: [Dayjs | null, Dayjs | null] | null
}

const INITIAL_QUERY: AdminAppointmentQueryParams = {
  page: 1,
  page_size: DEFAULT_PAGE_SIZE,
  status: 'all'
}

function appointmentWeekday(value: string): string {
  const [year, month, day] = value.split('-').map(Number)
  if (!year || !month || !day) {
    return ''
  }
  return WEEKDAY_LABELS[new Date(year, month - 1, day).getDay()] ?? ''
}

function userInitial(
  nickname: string | null,
  mobile: string | null,
  userId: number
): string {
  return nickname?.trim().slice(0, 1) || mobile?.slice(-2) || String(userId)
}

interface CompleteModalState {
  appointment: AdminAppointment | null
  remark: string
  submitting: boolean
  error: string | null
}

interface AllocateModalState {
  quota: AdminAppointmentQuota | null
  count: number | null
  remark: string
  submitting: boolean
  error: string | null
}

interface ReclaimModalState {
  quota: AdminAppointmentQuota | null
  count: number | null
  remark: string
  submitting: boolean
  error: string | null
}

interface HeaderGrantState {
  step: 0 | 1
  keyword: string
  searching: boolean
  searchError: string | null
  user: AdminUserSummary | null
  count: number | null
  remark: string
  submitting: boolean
  error: string | null
}

const EMPTY_HEADER_GRANT: HeaderGrantState = {
  step: 0,
  keyword: '',
  searching: false,
  searchError: null,
  user: null,
  count: 1,
  remark: '',
  submitting: false,
  error: null
}

export default function AppointmentsPage() {
  const { message } = AntdApp.useApp()
  const [activeTab, setActiveTab] = useState<'appointments' | 'quotas'>(
    'appointments'
  )
  const [filterForm] = Form.useForm<AppointmentFilterValues>()

  const [appointments, setAppointments] = useState<AdminAppointment[]>([])
  const [appointmentTotal, setAppointmentTotal] = useState(0)
  const [appointmentPage, setAppointmentPage] = useState(1)
  const [appointmentPageSize, setAppointmentPageSize] =
    useState(DEFAULT_PAGE_SIZE)
  const [appointmentQuery, setAppointmentQuery] =
    useState<AdminAppointmentQueryParams>(INITIAL_QUERY)
  const [appointmentsLoading, setAppointmentsLoading] = useState(true)
  const [appointmentsError, setAppointmentsError] = useState<string | null>(
    null
  )
  const [filterError, setFilterError] = useState<string | null>(null)
  const appointmentSeq = useRef(0)

  const [detail, setDetail] = useState<AdminAppointment | null>(null)
  const [completeModal, setCompleteModal] = useState<CompleteModalState>({
    appointment: null,
    remark: '',
    submitting: false,
    error: null
  })
  const [cancellingNo, setCancellingNo] = useState<string | null>(null)

  const [quotaKeyword, setQuotaKeyword] = useState('')
  const [hasRemainingOnly, setHasRemainingOnly] = useState(false)
  const [quotas, setQuotas] = useState<AdminAppointmentQuota[]>([])
  const [quotaTotal, setQuotaTotal] = useState(0)
  const [quotaPage, setQuotaPage] = useState(1)
  const [quotaPageSize, setQuotaPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [quotaQuery, setQuotaQuery] = useState({ keyword: '', only: false })
  const [quotasLoading, setQuotasLoading] = useState(false)
  const [quotasError, setQuotasError] = useState<string | null>(null)
  const [quotasLoaded, setQuotasLoaded] = useState(false)
  const quotaSeq = useRef(0)

  const [allocateModal, setAllocateModal] = useState<AllocateModalState>({
    quota: null,
    count: 1,
    remark: '',
    submitting: false,
    error: null
  })

  const [reclaimModal, setReclaimModal] = useState<ReclaimModalState>({
    quota: null,
    count: 1,
    remark: '',
    submitting: false,
    error: null
  })

  const [logQuota, setLogQuota] = useState<AdminAppointmentQuota | null>(null)
  const [logs, setLogs] = useState<AdminAppointmentQuotaLog[]>([])
  const [logTotal, setLogTotal] = useState(0)
  const [logPage, setLogPage] = useState(1)
  const [logPageSize, setLogPageSize] = useState(20)
  const [logsLoading, setLogsLoading] = useState(false)
  const [logsError, setLogsError] = useState<string | null>(null)

  const [grantOpen, setGrantOpen] = useState(false)
  const [grant, setGrant] = useState<HeaderGrantState>({
    ...EMPTY_HEADER_GRANT
  })

  const loadAppointments = useCallback(
    async (
      params: AdminAppointmentQueryParams,
      options?: { silent?: boolean }
    ) => {
      const silent = options?.silent === true
      const seq = appointmentSeq.current + 1
      appointmentSeq.current = seq
      if (!silent) {
        setAppointmentsLoading(true)
        setAppointmentsError(null)
      }
      try {
        const response = await fetchAdminAppointments(params)
        if (seq !== appointmentSeq.current) {
          return
        }
        setAppointments(response.items)
        setAppointmentTotal(response.total)
        setAppointmentPage(response.page)
        setAppointmentPageSize(response.page_size)
        if (!silent) {
          setAppointmentQuery(params)
        }
      } catch (loadError) {
        if (seq !== appointmentSeq.current) {
          return
        }
        // 定时静默刷新失败时保留当前列表，不打断正在查看的数据。
        if (!silent) {
          setAppointmentsError(getErrorMessage(loadError))
        }
      } finally {
        if (!silent && seq === appointmentSeq.current) {
          setAppointmentsLoading(false)
        }
      }
    },
    []
  )

  const loadQuotas = useCallback(
    async (
      nextPage: number,
      nextPageSize: number,
      keyword: string,
      onlyRemaining: boolean
    ) => {
      const seq = quotaSeq.current + 1
      quotaSeq.current = seq
      setQuotasLoading(true)
      setQuotasError(null)
      try {
        const response = await fetchAdminAppointmentQuotas({
          page: nextPage,
          page_size: nextPageSize,
          keyword: keyword || undefined,
          has_remaining: onlyRemaining || undefined
        })
        if (seq !== quotaSeq.current) {
          return
        }
        setQuotas(response.items)
        setQuotaTotal(response.total)
        setQuotaPage(response.page)
        setQuotaPageSize(response.page_size)
        setQuotaQuery({ keyword, only: onlyRemaining })
        setQuotasLoaded(true)
      } catch (loadError) {
        if (seq !== quotaSeq.current) {
          return
        }
        setQuotasError(getErrorMessage(loadError))
      } finally {
        if (seq === quotaSeq.current) {
          setQuotasLoading(false)
        }
      }
    },
    []
  )

  useEffect(() => {
    void loadAppointments(INITIAL_QUERY)
    return () => {
      appointmentSeq.current += 1
      quotaSeq.current += 1
    }
  }, [loadAppointments])

  const refreshAppointmentsSilently = useCallback(() => {
    if (typeof document !== 'undefined' && document.hidden) {
      return
    }
    void loadAppointments(
      {
        ...appointmentQuery,
        page: appointmentPage,
        page_size: appointmentPageSize
      },
      { silent: true }
    )
  }, [appointmentPage, appointmentPageSize, appointmentQuery, loadAppointments])

  useEffect(() => {
    if (activeTab !== 'appointments') {
      return undefined
    }
    const timer = window.setInterval(
      refreshAppointmentsSilently,
      APPOINTMENT_AUTO_REFRESH_MS
    )
    // 切回浏览器标签页时立即补一次，避免展示离开期间的旧数据。
    const handleVisibilityChange = () => {
      if (!document.hidden) {
        refreshAppointmentsSilently()
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [activeTab, refreshAppointmentsSilently])

  const handleTabChange = (key: string) => {
    const next = key === 'quotas' ? 'quotas' : 'appointments'
    setActiveTab(next)
    if (next === 'quotas' && !quotasLoaded) {
      void loadQuotas(1, DEFAULT_PAGE_SIZE, '', false)
    }
  }

  const handleSearch = (values: AppointmentFilterValues) => {
    const params: AdminAppointmentQueryParams = {
      page: 1,
      page_size: appointmentPageSize
    }
    if (values.status && values.status !== 'all') {
      params.status = values.status
    }
    if (values.keyword?.trim()) {
      params.keyword = values.keyword.trim()
    }
    const [from, to] = values.range ?? []
    if (from && to && from.isAfter(to)) {
      setFilterError('开始日期不能晚于结束日期')
      return
    }
    if (from) {
      params.date_start = from.format('YYYY-MM-DD')
    }
    if (to) {
      params.date_end = to.format('YYYY-MM-DD')
    }
    setFilterError(null)
    void loadAppointments(params)
  }

  const handleResetFilters = () => {
    filterForm.resetFields()
    filterForm.setFieldsValue({ status: 'all' })
    setFilterError(null)
    void loadAppointments(INITIAL_QUERY)
  }

  const refreshAppointments = () => {
    void loadAppointments({
      ...appointmentQuery,
      page: appointmentPage,
      page_size: appointmentPageSize
    })
    if (activeTab === 'quotas') {
      void loadQuotas(
        quotaPage,
        quotaPageSize,
        quotaQuery.keyword,
        quotaQuery.only
      )
    }
  }

  const openComplete = (appointment: AdminAppointment) => {
    setCompleteModal({
      appointment,
      remark: '',
      submitting: false,
      error: null
    })
  }

  const submitComplete = async () => {
    const target = completeModal.appointment
    if (!target || completeModal.submitting) {
      return
    }
    setCompleteModal((previous) => ({
      ...previous,
      submitting: true,
      error: null
    }))
    try {
      await completeAdminAppointment(target.appointment_no, completeModal.remark)
      setCompleteModal({
        appointment: null,
        remark: '',
        submitting: false,
        error: null
      })
      message.success('已标记完成，本次不退还预约次数')
      await loadAppointments({
        ...appointmentQuery,
        page: appointmentPage,
        page_size: appointmentPageSize
      })
    } catch (failure) {
      setCompleteModal((previous) => ({
        ...previous,
        submitting: false,
        error: getErrorMessage(failure)
      }))
    }
  }

  const handleCancel = async (appointment: AdminAppointment) => {
    if (cancellingNo !== null) {
      return
    }
    setCancellingNo(appointment.appointment_no)
    try {
      const result = await cancelAdminAppointment(appointment.appointment_no)
      setAppointments((previous) =>
        previous.filter(
          (item) => item.appointment_no !== appointment.appointment_no
        )
      )
      setAppointmentTotal((previous) => Math.max(0, previous - 1))
      message.success(result.message)
      await loadAppointments({
        ...appointmentQuery,
        page: appointmentPage,
        page_size: appointmentPageSize
      })
      if (quotasLoaded) {
        void loadQuotas(
          quotaPage,
          quotaPageSize,
          quotaQuery.keyword,
          quotaQuery.only
        )
      }
    } catch (failure) {
      message.error(getErrorMessage(failure))
    } finally {
      setCancellingNo(null)
    }
  }

  const openAllocate = (quota: AdminAppointmentQuota) => {
    setAllocateModal({
      quota,
      count: 1,
      remark: '',
      submitting: false,
      error: null
    })
  }

  const submitAllocate = async () => {
    const target = allocateModal.quota
    if (!target || allocateModal.submitting) {
      return
    }
    const count = allocateModal.count
    if (!count || !Number.isInteger(count) || count < 1) {
      setAllocateModal((previous) => ({
        ...previous,
        error: '分配次数需为大于 0 的整数'
      }))
      return
    }
    setAllocateModal((previous) => ({
      ...previous,
      submitting: true,
      error: null
    }))
    try {
      const result = await grantAdminAppointmentQuota({
        user_id: target.user_id,
        count,
        remark: allocateModal.remark
      })
      setAllocateModal((previous) => ({
        ...previous,
        submitting: false,
        quota: null
      }))
      message.success(
        `已分配 ${count} 次，当前剩余 ${result.remaining} 次`
      )
      await loadQuotas(
        quotaPage,
        quotaPageSize,
        quotaQuery.keyword,
        quotaQuery.only
      )
    } catch (failure) {
      setAllocateModal((previous) => ({
        ...previous,
        submitting: false,
        error: getErrorMessage(failure)
      }))
    }
  }

  const openReclaim = (quota: AdminAppointmentQuota) => {
    setReclaimModal({
      quota,
      count: 1,
      remark: '',
      submitting: false,
      error: null
    })
  }

  const submitReclaim = async () => {
    const target = reclaimModal.quota
    if (!target || reclaimModal.submitting) {
      return
    }
    const count = reclaimModal.count
    if (!count || !Number.isInteger(count) || count < 1) {
      setReclaimModal((previous) => ({
        ...previous,
        error: '回收次数需为大于 0 的整数'
      }))
      return
    }
    if (count > target.remaining) {
      setReclaimModal((previous) => ({
        ...previous,
        error: `最多可回收 ${target.remaining} 次`
      }))
      return
    }
    setReclaimModal((previous) => ({
      ...previous,
      submitting: true,
      error: null
    }))
    try {
      const result = await reclaimAdminAppointmentQuota({
        quota_id: target.quota_id,
        count,
        remark: reclaimModal.remark
      })
      setReclaimModal((previous) => ({
        ...previous,
        submitting: false,
        quota: null
      }))
      message.success(
        `已回收 ${count} 次，当前剩余 ${result.remaining} 次`
      )
      await loadQuotas(
        quotaPage,
        quotaPageSize,
        quotaQuery.keyword,
        quotaQuery.only
      )
    } catch (failure) {
      setReclaimModal((previous) => ({
        ...previous,
        submitting: false,
        error: getErrorMessage(failure)
      }))
    }
  }

  const openLogs = async (quota: AdminAppointmentQuota) => {
    setLogQuota(quota)
    setLogs([])
    setLogTotal(0)
    setLogPage(1)
    setLogsError(null)
    setLogsLoading(true)
    try {
      const response = await fetchAdminAppointmentQuotaLogs({
        page: 1,
        page_size: logPageSize,
        quota_id: quota.quota_id
      })
      setLogs(response.items)
      setLogTotal(response.total)
      setLogPage(response.page)
    } catch (failure) {
      setLogsError(getErrorMessage(failure))
    } finally {
      setLogsLoading(false)
    }
  }

  const loadLogPage = async (nextPage: number, nextPageSize: number) => {
    if (!logQuota) {
      return
    }
    setLogsLoading(true)
    setLogsError(null)
    try {
      const response = await fetchAdminAppointmentQuotaLogs({
        page: nextPage,
        page_size: nextPageSize,
        quota_id: logQuota.quota_id
      })
      setLogs(response.items)
      setLogTotal(response.total)
      setLogPage(response.page)
      setLogPageSize(response.page_size)
    } catch (failure) {
      setLogsError(getErrorMessage(failure))
    } finally {
      setLogsLoading(false)
    }
  }

  const openHeaderGrant = () => {
    setGrant({ ...EMPTY_HEADER_GRANT })
    setGrantOpen(true)
  }

  const closeHeaderGrant = () => {
    if (!grant.submitting) {
      setGrantOpen(false)
      setGrant({ ...EMPTY_HEADER_GRANT })
    }
  }

  const searchGrantUser = async (rawValue?: string) => {
    const value = (rawValue ?? grant.keyword).trim()
    if (!value) {
      setGrant((previous) => ({
        ...previous,
        searchError: '请输入手机号或用户 ID'
      }))
      return
    }
    if (!isValidMobile(value) && !parsePositiveInt(value)) {
      setGrant((previous) => ({
        ...previous,
        searchError: '请输入 11 位手机号或正整数用户 ID'
      }))
      return
    }
    setGrant((previous) => ({
      ...previous,
      searching: true,
      searchError: null,
      user: null
    }))
    try {
      const user = await lookupAdminUser(value)
      setGrant((previous) => ({ ...previous, user, searching: false }))
    } catch (failure) {
      setGrant((previous) => ({
        ...previous,
        searching: false,
        searchError: getErrorMessage(failure)
      }))
    }
  }

  const submitHeaderGrant = async () => {
    if (!grant.user || grant.submitting) {
      return
    }
    const count = grant.count
    if (!count || !Number.isInteger(count) || count < 1) {
      setGrant((previous) => ({
        ...previous,
        error: '分配次数需为大于 0 的整数'
      }))
      return
    }
    setGrant((previous) => ({ ...previous, submitting: true, error: null }))
    try {
      const result = await grantAdminAppointmentQuota({
        user_id: grant.user.user_id,
        count,
        remark: grant.remark
      })
      setGrantOpen(false)
      setGrant({ ...EMPTY_HEADER_GRANT })
      message.success(
        `已为 ${grant.user.nickname || grant.user.mobile || `用户 #${grant.user.user_id}`} 分配 ${count} 次，当前剩余 ${result.remaining} 次`
      )
      setActiveTab('quotas')
      await loadQuotas(1, quotaPageSize, quotaQuery.keyword, quotaQuery.only)
    } catch (failure) {
      setGrant((previous) => ({
        ...previous,
        submitting: false,
        error: getErrorMessage(failure)
      }))
    }
  }

  const appointmentColumns: ColumnsType<AdminAppointment> = [
    {
      title: '预约号',
      key: 'appointment_no',
      width: 230,
      render: (_value, item) => (
        <div>
          <Typography.Text
            copyable={{
              text: item.appointment_no,
              tooltips: ['复制预约号', '已复制']
            }}
            style={{
              fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
              fontSize: 11
            }}
          >
            {item.appointment_no}
          </Typography.Text>
          <div style={{ fontSize: 11, color: '#a8a29e' }}>ID #{item.id}</div>
        </div>
      )
    },
    {
      title: '学员',
      key: 'user',
      width: 200,
      render: (_value, item) => (
        <Space size={10}>
          <Avatar
            size={34}
            src={item.user_avatar_url || undefined}
            style={{ background: '#0d1526', color: '#dbbd7d', fontSize: 13 }}
          >
            {userInitial(item.user_nickname, item.user_mobile, item.user_id)}
          </Avatar>
          <div style={{ minWidth: 0 }}>
            <Typography.Text strong style={{ fontSize: 13 }}>
              {item.user_nickname || '未设置昵称'}
            </Typography.Text>
            <div style={{ fontSize: 11, color: '#a8a29e' }}>
              {item.user_mobile || `用户 #${item.user_id}`}
            </div>
          </div>
        </Space>
      )
    },
    {
      title: '预约日期',
      key: 'date',
      width: 130,
      render: (_value, item) => (
        <div>
          <Typography.Text style={{ fontSize: 13 }}>
            {item.appointment_date}
          </Typography.Text>
          <div style={{ fontSize: 11, color: '#a8a29e' }}>
            {appointmentWeekday(item.appointment_date)}
          </div>
        </div>
      )
    },
    {
      title: '时段',
      key: 'slot',
      width: 120,
      render: (_value, item) => (
        <Typography.Text style={{ fontSize: 12 }}>
          {item.start_time} - {item.end_time}
        </Typography.Text>
      )
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: AppointmentStatus) => (
        <AppointmentStatusTag status={status} />
      )
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 150,
      render: (value: string) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {formatShanghaiDateTime(value)}
        </Typography.Text>
      )
    },
    {
      title: '完成时间',
      key: 'completed',
      width: 160,
      render: (_value, item) =>
        item.completed_at ? (
          <div>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {formatShanghaiDateTime(item.completed_at)}
            </Typography.Text>
            <div style={{ fontSize: 11, color: '#a8a29e' }}>
              {item.completed_by_name || '—'}
            </div>
          </div>
        ) : (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            —
          </Typography.Text>
        )
    },
    {
      title: '学员备注',
      dataIndex: 'user_remark',
      key: 'user_remark',
      width: 170,
      ellipsis: { showTitle: false },
      render: (value: string | null) =>
        value ? <Tooltip title={value}>{value}</Tooltip> : '—'
    },
    {
      title: '操作',
      key: 'actions',
      width: 190,
      fixed: 'right',
      render: (_value, item) => (
        <Space size={4}>
          {item.status === 'pending' ? (
            <>
              <Button
                type="link"
                size="small"
                onClick={() => openComplete(item)}
              >
                标记完成
              </Button>
              <Popconfirm
                title="取消该预约？"
                description="取消后将退还学员1次预约次数，该记录不再展示"
                okText="确认取消"
                cancelText="返回"
                okButtonProps={{
                  danger: true,
                  loading: cancellingNo === item.appointment_no
                }}
                onConfirm={() => handleCancel(item)}
              >
                <Button
                  type="link"
                  size="small"
                  danger
                  disabled={cancellingNo !== null}
                >
                  取消
                </Button>
              </Popconfirm>
            </>
          ) : null}
          <Button type="link" size="small" onClick={() => setDetail(item)}>
            详情
          </Button>
        </Space>
      )
    }
  ]

  const quotaColumns: ColumnsType<AdminAppointmentQuota> = [
    {
      title: '学员',
      key: 'user',
      width: 220,
      render: (_value, item) => (
        <Space size={10}>
          <Avatar
            size={34}
            src={item.user_avatar_url || undefined}
            style={{ background: '#0d1526', color: '#dbbd7d', fontSize: 13 }}
          >
            {userInitial(item.user_nickname, item.user_mobile, item.user_id)}
          </Avatar>
          <div style={{ minWidth: 0 }}>
            <Typography.Text strong style={{ fontSize: 13 }}>
              {item.user_nickname || '未设置昵称'}
            </Typography.Text>
            <div style={{ fontSize: 11, color: '#a8a29e' }}>
              {item.user_mobile || `用户 #${item.user_id}`}
            </div>
          </div>
        </Space>
      )
    },
    {
      title: '累计',
      dataIndex: 'total_count',
      key: 'total_count',
      width: 90,
      render: (value: number) => formatNumber(value)
    },
    {
      title: '已用',
      dataIndex: 'used_count',
      key: 'used_count',
      width: 90,
      render: (value: number) => formatNumber(value)
    },
    {
      title: '剩余',
      dataIndex: 'remaining',
      key: 'remaining',
      width: 100,
      render: (value: number) =>
        value > 0 ? (
          <Tag color="success" bordered={false} style={{ borderRadius: 999 }}>
            {formatNumber(value)} 次
          </Tag>
        ) : (
          <Tag bordered={false} style={{ borderRadius: 999 }}>
            0 次
          </Tag>
        )
    },
    {
      title: '最近发放',
      key: 'latest_grant_at',
      width: 150,
      render: (_value, item) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {formatShanghaiDateTime(item.latest_grant_at)}
        </Typography.Text>
      )
    },
    {
      title: '备注',
      dataIndex: 'remark',
      key: 'remark',
      width: 170,
      ellipsis: { showTitle: false },
      render: (value: string | null) =>
        value ? <Tooltip title={value}>{value}</Tooltip> : '—'
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      fixed: 'right',
      render: (_value, item) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => openAllocate(item)}>
            分配
          </Button>
          <Button
            type="link"
            size="small"
            danger
            disabled={item.remaining <= 0}
            onClick={() => openReclaim(item)}
          >
            回收
          </Button>
          <Button type="link" size="small" onClick={() => void openLogs(item)}>
            流水
          </Button>
        </Space>
      )
    }
  ]

  const logColumns: ColumnsType<AdminAppointmentQuotaLog> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 150,
      render: (value: string) => formatShanghaiDateTime(value)
    },
    {
      title: '变动',
      dataIndex: 'quantity',
      key: 'quantity',
      width: 80,
      render: (value: number) => (
        <Typography.Text
          strong
          style={{ color: value > 0 ? '#15803d' : '#b45309' }}
        >
          {value > 0 ? `+${value}` : value}
        </Typography.Text>
      )
    },
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      width: 100,
      render: (value: AdminAppointmentQuotaLog['source']) =>
        SOURCE_LABELS[value] ?? value
    },
    {
      title: '关联单号 / 操作人',
      key: 'operator',
      width: 180,
      render: (_value, item) => (
        <div style={{ fontSize: 12 }}>
          <div>{item.biz_no || '—'}</div>
          <div style={{ color: '#a8a29e' }}>
            {item.operator_name || '系统'}
          </div>
        </div>
      )
    },
    {
      title: '备注',
      dataIndex: 'remark',
      key: 'remark',
      ellipsis: { showTitle: false },
      render: (value: string | null) =>
        value ? <Tooltip title={value}>{value}</Tooltip> : '—'
    }
  ]

  const appointmentsTab = (
    <div>
      <Card className="mb-4">
        <Form<AppointmentFilterValues>
          form={filterForm}
          layout="vertical"
          initialValues={{ status: 'all', keyword: '' }}
          onFinish={handleSearch}
        >
          <Row gutter={[16, 12]} align="bottom">
            <Col xs={24} md={8} xl={5}>
              <Form.Item name="status" label="预约状态">
                <Select options={STATUS_OPTIONS} />
              </Form.Item>
            </Col>
            <Col xs={24} md={10} xl={8}>
              <Form.Item name="keyword" label="关键词">
                <Input
                  allowClear
                  placeholder="手机号、昵称或预约号"
                  maxLength={100}
                />
              </Form.Item>
            </Col>
            <Col xs={24} xl={7}>
              <Form.Item label=" " colon={false} style={{ marginBottom: 0 }}>
                <Space>
                  <Button
                    type="primary"
                    htmlType="submit"
                    icon={<SearchOutlined />}
                    loading={appointmentsLoading}
                  >
                    查询
                  </Button>
                  <Button onClick={handleResetFilters}>重置</Button>
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
                  <Form.Item
                    name="range"
                    label="预约日期范围"
                    style={{ marginBottom: 0, maxWidth: 380 }}
                  >
                    <RangePicker
                      format="YYYY-MM-DD"
                      style={{ width: '100%' }}
                    />
                  </Form.Item>
                )
              }
            ]}
          />
        </Form>

        {filterError ? (
          <Alert
            type="error"
            showIcon
            style={{ marginTop: 10 }}
            message={filterError}
          />
        ) : null}
      </Card>

      {appointmentsError ? (
        <Alert
          type="error"
          showIcon
          className="mb-4"
          message="预约列表加载失败"
          description={appointmentsError}
          action={
            <Button size="small" onClick={refreshAppointments}>
              重试
            </Button>
          }
        />
      ) : null}

      <Card styles={{ body: { padding: 0 } }}>
        <Table<AdminAppointment>
          rowKey="id"
          columns={appointmentColumns}
          dataSource={appointments}
          loading={appointmentsLoading}
          scroll={{ x: 1400 }}
          onRow={(item) => ({
            style:
              item.status === 'pending'
                ? { background: '#fffbeb' }
                : undefined
          })}
          title={() => (
            <Space size={8} wrap>
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                共 {formatNumber(appointmentTotal)} 条预约
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                浅琥珀行为待完成
              </Typography.Text>
            </Space>
          )}
          locale={{
            emptyText: appointmentsLoading
              ? '正在查询预约…'
              : '暂无符合条件的预约'
          }}
          pagination={{
            current: appointmentPage,
            pageSize: appointmentPageSize,
            total: appointmentTotal,
            showSizeChanger: true,
            pageSizeOptions: ['10', '20', '50'],
            showTotal: (count) => `共 ${count} 条`,
            onChange: (nextPage, nextPageSize) =>
              void loadAppointments({
                ...appointmentQuery,
                page: nextPage,
                page_size: nextPageSize
              })
          }}
        />
      </Card>
    </div>
  )

  const quotasTab = (
    <div>
      <Card className="mb-4">
        <Space size={16} wrap>
          <Input.Search
            value={quotaKeyword}
            onChange={(event) => setQuotaKeyword(event.target.value)}
            onSearch={(value) =>
              void loadQuotas(
                1,
                quotaPageSize,
                value.trim(),
                hasRemainingOnly
              )
            }
            placeholder="手机号、昵称或用户 ID"
            allowClear
            maxLength={100}
            loading={quotasLoading}
            style={{ width: 320 }}
            enterButton={
              <>
                <SearchOutlined /> 查询
              </>
            }
          />
          <Space size={8}>
            <Switch
              size="small"
              checked={hasRemainingOnly}
              onChange={(checked) => {
                setHasRemainingOnly(checked)
                void loadQuotas(
                  1,
                  quotaPageSize,
                  quotaKeyword.trim(),
                  checked
                )
              }}
            />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              只看有剩余次数的学员
            </Typography.Text>
          </Space>
        </Space>
      </Card>

      {quotasError ? (
        <Alert
          type="error"
          showIcon
          className="mb-4"
          message="次数账户加载失败"
          description={quotasError}
          action={
            <Button
              size="small"
              onClick={() =>
                void loadQuotas(
                  quotaPage,
                  quotaPageSize,
                  quotaQuery.keyword,
                  quotaQuery.only
                )
              }
            >
              重试
            </Button>
          }
        />
      ) : null}

      <Card styles={{ body: { padding: 0 } }}>
        <Table<AdminAppointmentQuota>
          rowKey="quota_id"
          columns={quotaColumns}
          dataSource={quotas}
          loading={quotasLoading}
          scroll={{ x: 1000 }}
          title={() => (
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              共 {formatNumber(quotaTotal)} 个次数账户
            </Typography.Text>
          )}
          locale={{
            emptyText: quotasLoading ? '正在查询次数账户…' : '暂无次数账户'
          }}
          pagination={{
            current: quotaPage,
            pageSize: quotaPageSize,
            total: quotaTotal,
            showSizeChanger: true,
            pageSizeOptions: ['10', '20', '50'],
            showTotal: (count) => `共 ${count} 个`,
            onChange: (nextPage, nextPageSize) =>
              void loadQuotas(
                nextPage,
                nextPageSize,
                quotaQuery.keyword,
                quotaQuery.only
              )
          }}
        />
      </Card>
    </div>
  )

  return (
    <div>
      <AdminPageHeader
        eyebrow="APPOINTMENTS"
        title="指导预约"
        description="管理专项指导预约与学员预约次数。完成不退还次数，取消会退还 1 次；后台可手工分配或回收剩余次数，每次变动均写入流水。"
        extra={
          <>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={openHeaderGrant}
            >
              分配预约次数
            </Button>
            <Button
              icon={<ReloadOutlined />}
              loading={appointmentsLoading || quotasLoading}
              onClick={refreshAppointments}
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
        message="预约状态机"
        description="待完成 → 标记完成（不退还次数）或 取消（退还 1 次，记录不再展示）。到期未处理的预约可由后续任务标记为已过期，过期不退还次数。"
      />

      <Tabs
        activeKey={activeTab}
        onChange={handleTabChange}
        items={[
          {
            key: 'appointments',
            label: '预约管理',
            children: appointmentsTab
          },
          {
            key: 'quotas',
            label: '次数账户',
            children: quotasTab
          }
        ]}
      />

      <Modal
        open={completeModal.appointment !== null}
        title="确认预约完成"
        width={420}
        okText="标记完成"
        cancelText="取消"
        confirmLoading={completeModal.submitting}
        onOk={() => void submitComplete()}
        onCancel={() => {
          if (!completeModal.submitting) {
            setCompleteModal({
              appointment: null,
              remark: '',
              submitting: false,
              error: null
            })
          }
        }}
        destroyOnClose
      >
        {completeModal.appointment ? (
          <div>
            <Descriptions
              size="small"
              column={1}
              style={{ marginBottom: 14 }}
              items={[
                {
                  key: 'no',
                  label: '预约号',
                  children: completeModal.appointment.appointment_no
                },
                {
                  key: 'time',
                  label: '时段',
                  children: `${completeModal.appointment.appointment_date} ${completeModal.appointment.start_time} - ${completeModal.appointment.end_time}`
                },
                {
                  key: 'user',
                  label: '学员',
                  children:
                    completeModal.appointment.user_nickname ||
                    completeModal.appointment.user_mobile ||
                    `用户 #${completeModal.appointment.user_id}`
                }
              ]}
            />
            <Input.TextArea
              rows={3}
              maxLength={255}
              showCount
              value={completeModal.remark}
              onChange={(event) =>
                setCompleteModal((previous) => ({
                  ...previous,
                  remark: event.target.value
                }))
              }
              placeholder="完成备注，选填"
              style={{ resize: 'none' }}
              disabled={completeModal.submitting}
            />
            <Alert
              type="warning"
              showIcon
              style={{ marginTop: 12 }}
              message="标记完成不会退还预约次数。"
            />
            {completeModal.error ? (
              <Alert
                type="error"
                showIcon
                style={{ marginTop: 12 }}
                message="操作失败"
                description={completeModal.error}
              />
            ) : null}
          </div>
        ) : null}
      </Modal>

      <Drawer
        open={detail !== null}
        width={640}
        title="预约详情"
        onClose={() => setDetail(null)}
        extra={
          <Button size="small" onClick={() => setDetail(null)}>
            关闭
          </Button>
        }
      >
        {detail ? (
          <>
            <Descriptions
              bordered
              size="small"
              column={1}
              items={[
                {
                  key: 'no',
                  label: '预约号',
                  children: (
                    <Typography.Text copyable>
                      {detail.appointment_no}
                    </Typography.Text>
                  )
                },
                {
                  key: 'status',
                  label: '状态',
                  children: <AppointmentStatusTag status={detail.status} />
                },
                {
                  key: 'user',
                  label: '学员',
                  children: `${detail.user_nickname || '未设置昵称'} · ${
                    detail.user_mobile || `用户 #${detail.user_id}`
                  }`
                },
                {
                  key: 'date',
                  label: '预约日期',
                  children: `${detail.appointment_date} ${appointmentWeekday(detail.appointment_date)}`
                },
                {
                  key: 'slot',
                  label: '时段',
                  children: `${detail.start_time} - ${detail.end_time}`
                },
                {
                  key: 'user_remark',
                  label: '学员备注',
                  children: detail.user_remark || '—'
                },
                {
                  key: 'admin_remark',
                  label: '后台备注',
                  children: detail.admin_remark || '—'
                },
                {
                  key: 'created',
                  label: '创建时间',
                  children: formatShanghaiDateTime(detail.created_at)
                },
                {
                  key: 'completed',
                  label: '完成时间',
                  children: detail.completed_at
                    ? `${formatShanghaiDateTime(detail.completed_at)} · ${
                        detail.completed_by_name || '—'
                      }`
                    : '—'
                }
              ]}
            />
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 16 }}
              message="时间为业务时间"
              description="预约日期与时段为 Asia/Shanghai 业务墙上时间；创建/完成时间为 UTC，后台统一换算展示。"
            />
          </>
        ) : null}
      </Drawer>

      <Modal
        open={allocateModal.quota !== null}
        title="分配预约次数"
        width={480}
        okText="确认分配"
        cancelText="取消"
        confirmLoading={allocateModal.submitting}
        onOk={() => void submitAllocate()}
        onCancel={() => {
          if (!allocateModal.submitting) {
            setAllocateModal((previous) => ({ ...previous, quota: null }))
          }
        }}
        destroyOnClose
      >
        {allocateModal.quota ? (
          <div>
            <div
              style={{
                padding: 12,
                marginBottom: 14,
                borderRadius: 10,
                background: '#fafaf9',
                border: '1px solid #e7e5e4'
              }}
            >
              <Typography.Text strong>
                {allocateModal.quota.user_nickname || '未设置昵称'}
              </Typography.Text>
              <div style={{ fontSize: 12, color: '#78716c' }}>
                {allocateModal.quota.user_mobile || `用户 #${allocateModal.quota.user_id}`}
                {' · '}当前剩余 {allocateModal.quota.remaining} 次
              </div>
            </div>
            <Form layout="vertical">
              <Form.Item label="分配次数" required>
                <InputNumber
                  min={1}
                  max={MAX_GRANT_COUNT}
                  precision={0}
                  value={allocateModal.count}
                  onChange={(value) =>
                    setAllocateModal((previous) => ({
                      ...previous,
                      count: value
                    }))
                  }
                  style={{ width: '100%' }}
                  disabled={allocateModal.submitting}
                />
              </Form.Item>
              <Form.Item label="备注">
                <Input.TextArea
                  rows={2}
                  maxLength={255}
                  showCount
                  value={allocateModal.remark}
                  onChange={(event) =>
                    setAllocateModal((previous) => ({
                      ...previous,
                      remark: event.target.value
                    }))
                  }
                  placeholder="分配原因，选填"
                  style={{ resize: 'none' }}
                  disabled={allocateModal.submitting}
                />
              </Form.Item>
            </Form>
            {allocateModal.error ? (
              <Alert
                type="error"
                showIcon
                message="分配失败"
                description={allocateModal.error}
              />
            ) : null}
          </div>
        ) : null}
      </Modal>

      <Modal
        open={reclaimModal.quota !== null}
        title="回收预约次数"
        width={480}
        okText="确认回收"
        okButtonProps={{ danger: true }}
        cancelText="取消"
        confirmLoading={reclaimModal.submitting}
        onOk={() => void submitReclaim()}
        onCancel={() => {
          if (!reclaimModal.submitting) {
            setReclaimModal((previous) => ({ ...previous, quota: null }))
          }
        }}
        destroyOnClose
      >
        {reclaimModal.quota ? (
          <div>
            <div
              style={{
                padding: 12,
                marginBottom: 14,
                borderRadius: 10,
                background: '#fafaf9',
                border: '1px solid #e7e5e4'
              }}
            >
              <Typography.Text strong>
                {reclaimModal.quota.user_nickname || '未设置昵称'}
              </Typography.Text>
              <div style={{ fontSize: 12, color: '#78716c' }}>
                {reclaimModal.quota.user_mobile ||
                  `用户 #${reclaimModal.quota.user_id}`}
                {' · '}当前剩余 {reclaimModal.quota.remaining} 次
              </div>
            </div>
            <Form layout="vertical">
              <Form.Item label="回收次数" required>
                <InputNumber
                  min={1}
                  max={reclaimModal.quota.remaining}
                  precision={0}
                  value={reclaimModal.count}
                  onChange={(value) =>
                    setReclaimModal((previous) => ({
                      ...previous,
                      count: value
                    }))
                  }
                  style={{ width: '100%' }}
                  disabled={reclaimModal.submitting}
                />
              </Form.Item>
              <Form.Item label="备注">
                <Input.TextArea
                  rows={2}
                  maxLength={255}
                  showCount
                  value={reclaimModal.remark}
                  onChange={(event) =>
                    setReclaimModal((previous) => ({
                      ...previous,
                      remark: event.target.value
                    }))
                  }
                  placeholder="回收原因，选填"
                  style={{ resize: 'none' }}
                  disabled={reclaimModal.submitting}
                />
              </Form.Item>
            </Form>
            <Alert
              type="warning"
              showIcon
              message="只能回收未使用的剩余次数，已使用次数不会被扣回；回收会写入负数流水。"
            />
            {reclaimModal.error ? (
              <Alert
                type="error"
                showIcon
                style={{ marginTop: 12 }}
                message="回收失败"
                description={reclaimModal.error}
              />
            ) : null}
          </div>
        ) : null}
      </Modal>

      <Drawer
        open={logQuota !== null}
        width={640}
        title="次数变动流水"
        onClose={() => setLogQuota(null)}
        extra={
          <Button size="small" onClick={() => setLogQuota(null)}>
            关闭
          </Button>
        }
      >
        {logQuota ? (
          <>
            <Descriptions
              size="small"
              column={2}
              style={{ marginBottom: 16 }}
              items={[
                {
                  key: 'user',
                  label: '学员',
                  children:
                    logQuota.user_nickname ||
                    logQuota.user_mobile ||
                    `用户 #${logQuota.user_id}`
                },
                {
                  key: 'total',
                  label: '累计 / 已用 / 剩余',
                  children: `${logQuota.total_count} / ${logQuota.used_count} / ${logQuota.remaining}`
                },
                {
                  key: 'remark',
                  label: '账户备注',
                  children: logQuota.remark || '—'
                }
              ]}
            />
            {logsError ? (
              <Alert
                type="error"
                showIcon
                style={{ marginBottom: 12 }}
                message="流水加载失败"
                description={logsError}
              />
            ) : null}
            <Table<AdminAppointmentQuotaLog>
              rowKey="id"
              size="small"
              columns={logColumns}
              dataSource={logs}
              loading={logsLoading}
              pagination={{
                current: logPage,
                pageSize: logPageSize,
                total: logTotal,
                showSizeChanger: false,
                showTotal: (count) => `共 ${count} 条`,
                onChange: (nextPage, nextPageSize) =>
                  void loadLogPage(nextPage, nextPageSize)
              }}
              locale={{
                emptyText: logsLoading ? '正在加载流水…' : '暂无次数变动记录'
              }}
            />
          </>
        ) : null}
      </Drawer>

      <Modal
        open={grantOpen}
        title="分配预约次数"
        width={560}
        footer={
          grant.step === 0 ? (
            <Space>
              <Button onClick={closeHeaderGrant}>取消</Button>
              <Button
                type="primary"
                disabled={!grant.user}
                onClick={() => setGrant((previous) => ({ ...previous, step: 1 }))}
              >
                下一步
              </Button>
            </Space>
          ) : (
            <Space>
              <Button
                disabled={grant.submitting}
                onClick={() => setGrant((previous) => ({ ...previous, step: 0 }))}
              >
                上一步
              </Button>
              <Button
                type="primary"
                loading={grant.submitting}
                onClick={() => void submitHeaderGrant()}
              >
                确认分配
              </Button>
            </Space>
          )
        }
        onCancel={closeHeaderGrant}
        destroyOnClose
      >
        <Steps
          current={grant.step}
          size="small"
          style={{ marginBottom: 20 }}
          items={[{ title: '选择学员' }, { title: '填写次数' }]}
        />

        {grant.step === 0 ? (
          <div>
            <Input.Search
              value={grant.keyword}
              onChange={(event) =>
                setGrant((previous) => ({
                  ...previous,
                  keyword: event.target.value,
                  searchError: null,
                  user: null
                }))
              }
              onSearch={(value) => void searchGrantUser(value)}
              placeholder="输入 11 位手机号或用户 ID"
              maxLength={64}
              allowClear
              size="large"
              loading={grant.searching}
              enterButton={
                <>
                  <SearchOutlined /> 查找学员
                </>
              }
            />
            {grant.searchError ? (
              <Alert
                type="error"
                showIcon
                style={{ marginTop: 12 }}
                message="未找到学员"
                description={grant.searchError}
              />
            ) : null}
            {grant.user ? (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 14,
                  marginTop: 16,
                  padding: 14,
                  border: '1px solid #e7e5e4',
                  borderRadius: 12,
                  background: '#fafaf9'
                }}
              >
                <Avatar
                  size={48}
                  src={grant.user.avatar_url || undefined}
                  style={{ background: '#0d1526', color: '#dbbd7d' }}
                >
                  {userInitial(
                    grant.user.nickname,
                    grant.user.mobile,
                    grant.user.user_id
                  )}
                </Avatar>
                <div style={{ minWidth: 0 }}>
                  <Typography.Text strong>
                    {grant.user.nickname || '未设置昵称'}
                  </Typography.Text>
                  <div style={{ fontSize: 12, color: '#78716c' }}>
                    {grant.user.mobile || '未绑定手机号'} · 用户 #
                    {grant.user.user_id}
                  </div>
                </div>
              </div>
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                style={{ marginTop: 20 }}
                description="先精确查找学员，再分配次数"
              />
            )}
          </div>
        ) : (
          <div>
            {grant.user ? (
              <Typography.Paragraph
                type="secondary"
                style={{ fontSize: 12 }}
              >
                目标学员：{grant.user.nickname || '未设置昵称'}（
                {grant.user.mobile || `用户 #${grant.user.user_id}`}）
              </Typography.Paragraph>
            ) : null}
            <Form layout="vertical">
              <Form.Item label="分配次数" required>
                <InputNumber
                  min={1}
                  max={MAX_GRANT_COUNT}
                  precision={0}
                  value={grant.count}
                  onChange={(value) =>
                    setGrant((previous) => ({ ...previous, count: value }))
                  }
                  style={{ width: '100%' }}
                  disabled={grant.submitting}
                />
              </Form.Item>
              <Form.Item label="备注">
                <Input.TextArea
                  rows={2}
                  maxLength={255}
                  showCount
                  value={grant.remark}
                  onChange={(event) =>
                    setGrant((previous) => ({
                      ...previous,
                      remark: event.target.value
                    }))
                  }
                  placeholder="分配原因，选填"
                  style={{ resize: 'none' }}
                  disabled={grant.submitting}
                />
              </Form.Item>
            </Form>
            {grant.error ? (
              <Alert
                type="error"
                showIcon
                message="分配失败"
                description={grant.error}
              />
            ) : null}
          </div>
        )}
      </Modal>

      <Typography.Paragraph
        type="secondary"
        style={{ marginTop: 14, fontSize: 11, lineHeight: '20px' }}
      >
        预约次数由购买课程、后台赠课或手工分配产生；完成预约不退还次数，
        学员或管理员取消预约会退还 1 次。后台可按剩余次数手工回收，回收只
        减少累计、不改已用；剩余次数 = 累计 - 已用，始终实时计算。
      </Typography.Paragraph>
    </div>
  )
}
