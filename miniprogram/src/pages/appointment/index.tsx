import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Button,
  ScrollView,
  Text,
  Textarea,
  View
} from '@tarojs/components'
import Taro, { usePullDownRefresh, useReachBottom } from '@tarojs/taro'

import MockModeBadge from '../../components/MockModeBadge'
import WxAuthSheet from '../../components/WxAuthSheet'
import { DEFAULT_PAGE_SIZE } from '../../constants'
import { useRequireAuth } from '../../hooks/useRequireAuth'
import {
  cancelAppointment,
  createAppointment,
  getAppointmentOverview,
  getAvailableSlots,
  getMyAppointments
} from '../../services/appointmentApi'
import { ApiError, getErrorMessage } from '../../services/request'
import { useAppSelector } from '../../store/hooks'
import type {
  AppointmentAvailableSlots,
  AppointmentItem,
  AppointmentOverview,
  AppointmentSlot,
  AppointmentStatus
} from '../../types'

import './index.scss'

type FilterStatus = 'all' | 'pending' | 'completed'
type LoadStatus = 'idle' | 'loading' | 'ready' | 'error'

const FILTER_OPTIONS: Array<{ value: FilterStatus; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'pending', label: '待完成' },
  { value: 'completed', label: '已完成' }
]

const STATUS_LABELS: Record<AppointmentStatus, string> = {
  pending: '待完成',
  completed: '已完成',
  expired: '已过期'
}

const WEEKDAY_LABELS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

const APPOINTMENT_ERROR_MESSAGES: Record<string, string> = {
  APPOINTMENT_DISABLED: '当前暂未开放预约，请稍后再试',
  APPOINTMENT_DATE_INVALID: '预约日期无效，请重新选择',
  APPOINTMENT_SLOT_INVALID: '预约时段无效，请刷新后重新选择',
  APPOINTMENT_ADVANCE_REQUIRED: '该时段需要提前更长时间预约，请选择更晚的时段',
  APPOINTMENT_DUPLICATE: '该时段你已预约',
  APPOINTMENT_QUOTA_INSUFFICIENT: '可预约次数不足',
  APPOINTMENT_SLOT_FULL: '该时段已被约满，请选择其他时段',
  APPOINTMENT_STATUS_INVALID: '当前状态不可操作',
  APPOINTMENT_CANCEL_TOO_LATE: '已超过可取消时限，无法取消',
  APPOINTMENT_NOT_FOUND: '预约记录不存在'
}

function resolveAppointmentError(error: unknown): string {
  if (error instanceof ApiError) {
    const mapped = APPOINTMENT_ERROR_MESSAGES[error.code]
    if (mapped) {
      return mapped
    }
  }
  return getErrorMessage(error)
}

function parseDateParts(date: string): [number, number, number] | null {
  const parts = date.split('-').map(Number)
  if (parts.length !== 3 || parts.some((part) => !Number.isInteger(part))) {
    return null
  }
  return [parts[0], parts[1], parts[2]]
}

function formatMonthDay(date: string): string {
  return date.slice(5)
}

function weekdayLabel(date: string): string {
  const parts = parseDateParts(date)
  if (!parts) {
    return ''
  }
  const [year, month, day] = parts
  return WEEKDAY_LABELS[new Date(year, month - 1, day).getDay()] || ''
}

function slotLabel(slot: AppointmentSlot): string {
  return `${slot.start_time} - ${slot.end_time}`
}

/** 预约开始时间（北京时间）转为毫秒时间戳。 */
function appointmentStartMs(date: string, startTime: string): number {
  const parts = parseDateParts(date)
  const timeParts = startTime.split(':').map(Number)
  if (!parts || timeParts.length < 2) {
    return Number.NaN
  }
  const [year, month, day] = parts
  const [hour, minute] = timeParts
  if (
    !Number.isInteger(hour) ||
    !Number.isInteger(minute) ||
    hour < 0 ||
    hour > 23 ||
    minute < 0 ||
    minute > 59
  ) {
    return Number.NaN
  }
  // 业务时间固定 UTC+8，存储为无时区自然时间。
  return Date.UTC(year, month - 1, day, hour - 8, minute)
}

function isCancelable(item: AppointmentItem, minAdvanceHours: number): boolean {
  if (item.status !== 'pending') {
    return false
  }
  const start = appointmentStartMs(item.appointment_date, item.start_time)
  return (
    Number.isFinite(start) &&
    start - Date.now() >= minAdvanceHours * 60 * 60 * 1000
  )
}

export default function AppointmentPage() {
  const { openLogin } = useRequireAuth()
  const token = useAppSelector((state) => state.user.token)
  const isMockLogin = useAppSelector((state) => state.user.isMockLogin)
  const mountedRef = useRef(true)
  const overviewSeq = useRef(0)
  const listSeq = useRef(0)
  const slotsSeq = useRef(0)

  const [overview, setOverview] = useState<AppointmentOverview | null>(null)
  const [overviewStatus, setOverviewStatus] = useState<LoadStatus>('idle')
  const [overviewError, setOverviewError] = useState('')

  const [items, setItems] = useState<AppointmentItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [filter, setFilter] = useState<FilterStatus>('all')
  const [listStatus, setListStatus] = useState<LoadStatus>('idle')
  const [listError, setListError] = useState('')
  const [cancellingNo, setCancellingNo] = useState<string | null>(null)

  const [sheetVisible, setSheetVisible] = useState(false)
  const [slots, setSlots] = useState<AppointmentAvailableSlots | null>(null)
  const [slotsStatus, setSlotsStatus] = useState<LoadStatus>('idle')
  const [slotsError, setSlotsError] = useState('')
  const [selectedDate, setSelectedDate] = useState('')
  const [selectedStart, setSelectedStart] = useState('')
  const [remark, setRemark] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      overviewSeq.current += 1
      listSeq.current += 1
      slotsSeq.current += 1
    }
  }, [])

  const loadOverview = useCallback(async () => {
    const seq = overviewSeq.current + 1
    overviewSeq.current = seq
    setOverviewStatus('loading')
    setOverviewError('')
    try {
      const data = await getAppointmentOverview()
      if (!mountedRef.current || seq !== overviewSeq.current) {
        return
      }
      setOverview(data)
      setOverviewStatus('ready')
    } catch (error) {
      if (!mountedRef.current || seq !== overviewSeq.current) {
        return
      }
      setOverviewError(resolveAppointmentError(error))
      setOverviewStatus('error')
    }
  }, [])

  const loadList = useCallback(async (nextPage: number, status: FilterStatus) => {
    const seq = listSeq.current + 1
    listSeq.current = seq
    setListStatus('loading')
    setListError('')
    try {
      const data = await getMyAppointments({
        status: status === 'all' ? undefined : status,
        page: nextPage,
        pageSize: DEFAULT_PAGE_SIZE
      })
      if (!mountedRef.current || seq !== listSeq.current) {
        return
      }
      setItems((previous) =>
        nextPage > 1 ? [...previous, ...data.items] : data.items
      )
      setTotal(data.total)
      setPage(data.page)
      setHasMore(data.page * data.page_size < data.total)
      setListStatus('ready')
    } catch (error) {
      if (!mountedRef.current || seq !== listSeq.current) {
        return
      }
      setListError(resolveAppointmentError(error))
      setListStatus('error')
    }
  }, [])

  useEffect(() => {
    if (!token) {
      setOverview(null)
      setOverviewStatus('idle')
      setOverviewError('')
      setItems([])
      setTotal(0)
      setPage(1)
      setHasMore(false)
      setListStatus('idle')
      setListError('')
      setFilter('all')
      return
    }
    void loadOverview()
  }, [loadOverview, token])

  useEffect(() => {
    if (!token) {
      return
    }
    void loadList(1, filter)
  }, [filter, loadList, token])

  usePullDownRefresh(() => {
    if (!token) {
      void Taro.stopPullDownRefresh()
      return
    }
    void Promise.all([
      loadOverview(),
      loadList(1, filter)
    ]).finally(() => {
      void Taro.stopPullDownRefresh()
    })
  })

  useReachBottom(() => {
    if (
      !token ||
      !hasMore ||
      listStatus === 'loading' ||
      page < 1
    ) {
      return
    }
    void loadList(page + 1, filter)
  })

  const refreshAfterChange = () => {
    void loadOverview()
    if (filter === 'all') {
      void loadList(1, filter)
      return
    }
    setItems([])
    setTotal(0)
    setPage(1)
    setHasMore(false)
    setFilter('all')
  }

  const handleFilterChange = (next: FilterStatus) => {
    if (next === filter) {
      return
    }
    setItems([])
    setTotal(0)
    setPage(1)
    setHasMore(false)
    setFilter(next)
  }

  const loadSlots = useCallback(async (date?: string) => {
    const seq = slotsSeq.current + 1
    slotsSeq.current = seq
    setSlotsStatus('loading')
    setSlotsError('')
    setSelectedStart('')
    try {
      let data = await getAvailableSlots(date)
      if (!mountedRef.current || seq !== slotsSeq.current) {
        return
      }
      let targetDate = date ?? data.date
      if (!date) {
        const firstAvailable = data.dates.find((item) => item.has_available)
        if (firstAvailable && firstAvailable.date !== data.date) {
          data = await getAvailableSlots(firstAvailable.date)
          if (!mountedRef.current || seq !== slotsSeq.current) {
            return
          }
          targetDate = data.date
        }
      }
      setSlots(data)
      setSelectedDate(targetDate)
      setSlotsStatus('ready')
    } catch (error) {
      if (!mountedRef.current || seq !== slotsSeq.current) {
        return
      }
      setSlotsError(resolveAppointmentError(error))
      setSlotsStatus('error')
    }
  }, [])

  const openSheet = () => {
    if ((overview?.remaining_total ?? 0) <= 0) {
      void Taro.showToast({
        title: '暂无可预约次数，购课或联系老师获取',
        icon: 'none'
      })
      return
    }
    setSheetVisible(true)
    setSlots(null)
    setSelectedDate('')
    setSelectedStart('')
    setRemark('')
    setSubmitError('')
    setSlotsStatus('loading')
    void loadSlots()
  }

  const closeSheet = () => {
    if (submitting) {
      return
    }
    slotsSeq.current += 1
    setSheetVisible(false)
  }

  const handleSelectDate = (date: string) => {
    if (slotsStatus === 'loading') {
      return
    }
    if (date === selectedDate && slotsStatus === 'ready') {
      return
    }
    setSelectedDate(date)
    setSelectedStart('')
    void loadSlots(date)
  }

  const handleSubmit = async () => {
    if (submitting) {
      return
    }
    if (!selectedDate) {
      setSubmitError('请选择预约日期')
      return
    }
    if (!selectedStart) {
      setSubmitError('请选择预约时段')
      return
    }
    if (slots && !slots.enabled) {
      setSubmitError(APPOINTMENT_ERROR_MESSAGES.APPOINTMENT_DISABLED)
      return
    }
    if ((overview?.remaining_total ?? 0) <= 0) {
      setSubmitError(APPOINTMENT_ERROR_MESSAGES.APPOINTMENT_QUOTA_INSUFFICIENT)
      return
    }
    const remarkValue = remark.trim()
    setSubmitting(true)
    setSubmitError('')
    try {
      const result = await createAppointment({
        appointment_date: selectedDate,
        start_time: selectedStart,
        user_remark: remarkValue || undefined
      })
      if (!mountedRef.current) {
        return
      }
      setSheetVisible(false)
      setRemark('')
      void Taro.showToast({
        title: result.message || '预约成功，请按时参加',
        icon: 'none',
        duration: 2000
      })
      refreshAfterChange()
    } catch (error) {
      if (!mountedRef.current) {
        return
      }
      setSubmitError(resolveAppointmentError(error))
    } finally {
      if (mountedRef.current) {
        setSubmitting(false)
      }
    }
  }

  const handleCancel = async (item: AppointmentItem) => {
    if (cancellingNo) {
      return
    }
    const result = await Taro.showModal({
      title: '取消预约',
      content: `${formatMonthDay(item.appointment_date)} ${weekdayLabel(
        item.appointment_date
      )} ${item.start_time} - ${item.end_time} 的预约。取消后将退还 1 次预约次数。`,
      confirmText: '确认取消',
      cancelText: '再想想',
      confirmColor: '#a37632'
    })
    if (!result.confirm) {
      return
    }
    setCancellingNo(item.appointment_no)
    try {
      const response = await cancelAppointment(item.appointment_no)
      if (!mountedRef.current) {
        return
      }
      setItems((previous) =>
        previous.filter(
          (appointment) => appointment.appointment_no !== item.appointment_no
        )
      )
      setTotal((previous) => Math.max(0, previous - 1))
      void Taro.showToast({
        title: response.message || '已取消预约，已退还1次预约次数',
        icon: 'none',
        duration: 2000
      })
      refreshAfterChange()
    } catch (error) {
      if (!mountedRef.current) {
        return
      }
      void Taro.showToast({
        title: resolveAppointmentError(error),
        icon: 'none'
      })
    } finally {
      if (mountedRef.current) {
        setCancellingNo(null)
      }
    }
  }

  const remaining = overview?.remaining_total ?? 0
  const cancelWindowHours = overview?.min_advance_hours ?? 24
  const canSubmit =
    Boolean(selectedDate && selectedStart) &&
    slots?.enabled !== false &&
    !submitting

  const renderSkeleton = () => (
    <View>
      <View className='appointment-skeleton appointment-skeleton--quota' />
      <View className='appointment-skeleton appointment-skeleton--line' />
      <View className='appointment-skeleton appointment-skeleton--card' />
      <View className='appointment-skeleton appointment-skeleton--card' />
    </View>
  )

  const renderOverviewError = () => (
    <View className='state-block'>
      <Text>
        {isMockLogin
          ? '测试模式下预约接口可能返回 401，暂不加载预约次数'
          : overviewError || '预约次数加载失败'}
      </Text>
      <Text className='state-block__action' onClick={() => void loadOverview()}>
        重新加载
      </Text>
    </View>
  )

  const renderQuotaCard = () => {
    if (!overview) {
      return null
    }
    return (
      <View className='appointment-quota'>
        <View className='appointment-quota__glow' />
        <Text className='appointment-quota__eyebrow'>APPOINTMENT CREDITS</Text>
        <View className='appointment-quota__head'>
          <View className='appointment-quota__main'>
            <Text className='appointment-quota__label'>剩余可预约次数</Text>
            <View className='appointment-quota__value-row'>
              <Text className='appointment-quota__value'>
                {overview.remaining_total}
              </Text>
              <Text className='appointment-quota__unit'>次</Text>
            </View>
            <Text className='appointment-quota__sub'>
              累计获得 {overview.purchased_total} 次 / 已使用{' '}
              {overview.used_total} 次
            </Text>
          </View>
          <Button
            className={`appointment-quota__button ${
              remaining <= 0 ? 'appointment-quota__button--disabled' : ''
            }`}
            disabled={remaining <= 0}
            onClick={openSheet}
          >
            新增预约
          </Button>
        </View>
        {remaining <= 0 ? (
          <Text className='appointment-quota__hint'>
            暂无可用次数，购课或联系老师获取
          </Text>
        ) : null}
        <View className='appointment-quota__stats'>
          <Text className='appointment-quota__stat'>
            待完成 {overview.pending_count}
          </Text>
          <Text className='appointment-quota__stat'>
            已完成 {overview.completed_count}
          </Text>
        </View>
      </View>
    )
  }

  const renderAppointmentCard = (item: AppointmentItem) => {
    const cancelable = isCancelable(item, cancelWindowHours)
    return (
      <View key={item.appointment_no} className='appointment-card'>
        <View className='appointment-card__date'>
          <Text className='appointment-card__day'>
            {formatMonthDay(item.appointment_date)}
          </Text>
          <Text className='appointment-card__weekday'>
            {weekdayLabel(item.appointment_date)}
          </Text>
        </View>
        <View className='appointment-card__body'>
          <View className='appointment-card__top'>
            <Text className='appointment-card__time'>
              {item.start_time} - {item.end_time}
            </Text>
            <Text
              className={`appointment-card__status appointment-card__status--${item.status}`}
            >
              {STATUS_LABELS[item.status]}
            </Text>
          </View>
          <Text className='appointment-card__title'>专项指导</Text>
          {item.user_remark ? (
            <Text className='appointment-card__remark'>
              备注：{item.user_remark}
            </Text>
          ) : null}
          {item.admin_remark ? (
            <Text className='appointment-card__remark appointment-card__remark--admin'>
              老师留言：{item.admin_remark}
            </Text>
          ) : null}
          {item.status === 'pending' ? (
            <View className='appointment-card__actions'>
              {cancelable ? (
                <Text
                  className={`appointment-card__cancel ${
                    cancellingNo === item.appointment_no
                      ? 'appointment-card__cancel--busy'
                      : ''
                  }`}
                  onClick={() => {
                    if (!cancellingNo) {
                      void handleCancel(item)
                    }
                  }}
                >
                  {cancellingNo === item.appointment_no
                    ? '取消中…'
                    : '取消预约'}
                </Text>
              ) : (
                <Text className='appointment-card__locked'>
                  距开始不足{cancelWindowHours}小时，不可取消
                </Text>
              )}
            </View>
          ) : null}
        </View>
      </View>
    )
  }

  const renderEmpty = () => {
    if (filter !== 'all') {
      return (
        <View className='state-block'>
          <Text>当前筛选下暂无预约记录</Text>
          <Text
            className='state-block__action'
            onClick={() => handleFilterChange('all')}
          >
            查看全部
          </Text>
        </View>
      )
    }
    return (
      <View className='appointment-empty'>
        <Text className='appointment-empty__icon'>🗓️</Text>
        <Text className='appointment-empty__title'>还没有预约</Text>
        <Text className='appointment-empty__desc'>
          点击上方新增一次专项指导
        </Text>
        <Button
          className={`appointment-empty__button ${
            remaining <= 0 ? 'appointment-empty__button--disabled' : ''
          }`}
          disabled={remaining <= 0}
          onClick={openSheet}
        >
          新增预约
        </Button>
        {remaining <= 0 ? (
          <Text className='appointment-empty__hint'>
            暂无可预约次数，购课或联系老师获取
          </Text>
        ) : null}
      </View>
    )
  }

  const renderList = () => {
    if (listStatus === 'loading' && !items.length) {
      return (
        <View>
          <View className='appointment-skeleton appointment-skeleton--card' />
          <View className='appointment-skeleton appointment-skeleton--card' />
        </View>
      )
    }
    if (listStatus === 'error' && !items.length) {
      return (
        <View className='state-block'>
          <Text>
            {isMockLogin
              ? '测试模式下预约接口可能返回 401，暂不加载预约记录'
              : listError || '预约记录加载失败'}
          </Text>
          <Text
            className='state-block__action'
            onClick={() => void loadList(1, filter)}
          >
            重新加载
          </Text>
        </View>
      )
    }
    if (!items.length) {
      return renderEmpty()
    }
    return (
      <View>
        {items.map((item) => renderAppointmentCard(item))}
        {listStatus === 'loading' ? (
          <View className='loading-line'>正在加载更多预约…</View>
        ) : null}
        {!hasMore ? (
          <View className='appointment-page__end'>已展示全部预约</View>
        ) : null}
      </View>
    )
  }

  const renderSheetDates = () => {
    if (!slots?.dates.length) {
      if (slotsStatus === 'loading') {
        return <View className='loading-line'>正在加载可预约日期…</View>
      }
      return null
    }
    return (
      <ScrollView
        className='appointment-sheet__dates'
        scrollX
        enhanced
        showScrollbar={false}
      >
        <View className='appointment-sheet__dates-track'>
          {slots.dates.map((item) => {
            const active = item.date === selectedDate
            return (
              <View
                key={item.date}
                className={`appointment-sheet__date ${
                  item.has_available
                    ? ''
                    : 'appointment-sheet__date--disabled'
                } ${active ? 'appointment-sheet__date--active' : ''}`}
                onClick={() => {
                  if (item.has_available) {
                    handleSelectDate(item.date)
                  }
                }}
              >
                <Text className='appointment-sheet__date-week'>
                  {weekdayLabel(item.date)}
                </Text>
                <Text className='appointment-sheet__date-day'>
                  {formatMonthDay(item.date)}
                </Text>
                <Text className='appointment-sheet__date-state'>
                  {item.has_available ? (active ? '已选' : '可约') : '约满'}
                </Text>
              </View>
            )
          })}
        </View>
      </ScrollView>
    )
  }

  const renderSheetSlots = () => {
    if (slotsStatus === 'loading') {
      return <View className='loading-line'>正在加载可预约时段…</View>
    }
    if (slotsStatus === 'error') {
      return (
        <View className='state-block'>
          <Text>{slotsError || '可预约时段加载失败'}</Text>
          <Text
            className='state-block__action'
            onClick={() => void loadSlots(selectedDate || undefined)}
          >
            重新加载
          </Text>
        </View>
      )
    }
    if (slots && !slots.enabled) {
      return (
        <View className='state-block'>
          当前暂未开放预约，请联系老师或稍后再试
        </View>
      )
    }
    if (!slots || !slots.slots.length) {
      return <View className='state-block'>当天暂无可预约时段</View>
    }
    return (
      <View className='appointment-sheet__slots'>
        {slots.slots.map((slot) => {
          const full = slot.available <= 0
          const active = slot.start_time === selectedStart
          return (
            <View
              key={slot.start_time}
              className={`appointment-sheet__slot ${
                full ? 'appointment-sheet__slot--disabled' : ''
              } ${active ? 'appointment-sheet__slot--active' : ''}`}
              onClick={() => {
                if (!full) {
                  setSelectedStart(slot.start_time)
                  setSubmitError('')
                }
              }}
            >
              <Text className='appointment-sheet__slot-time'>
                {slotLabel(slot)}
              </Text>
              <Text className='appointment-sheet__slot-meta'>
                {full ? '已满' : '可预约'}
              </Text>
            </View>
          )
        })}
      </View>
    )
  }

  return (
    <View className='page appointment-page'>
      <MockModeBadge />

      <View className='section appointment-page__header'>
        <Text className='appointment-page__eyebrow'>MY APPOINTMENTS</Text>
        <Text className='appointment-page__heading'>我的预约</Text>
        <Text className='appointment-page__sub'>
          预约一次专项指导，把问题聊透
        </Text>
      </View>

      {!token ? (
        <View className='section'>
          <View className='appointment-login'>
            <Text className='appointment-login__title'>登录后查看我的预约</Text>
            <Text className='appointment-login__desc'>
              登录后即可预约专项指导、查看剩余次数与预约记录。
            </Text>
            <Button
              className='appointment-login__button'
              onClick={() => openLogin('登录后即可预约专项指导')}
            >
              手机号快捷登录
            </Button>
          </View>
        </View>
      ) : (
        <>
          <View className='section'>
            {overviewStatus === 'loading' && !overview
              ? renderSkeleton()
              : overviewStatus === 'error' && !overview
                ? renderOverviewError()
                : renderQuotaCard()}
          </View>

          <View className='section appointment-page__list'>
            <View className='section-head appointment-page__list-head'>
              <Text className='section-title'>预约记录</Text>
              <Text className='appointment-page__count'>共 {total} 条</Text>
            </View>

            <ScrollView
              className='appointment-filter'
              scrollX
              enhanced
              showScrollbar={false}
            >
              <View className='appointment-filter__track'>
                {FILTER_OPTIONS.map((option) => (
                  <Text
                    key={option.value}
                    className={`appointment-filter__item ${
                      option.value === filter
                        ? 'appointment-filter__item--active'
                        : ''
                    }`}
                    onClick={() => handleFilterChange(option.value)}
                  >
                    {option.label}
                  </Text>
                ))}
              </View>
            </ScrollView>

            {renderList()}
          </View>
        </>
      )}

      {sheetVisible ? (
        <View className='appointment-sheet'>
          <View
            className='appointment-sheet__backdrop'
            onClick={closeSheet}
          />
          <View className='appointment-sheet__panel'>
            <View className='appointment-sheet__header'>
              <View className='appointment-sheet__heading'>
                <Text className='appointment-sheet__title'>新增专项指导预约</Text>
                <Text className='appointment-sheet__sub'>
                  选择日期与时段，提交后立即扣减 1 次
                </Text>
              </View>
              <Text className='appointment-sheet__close' onClick={closeSheet}>
                ×
              </Text>
            </View>

            <ScrollView scrollY className='appointment-sheet__scroll'>
              <View className='appointment-sheet__content'>
                <Text className='appointment-sheet__label'>预约日期</Text>
                {renderSheetDates()}

                <Text className='appointment-sheet__label'>预约时段</Text>
                {renderSheetSlots()}

                <Text className='appointment-sheet__label'>备注（选填）</Text>
                <Textarea
                  className='appointment-sheet__textarea'
                  value={remark}
                  maxlength={255}
                  placeholder='想重点解决的问题，选填'
                  placeholderClass='appointment-sheet__placeholder'
                  onInput={(event) => setRemark(event.detail.value)}
                />

                {submitError ? (
                  <Text className='appointment-sheet__error'>{submitError}</Text>
                ) : null}
              </View>
            </ScrollView>

            <View className='appointment-sheet__footer'>
              <View className='appointment-sheet__cost'>
                <Text className='appointment-sheet__cost-label'>
                  本次消耗 1 次预约次数
                </Text>
                <Text className='appointment-sheet__cost-value'>
                  剩余 {remaining} 次
                </Text>
              </View>
              <Button
                className={`appointment-sheet__confirm ${
                  canSubmit ? '' : 'appointment-sheet__confirm--disabled'
                }`}
                disabled={!canSubmit}
                loading={submitting}
                onClick={() => void handleSubmit()}
              >
                确认预约
              </Button>
            </View>
          </View>
        </View>
      ) : null}

      <WxAuthSheet />
    </View>
  )
}
