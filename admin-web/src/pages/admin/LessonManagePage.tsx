import {
  useCallback,
  useEffect,
  useMemo,
  useState
} from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  HolderOutlined,
  PlusOutlined,
  ReloadOutlined,
  VideoCameraAddOutlined
} from '@ant-design/icons'

import { getAdminCourse } from '../../api/courseApi'
import { listVodMedia, syncVodMediaStatus } from '../../api/mediaApi'
import { getErrorMessage } from '../../api/request'
import AdminCourseSelect from '../../components/admin/CourseSelect'
import AdminPageHeader from '../../components/admin/PageHeader'
import { MediaStatusTag } from '../../components/admin/StatusTags'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  clearLessons,
  createLesson,
  deleteLesson,
  fetchLessons,
  selectLessonManage,
  updateLesson
} from '../../store/slices/lessonManageSlice'
import type { Lesson, VodMedia } from '../../types'
import { formatDateTime, formatDuration } from '../../utils/format'
import { parsePositiveInt } from '../../utils/validation'

const PICKER_PAGE_SIZE = 8
const PICKER_POLL_INTERVAL_MS = 8000

interface VideoSelection {
  file_id: string
  video_name: string | null
  duration_seconds: number
}

interface LessonFormValues {
  title: string
  sort_order: number | null
}

interface VideoPickerModalProps {
  open: boolean
  selected: VideoSelection | null
  canManage: boolean
  onClose: () => void
  onConfirm: (selection: VideoSelection) => void
}

function VideoPickerModal({
  open,
  selected,
  canManage,
  onClose,
  onConfirm
}: VideoPickerModalProps) {
  const [items, setItems] = useState<VodMedia[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [keyword, setKeyword] = useState('')
  const [picked, setPicked] = useState<VideoSelection | null>(selected)

  const load = useCallback(async (nextPage: number, nextKeyword: string) => {
    setLoading(true)
    setError(null)
    try {
      const response = await listVodMedia({
        page: nextPage,
        page_size: PICKER_PAGE_SIZE,
        keyword: nextKeyword.trim() || undefined
      })
      setItems(response.items)
      setTotal(response.total)
      setPage(response.page)
    } catch (loadError) {
      setError(getErrorMessage(loadError))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!open) {
      return
    }
    setPicked(selected)
    setKeyword('')
    setItems([])
    setTotal(0)
    setPage(1)
    void load(1, '')
  }, [open, selected, load])

  const pendingIds = items
    .filter((item) => item.status === 0)
    .map((item) => item.id)
  const pendingKey = pendingIds.join(',')

  useEffect(() => {
    if (!open || !canManage || !pendingKey) {
      return
    }
    const timer = window.setInterval(() => {
      void syncVodMediaStatus({ media_ids: pendingKey.split(',').map(Number) })
        .catch(() => undefined)
        .finally(() => void load(page, keyword))
    }, PICKER_POLL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [open, canManage, pendingKey, page, keyword, load])

  const columns: ColumnsType<VodMedia> = [
    {
      title: '视频',
      key: 'video',
      render: (_value, media) => (
        <div>
          <Typography.Text strong>{media.video_name}</Typography.Text>
          <div style={{ fontSize: 11, color: '#a8a29e' }}>
            {media.file_id}
          </div>
        </div>
      )
    },
    {
      title: '时长',
      dataIndex: 'duration_seconds',
      key: 'duration',
      width: 90,
      render: (value: number) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {formatDuration(value)}
        </Typography.Text>
      )
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (_value, media) => <MediaStatusTag status={media.status} />
    }
  ]

  return (
    <Modal
      open={open}
      title="选择视频"
      width={720}
      onCancel={onClose}
      okText="确认选择"
      cancelText="取消"
      okButtonProps={{ disabled: !picked }}
      onOk={() => {
        if (picked) {
          onConfirm(picked)
        }
      }}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="视频来自媒资库，同一视频可被多个课时复用。只有「可用」状态的视频可以绑定。"
      />

      <Input.Search
        allowClear
        placeholder="按视频名称搜索媒资库"
        maxLength={100}
        value={keyword}
        onChange={(event) => setKeyword(event.target.value)}
        onSearch={(value) => void load(1, value)}
        style={{ marginBottom: 12 }}
      />

      {error ? (
        <Alert
          type="error"
          showIcon
          message={error}
          style={{ marginBottom: 12 }}
          action={
            <Button size="small" onClick={() => void load(page, keyword)}>
              重试
            </Button>
          }
        />
      ) : null}

      <Table<VodMedia>
        rowKey="file_id"
        size="small"
        columns={columns}
        dataSource={items}
        loading={loading}
        rowSelection={{
          type: 'radio',
          selectedRowKeys: picked ? [picked.file_id] : [],
          getCheckboxProps: (record) => ({
            disabled: record.status !== 1
          }),
          onChange: (_keys, rows) => {
            const media = rows[0]
            if (!media) {
              return
            }
            setPicked({
              file_id: media.file_id,
              video_name: media.video_name,
              duration_seconds: media.duration_seconds
            })
          }
        }}
        onRow={(record) => ({
          onClick: () => {
            if (record.status === 1) {
              setPicked({
                file_id: record.file_id,
                video_name: record.video_name,
                duration_seconds: record.duration_seconds
              })
            }
          },
          style: {
            cursor: record.status === 1 ? 'pointer' : 'not-allowed'
          }
        })}
        locale={{ emptyText: loading ? '正在加载媒资…' : '媒资库暂无视频' }}
        pagination={{
          current: page,
          pageSize: PICKER_PAGE_SIZE,
          total,
          showSizeChanger: false,
          onChange: (nextPage) => void load(nextPage, keyword)
        }}
      />

      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {picked
          ? `已选：${picked.video_name || picked.file_id} · ${formatDuration(picked.duration_seconds)}`
          : '请选择一个可用视频'}
      </Typography.Text>
    </Modal>
  )
}

export default function LessonManagePage() {
  const dispatch = useAppDispatch()
  const { message } = AntdApp.useApp()
  const [searchParams, setSearchParams] = useSearchParams()
  const initialParam = searchParams.get('courseId')
  const initialCourseId = initialParam ? parsePositiveInt(initialParam) : null

  const [courseId, setCourseId] = useState<number | null>(initialCourseId)
  const [courseTitle, setCourseTitle] = useState('')
  const [nameFilter, setNameFilter] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [editingLesson, setEditingLesson] = useState<Lesson | null>(null)
  const [selectedVideo, setSelectedVideo] = useState<VideoSelection | null>(
    null
  )
  const [videoError, setVideoError] = useState<string | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [form] = Form.useForm<LessonFormValues>()

  const { items, loading, error, saving } = useAppSelector(selectLessonManage)
  const role = useAppSelector((state) => state.adminAuth.admin?.role)
  const canManage = role === 'super'

  useEffect(() => {
    if (courseId) {
      void dispatch(fetchLessons(courseId))
    } else {
      dispatch(clearLessons())
    }
  }, [courseId, dispatch])

  useEffect(() => {
    if (!courseId) {
      setCourseTitle('')
      return
    }
    let cancelled = false
    getAdminCourse(courseId)
      .then((course) => {
        if (!cancelled) {
          setCourseTitle(course.title)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCourseTitle(`课程 #${courseId}`)
        }
      })
    return () => {
      cancelled = true
    }
  }, [courseId])

  const visibleLessons = useMemo(() => {
    const query = nameFilter.trim().toLowerCase()
    if (!query) {
      return items
    }
    return items.filter((lesson) =>
      lesson.title.toLowerCase().includes(query)
    )
  }, [items, nameFilter])

  const handleCourseChange = (nextCourseId: number | null) => {
    setCourseId(nextCourseId)
    setFormOpen(false)
    setEditingLesson(null)
    setNameFilter('')
    if (nextCourseId) {
      setSearchParams({ courseId: String(nextCourseId) }, { replace: true })
    } else {
      setSearchParams({}, { replace: true })
    }
  }

  const openCreate = () => {
    setEditingLesson(null)
    setSelectedVideo(null)
    setVideoError(null)
    setFormOpen(true)
  }

  const openEdit = (lesson: Lesson) => {
    setEditingLesson(lesson)
    setSelectedVideo(
      lesson.file_id
        ? {
            file_id: lesson.file_id,
            video_name: lesson.video_name,
            duration_seconds: lesson.duration_seconds
          }
        : null
    )
    setVideoError(null)
    setFormOpen(true)
  }

  useEffect(() => {
    if (!formOpen) {
      return
    }
    form.setFieldsValue({
      title: editingLesson?.title ?? '',
      sort_order: editingLesson ? editingLesson.sort_order : null
    })
  }, [formOpen, editingLesson, form])

  const handleFinish = async (values: LessonFormValues) => {
    if (!courseId || !canManage) {
      return
    }
    if (!selectedVideo || !selectedVideo.file_id) {
      setVideoError('请从媒资库选择视频')
      return
    }
    setVideoError(null)
    try {
      if (editingLesson) {
        await dispatch(
          updateLesson({
            id: editingLesson.id,
            payload: {
              title: values.title.trim(),
              file_id: selectedVideo.file_id,
              sort_order: values.sort_order ?? undefined
            }
          })
        ).unwrap()
        message.success('课时已更新')
      } else {
        await dispatch(
          createLesson({
            course_id: courseId,
            title: values.title.trim(),
            file_id: selectedVideo.file_id,
            sort_order: values.sort_order ?? undefined
          })
        ).unwrap()
        message.success('课时已创建')
      }
      setFormOpen(false)
      setEditingLesson(null)
    } catch (saveError) {
      message.error(getErrorMessage(saveError))
    }
  }

  const handleDelete = async (lesson: Lesson) => {
    try {
      await dispatch(deleteLesson(lesson.id)).unwrap()
      message.success(`课时「${lesson.title}」已删除`)
    } catch (deleteError) {
      message.error(getErrorMessage(deleteError))
    }
  }

  /** 拖拽 / 上下移后，用既有更新接口重排 sort_order（10、20、30…）。 */
  const persistOrder = async (reordered: Lesson[]) => {
    if (!canManage || saving) {
      return
    }
    const updates = reordered
      .map((lesson, index) => ({
        lesson,
        nextSort: (index + 1) * 10
      }))
      .filter(({ lesson, nextSort }) => lesson.sort_order !== nextSort)

    if (updates.length === 0) {
      return
    }

    try {
      await Promise.all(
        updates.map(({ lesson, nextSort }) =>
          dispatch(
            updateLesson({
              id: lesson.id,
              payload: { sort_order: nextSort }
            })
          ).unwrap()
        )
      )
      message.success('课时顺序已更新')
      if (courseId) {
        void dispatch(fetchLessons(courseId))
      }
    } catch (orderError) {
      message.error(getErrorMessage(orderError))
      if (courseId) {
        void dispatch(fetchLessons(courseId))
      }
    }
  }

  const moveLesson = (index: number, offset: -1 | 1) => {
    const target = index + offset
    if (target < 0 || target >= visibleLessons.length) {
      return
    }
    const next = [...visibleLessons]
    const [moved] = next.splice(index, 1)
    next.splice(target, 0, moved)
    void persistOrder(next)
  }

  const handleDrop = (targetIndex: number) => {
    if (dragIndex === null || dragIndex === targetIndex) {
      setDragIndex(null)
      return
    }
    const next = [...visibleLessons]
    const [moved] = next.splice(dragIndex, 1)
    next.splice(targetIndex, 0, moved)
    setDragIndex(null)
    void persistOrder(next)
  }

  const reorderDisabled =
    !canManage || Boolean(nameFilter.trim()) || saving || visibleLessons.length < 2

  const columns: ColumnsType<Lesson> = [
    {
      title: '排序',
      key: 'sort',
      width: 150,
      render: (_value, lesson, index) => (
        <Space size={4}>
          <Tooltip title="拖拽行可调整顺序">
            <HolderOutlined style={{ color: reorderDisabled ? '#d6d3d1' : '#a8a29e' }} />
          </Tooltip>
          <Tag style={{ marginInlineEnd: 0 }}>{lesson.sort_order}</Tag>
          <Button
            type="text"
            size="small"
            icon={<ArrowUpOutlined />}
            disabled={reorderDisabled || index === 0}
            onClick={() => moveLesson(index, -1)}
            aria-label="上移"
          />
          <Button
            type="text"
            size="small"
            icon={<ArrowDownOutlined />}
            disabled={reorderDisabled || index === visibleLessons.length - 1}
            onClick={() => moveLesson(index, 1)}
            aria-label="下移"
          />
        </Space>
      )
    },
    {
      title: '归属课程',
      key: 'course',
      width: 190,
      ellipsis: true,
      render: () => (
        <Tooltip title={courseTitle}>
          <Typography.Text>{courseTitle || `课程 #${courseId ?? '—'}`}</Typography.Text>
        </Tooltip>
      )
    },
    {
      title: '课时标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: { showTitle: false },
      render: (value: string, lesson) => (
        <div>
          <Tooltip title={value}>
            <Typography.Text strong ellipsis style={{ maxWidth: 260 }}>
              {value}
            </Typography.Text>
          </Tooltip>
          <div style={{ fontSize: 11, color: '#a8a29e' }}>#{lesson.id}</div>
        </div>
      )
    },
    {
      title: '视频',
      key: 'video',
      width: 220,
      render: (_value, lesson) => (
        <div>
          <Typography.Text style={{ fontSize: 13 }}>
            {lesson.video_name || '未关联媒资'}
          </Typography.Text>
          <div style={{ fontSize: 11, color: '#a8a29e' }}>
            时长 {formatDuration(lesson.duration_seconds)}
          </div>
        </div>
      )
    },
    {
      title: '转码状态',
      key: 'status',
      width: 110,
      render: (_value, lesson) =>
        lesson.file_id ? (
          <Tooltip title="课时只绑定 FileId；转码详情请到媒资管理查看">
            <Tag color="success" bordered={false} style={{ borderRadius: 999 }}>
              已绑定
            </Tag>
          </Tooltip>
        ) : (
          <Tag bordered={false} style={{ borderRadius: 999 }}>
            未绑定
          </Tag>
        )
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (value: string) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {formatDateTime(value)}
        </Typography.Text>
      )
    },
    ...(canManage
      ? [
          {
            title: '操作',
            key: 'actions',
            width: 120,
            fixed: 'right' as const,
            render: (_value: unknown, lesson: Lesson) => (
              <Space size={4}>
                <Button
                  type="link"
                  size="small"
                  onClick={() => openEdit(lesson)}
                >
                  编辑
                </Button>
                <Popconfirm
                  title="删除课时？"
                  description="若该课时已存在学员学习记录，后端会拒绝删除。"
                  okText="删除"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => handleDelete(lesson)}
                >
                  <Button type="link" size="small" danger>
                    删除
                  </Button>
                </Popconfirm>
              </Space>
            )
          }
        ]
      : [])
  ]

  return (
    <div>
      <AdminPageHeader
        eyebrow="LESSONS"
        title="课时管理"
        description="按课程维护课时标题、排序与绑定视频。视频统一从媒资库选择，绑定 FileId 后由后端签发播放鉴权；管理后台不加载、不预览、不播放视频。"
        extra={
          <>
            <Button
              icon={<ReloadOutlined />}
              disabled={!courseId}
              loading={loading}
              onClick={() => {
                if (courseId) {
                  void dispatch(fetchLessons(courseId))
                }
              }}
            >
              刷新
            </Button>
            {canManage ? (
              <Button
                type="primary"
                icon={<PlusOutlined />}
                disabled={!courseId}
                onClick={openCreate}
              >
                新增课时
              </Button>
            ) : null}
          </>
        }
      />

      <Alert
        type={canManage ? 'info' : 'warning'}
        showIcon
        className="mb-4"
        message={
          canManage
            ? '课时属于整门课程：学员购买或获赠课程后解锁全部课时。视频从「媒资管理」上传并自动加密转码，这里只绑定 FileId。'
            : '当前账号为普通管理员，仅可查看课时与绑定视频。新建、编辑、删除课时需要超级管理员权限。'
        }
      />

      <Card className="mb-4">
        <Row gutter={[16, 12]} align="bottom">
          <Col xs={24} lg={12}>
            <Typography.Text
              type="secondary"
              style={{ display: 'block', marginBottom: 6, fontSize: 12 }}
            >
              所属课程
            </Typography.Text>
            <AdminCourseSelect
              value={courseId}
              onChange={handleCourseChange}
              placeholder="搜索并选择课程"
              disabled={saving}
            />
          </Col>
          <Col xs={24} lg={12}>
            <Typography.Text
              type="secondary"
              style={{ display: 'block', marginBottom: 6, fontSize: 12 }}
            >
              课时名称
            </Typography.Text>
            <Input
              allowClear
              placeholder="在当前课程的课时中筛选"
              value={nameFilter}
              onChange={(event) => setNameFilter(event.target.value)}
              disabled={!courseId}
            />
          </Col>
        </Row>

        <div
          style={{
            marginTop: 14,
            padding: '10px 12px',
            borderRadius: 8,
            background: '#faf8f4',
            color: '#78716c',
            fontSize: 12
          }}
        >
          {courseId ? (
            <>
              当前课程：<strong>{courseTitle || `课程 #${courseId}`}</strong>
              {' · '}共 {items.length} 个课时
              {nameFilter.trim()
                ? `，筛选出 ${visibleLessons.length} 个`
                : ' · 按排序值升序'}
            </>
          ) : (
            '请先搜索并选择一门课程再管理课时'
          )}
        </div>
      </Card>

      {error ? (
        <Alert
          type="error"
          showIcon
          className="mb-4"
          message="课时列表加载失败"
          description={error}
          action={
            courseId ? (
              <Button
                size="small"
                onClick={() => void dispatch(fetchLessons(courseId))}
              >
                重试
              </Button>
            ) : undefined
          }
        />
      ) : null}

      <Card styles={{ body: { padding: 0 } }}>
        <Table<Lesson>
          rowKey="id"
          columns={columns}
          dataSource={visibleLessons}
          loading={loading}
          scroll={{ x: 1050 }}
          onRow={(_record, index) => ({
            draggable: !reorderDisabled,
            onDragStart: () => setDragIndex(index ?? null),
            onDragOver: (event) => event.preventDefault(),
            onDrop: () => handleDrop(index ?? 0),
            style: {
              cursor: reorderDisabled ? 'default' : 'grab',
              opacity: dragIndex === index ? 0.6 : 1
            }
          })}
          locale={{
            emptyText: !courseId ? (
              <Empty description="请先在上方搜索并选择一门课程" />
            ) : (
              <Empty
                description={
                  loading
                    ? '正在加载课时…'
                    : nameFilter
                      ? '没有匹配的课时'
                      : '该课程还没有课时'
                }
              />
            )
          }}
          title={() => (
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              课时列表 · 支持拖拽行或使用上下箭头调整顺序
            </Typography.Text>
          )}
        />
      </Card>

      <Modal
        open={formOpen}
        title={editingLesson ? '编辑课时' : '新增课时'}
        width={580}
        okText="保存课时"
        cancelText="取消"
        confirmLoading={saving}
        onOk={() => form.submit()}
        onCancel={() => {
          if (!saving) {
            setFormOpen(false)
            setEditingLesson(null)
          }
        }}
        destroyOnClose
      >
        <Form<LessonFormValues>
          form={form}
          layout="vertical"
          onFinish={(values) => void handleFinish(values)}
          preserve={false}
        >
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message={`所属课程：${courseTitle || `#${courseId ?? '—'}`}${
              editingLesson ? '；课时创建后不可迁移到其他课程' : ''
            }`}
          />

          <Form.Item
            name="title"
            label="课时标题"
            rules={[
              { required: true, whitespace: true, message: '请输入课时标题' },
              { max: 200, message: '课时标题不能超过 200 个字符' }
            ]}
          >
            <Input
              placeholder="例如：第 1 讲 · 增长模型"
              maxLength={200}
            />
          </Form.Item>

          <Form.Item
            name="sort_order"
            label="排序值"
            extra="越小越靠前；留空则新建时自动追加到末尾"
            rules={[
              {
                type: 'number',
                min: 0,
                max: 99999,
                message: '排序值需为 0-99999 的整数'
              }
            ]}
          >
            <InputNumber
              min={0}
              max={99999}
              precision={0}
              placeholder="例如：10"
              style={{ width: '100%' }}
            />
          </Form.Item>

          <Form.Item
            label="课时视频"
            required
            validateStatus={videoError ? 'error' : undefined}
            help={videoError || '从媒资库选择已转码完成的视频；后台不加载视频地址'}
          >
            {selectedVideo ? (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 12,
                  padding: '12px 14px',
                  border: '1px solid #e7e5e4',
                  borderRadius: 8,
                  background: '#fafaf9'
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <Typography.Text strong ellipsis style={{ display: 'block' }}>
                    {selectedVideo.video_name || '历史视频（不在媒资库中）'}
                  </Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                    时长 {formatDuration(selectedVideo.duration_seconds)} ·{' '}
                    {selectedVideo.file_id}
                  </Typography.Text>
                </div>
                <Button
                  size="small"
                  onClick={() => setPickerOpen(true)}
                  disabled={saving}
                >
                  重新选择
                </Button>
              </div>
            ) : (
              <Button
                block
                type="dashed"
                icon={<VideoCameraAddOutlined />}
                onClick={() => setPickerOpen(true)}
                disabled={saving}
              >
                从媒资库选择视频
              </Button>
            )}
          </Form.Item>
        </Form>
      </Modal>

      {formOpen ? (
        <VideoPickerModal
          open={pickerOpen}
          selected={selectedVideo}
          canManage={canManage}
          onClose={() => setPickerOpen(false)}
          onConfirm={(selection) => {
            setSelectedVideo(selection)
            setVideoError(null)
            setPickerOpen(false)
          }}
        />
      ) : null}
    </div>
  )
}
