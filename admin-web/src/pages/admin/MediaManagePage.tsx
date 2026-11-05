import {
  useCallback,
  useEffect,
  useRef,
  useState
} from 'react'
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Empty,
  Form,
  Input,
  Modal,
  Pagination,
  Popconfirm,
  Progress,
  Row,
  Segmented,
  Select,
  Space,
  Table,
  Tooltip,
  Typography,
  Upload
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { UploadFile } from 'antd/es/upload/interface'
import {
  AppstoreOutlined,
  BarsOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SyncOutlined
} from '@ant-design/icons'

import { getErrorMessage } from '../../api/request'
import AdminPageHeader from '../../components/admin/PageHeader'
import { MediaStatusTag } from '../../components/admin/StatusTags'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  clearUploadError,
  deleteMedia,
  fetchMedia,
  selectMedia,
  syncMedia,
  updateMedia,
  uploadMedia
} from '../../store/slices/mediaSlice'
import type { VodMedia, VodMediaStatus } from '../../types'
import {
  formatDateTime,
  formatDuration,
  formatFileSize
} from '../../utils/format'

const MAX_UPLOAD_MB = 2048
const POLL_INTERVAL_MS = 8000
const PAGE_SIZE_OPTIONS = ['12', '24', '48']
const TABLE_PAGE_SIZE_OPTIONS = ['10', '20', '50']

const STATUS_OPTIONS: Array<{ label: string; value: VodMediaStatus }> = [
  { label: '转码中', value: 0 },
  { label: '可用', value: 1 },
  { label: '转码失败', value: 2 }
]

interface MediaFilterValues {
  keyword?: string
  status?: VodMediaStatus
}

interface MediaRenameValues {
  video_name: string
}

interface MediaCoverProps {
  media: VodMedia
  height?: number
}

function MediaCover({ media, height = 152 }: MediaCoverProps) {
  const [broken, setBroken] = useState(false)
  const showImage = Boolean(media.cover_url) && !broken

  return (
    <div
      style={{
        position: 'relative',
        height,
        overflow: 'hidden',
        borderRadius: 8,
        background:
          'linear-gradient(135deg, #1b2942 0%, #0d1526 60%, #131e33 100%)'
      }}
    >
      {showImage ? (
        <img
          src={media.cover_url ?? ''}
          alt={`${media.video_name} 封面`}
          loading="lazy"
          onError={() => setBroken(true)}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        />
      ) : (
        <div
          style={{
            display: 'flex',
            height: '100%',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 6,
            color: 'rgba(255,255,255,0.45)',
            fontSize: 12
          }}
        >
          <PlayCircleOutlined style={{ fontSize: 28 }} />
          {media.status === 0 ? '转码中，封面稍后生成' : '暂无封面'}
        </div>
      )}

      <div style={{ position: 'absolute', top: 8, left: 8 }}>
        <MediaStatusTag status={media.status} />
      </div>

      <div
        style={{
          position: 'absolute',
          right: 8,
          bottom: 8,
          padding: '1px 8px',
          borderRadius: 999,
          background: 'rgba(13,21,38,0.78)',
          color: '#fff',
          fontSize: 11,
          fontVariantNumeric: 'tabular-nums'
        }}
      >
        {formatDuration(media.duration_seconds)}
      </div>
    </div>
  )
}

interface MediaPreviewModalProps {
  media: VodMedia | null
  onClose: () => void
}

function MediaPreviewModal({ media, onClose }: MediaPreviewModalProps) {
  return (
    <Modal
      open={media !== null}
      title="媒资详情"
      width={640}
      footer={<Button onClick={onClose}>关闭</Button>}
      onCancel={onClose}
      destroyOnClose
    >
      {media ? (
        <>
          <MediaCover media={media} height={260} />

          {media.status === 2 && media.fail_reason ? (
            <Alert
              type="error"
              showIcon
              style={{ marginTop: 12 }}
              message="转码失败"
              description={media.fail_reason}
            />
          ) : null}

          <Descriptions
            column={2}
            size="small"
            style={{ marginTop: 16 }}
            items={[
              {
                key: 'name',
                label: '视频名称',
                children: media.video_name,
                span: 2
              },
              {
                key: 'file_id',
                label: 'FileId',
                children: (
                  <Typography.Text copyable style={{ fontSize: 12 }}>
                    {media.file_id}
                  </Typography.Text>
                ),
                span: 2
              },
              {
                key: 'duration',
                label: '时长',
                children: formatDuration(media.duration_seconds)
              },
              {
                key: 'status',
                label: '转码状态',
                children: <MediaStatusTag status={media.status} />
              },
              {
                key: 'uploader',
                label: '上传人',
                children: media.uploader_id
                  ? `管理员 #${media.uploader_id}`
                  : '—'
              },
              {
                key: 'created',
                label: '上传时间',
                children: formatDateTime(media.created_at)
              }
            ]}
          />

          <Alert
            type="info"
            showIcon
            style={{ marginTop: 12 }}
            message="后台不加载、不播放视频。加密播放地址仅在学员端通过后端鉴权接口签发。"
          />
        </>
      ) : null}
    </Modal>
  )
}

export default function MediaManagePage() {
  const dispatch = useAppDispatch()
  const { message } = AntdApp.useApp()
  const {
    items,
    total,
    page,
    pageSize,
    keyword,
    loading,
    error,
    uploading,
    uploadPercent,
    uploadError,
    syncing,
    updating,
    deletingId
  } = useAppSelector(selectMedia)
  const role = useAppSelector((state) => state.adminAuth.admin?.role)
  const canManage = role === 'super'

  const [filterForm] = Form.useForm<MediaFilterValues>()
  const [renameForm] = Form.useForm<MediaRenameValues>()

  const [viewMode, setViewMode] = useState<'grid' | 'table'>('grid')
  const [appliedKeyword, setAppliedKeyword] = useState('')
  const [appliedStatus, setAppliedStatus] = useState<VodMediaStatus | undefined>()
  const [appliedFileId, setAppliedFileId] = useState('')
  const [fileIdInput, setFileIdInput] = useState('')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadLocalError, setUploadLocalError] = useState<string | null>(null)
  const [uploadTask, setUploadTask] = useState<{
    abort: (reason?: string) => void
  } | null>(null)
  const [editTarget, setEditTarget] = useState<VodMedia | null>(null)
  const [previewTarget, setPreviewTarget] = useState<VodMedia | null>(null)
  const uploadInputRef = useRef<HTMLInputElement | null>(null)

  const load = useCallback(
    (
      nextPage: number,
      nextPageSize = pageSize,
      nextKeyword = '',
      nextStatus?: VodMediaStatus,
      nextFileId = ''
    ) => {
      void dispatch(
        fetchMedia({
          page: nextPage,
          page_size: nextPageSize,
          keyword: nextKeyword || undefined,
          file_id: nextFileId || undefined,
          status: nextStatus
        })
      )
    },
    [dispatch, pageSize]
  )

  useEffect(() => {
    load(1, 20, '', undefined, '')
    // 首次进入只加载一次默认列表。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dispatch])

  /** 转码中或封面尚未生成的媒资需要轮询同步。 */
  const pendingIds = items
    .filter(
      (item) => item.status === 0 || (item.status === 1 && !item.cover_url)
    )
    .map((item) => item.id)
  const pendingKey = pendingIds.join(',')

  useEffect(() => {
    if (!canManage || !pendingKey) {
      return
    }
    let cancelled = false
    const timer = window.setInterval(() => {
      void dispatch(syncMedia(pendingKey.split(',').map(Number)))
        .unwrap()
        .catch(() => undefined)
        .finally(() => {
          if (!cancelled) {
            load(page, pageSize, appliedKeyword, appliedStatus, appliedFileId)
          }
        })
    }, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [
    canManage,
    pendingKey,
    page,
    pageSize,
    appliedKeyword,
    appliedStatus,
    appliedFileId,
    load
  ])

  const handleSearch = (values: MediaFilterValues) => {
    const nextKeyword = values.keyword?.trim() ?? ''
    const nextFileId = fileIdInput.trim()
    setAppliedKeyword(nextKeyword)
    setAppliedStatus(values.status)
    setAppliedFileId(nextFileId)
    load(1, pageSize, nextKeyword, values.status, nextFileId)
  }

  const handleReset = () => {
    filterForm.resetFields()
    setFileIdInput('')
    setAppliedKeyword('')
    setAppliedStatus(undefined)
    setAppliedFileId('')
    load(1, pageSize, '', undefined, '')
  }

  const openUpload = () => {
    dispatch(clearUploadError())
    setUploadFile(null)
    setUploadLocalError(null)
    setUploadOpen(true)
  }

  const pickUploadFile = (file: File) => {
    const lowerName = file.name.toLowerCase()
    if (!lowerName.endsWith('.mp4')) {
      setUploadFile(null)
      setUploadLocalError('仅支持 MP4 格式的视频')
      return
    }
    if (file.size <= 0) {
      setUploadFile(null)
      setUploadLocalError('视频文件为空，请重新选择')
      return
    }
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setUploadFile(null)
      setUploadLocalError(`视频不能超过 ${MAX_UPLOAD_MB}MB`)
      return
    }
    setUploadLocalError(null)
    setUploadFile(file)
  }

  const startUpload = async () => {
    if (!uploadFile) {
      setUploadLocalError('请选择要上传的视频')
      return
    }
    const task = dispatch(uploadMedia({ file: uploadFile }))
    setUploadTask(task)
    try {
      const media = await task.unwrap()
      message.success(
        `「${media.video_name}」已上传，正在转码，完成后自动可用`
      )
      setUploadOpen(false)
      setUploadFile(null)
      load(1, pageSize, appliedKeyword, appliedStatus, appliedFileId)
    } catch (uploadTaskError) {
      // 具体错误由 uploadError 在弹窗内展示。
      if (!(uploadTaskError === '已取消上传')) {
        message.error(getErrorMessage(uploadTaskError))
      }
    } finally {
      setUploadTask(null)
    }
  }

  const closeUploadModal = () => {
    if (uploading) {
      uploadTask?.abort('用户取消上传')
    }
    setUploadOpen(false)
    setUploadFile(null)
    setUploadLocalError(null)
  }

  const openEdit = (media: VodMedia) => {
    setEditTarget(media)
  }

  useEffect(() => {
    if (!editTarget) {
      return
    }
    renameForm.setFieldsValue({ video_name: editTarget.video_name })
  }, [editTarget, renameForm])

  const handleRename = async (values: MediaRenameValues) => {
    if (!editTarget) {
      return
    }
    try {
      await dispatch(
        updateMedia({
          id: editTarget.id,
          payload: { video_name: values.video_name.trim() }
        })
      ).unwrap()
      message.success('媒资名称已更新')
      setEditTarget(null)
      load(page, pageSize, appliedKeyword, appliedStatus, appliedFileId)
    } catch (renameError) {
      message.error(getErrorMessage(renameError))
    }
  }

  const handleDelete = async (media: VodMedia) => {
    try {
      await dispatch(deleteMedia(media.id)).unwrap()
      message.success(`媒资「${media.video_name}」已删除`)
      const nextPage = items.length === 1 && page > 1 ? page - 1 : page
      load(
        nextPage,
        pageSize,
        appliedKeyword,
        appliedStatus,
        appliedFileId
      )
    } catch (deleteError) {
      message.error(getErrorMessage(deleteError))
    }
  }

  const handleSync = async () => {
    try {
      const result = await dispatch(
        syncMedia(pendingIds.length ? pendingIds : undefined)
      ).unwrap()
      message.success(result.message)
      load(page, pageSize, appliedKeyword, appliedStatus, appliedFileId)
    } catch (syncError) {
      message.error(getErrorMessage(syncError))
    }
  }

  const renderActions = (media: VodMedia, compact = false) => (
    <Space size={compact ? 0 : 4}>
      <Button
        type="link"
        size="small"
        icon={<EyeOutlined />}
        onClick={() => setPreviewTarget(media)}
      >
        预览
      </Button>
      {canManage ? (
        <>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEdit(media)}
          >
            编辑
          </Button>
          <Popconfirm
            title="删除媒资？"
            description="仅删除本地媒资记录，VOD 原文件保留；已被课时绑定时后端会拒绝删除。"
            okText="删除"
            cancelText="取消"
            okButtonProps={{
              danger: true,
              loading: deletingId === media.id
            }}
            onConfirm={() => handleDelete(media)}
          >
            <Button
              type="link"
              size="small"
              danger
              icon={<DeleteOutlined />}
              disabled={deletingId !== null}
            >
              删除
            </Button>
          </Popconfirm>
        </>
      ) : null}
    </Space>
  )

  const columns: ColumnsType<VodMedia> = [
    {
      title: '封面',
      key: 'cover',
      width: 130,
      render: (_value, media) => (
        <div style={{ width: 104 }}>
          <MediaCover media={media} height={60} />
        </div>
      )
    },
    {
      title: '视频名称 / FileId',
      key: 'name',
      render: (_value, media) => (
        <div style={{ minWidth: 0 }}>
          <Tooltip title={media.video_name}>
            <Typography.Text
              strong
              ellipsis
              style={{ display: 'block', maxWidth: 320 }}
            >
              {media.video_name}
            </Typography.Text>
          </Tooltip>
          <Typography.Text
            type="secondary"
            copyable={{ text: media.file_id }}
            style={{ fontSize: 11 }}
          >
            {media.file_id}
          </Typography.Text>
        </div>
      )
    },
    {
      title: '时长',
      dataIndex: 'duration_seconds',
      key: 'duration',
      width: 90,
      render: (value: number) => (
        <Typography.Text style={{ fontSize: 12 }}>
          {formatDuration(value)}
        </Typography.Text>
      )
    },
    {
      title: '转码状态',
      key: 'status',
      width: 130,
      render: (_value, media) => (
        <div>
          <MediaStatusTag status={media.status} />
          {media.status === 2 && media.fail_reason ? (
            <Tooltip title={media.fail_reason}>
              <Typography.Text
                type="danger"
                ellipsis
                style={{ display: 'block', maxWidth: 120, fontSize: 11 }}
              >
                {media.fail_reason}
              </Typography.Text>
            </Tooltip>
          ) : null}
        </div>
      )
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (value: string) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {formatDateTime(value)}
        </Typography.Text>
      )
    },
    {
      title: '操作',
      key: 'actions',
      width: canManage ? 210 : 90,
      fixed: 'right',
      render: (_value, media) => renderActions(media)
    }
  ]

  const gridCards = items.map((media) => (
    <Col key={media.id} xs={24} sm={12} lg={8} xxl={6}>
      <Card
        hoverable
        size="small"
        styles={{ body: { padding: 12 } }}
        onClick={() => setPreviewTarget(media)}
      >
        <MediaCover media={media} />
        <div style={{ marginTop: 10 }}>
          <Tooltip title={media.video_name}>
            <Typography.Text
              strong
              ellipsis
              style={{ display: 'block', fontSize: 13 }}
            >
              {media.video_name}
            </Typography.Text>
          </Tooltip>
          <Space size={6} wrap style={{ marginTop: 4 }}>
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              {formatDateTime(media.created_at)}
            </Typography.Text>
            {media.uploader_id ? (
              <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                · 上传人 #{media.uploader_id}
              </Typography.Text>
            ) : null}
          </Space>
        </div>

        <div
          style={{ marginTop: 8, borderTop: '1px solid #f5f5f4', paddingTop: 4 }}
          onClick={(event) => event.stopPropagation()}
        >
          {renderActions(media, true)}
        </div>
      </Card>
    </Col>
  ))

  return (
    <div>
      <AdminPageHeader
        eyebrow="MEDIA"
        title="媒资管理"
        description="上传 MP4 到腾讯云 VOD 媒资库，上传时自动绑定加密转码任务流。只有转码完成的视频才能在课时中绑定；同一视频可被多个课时复用。"
        extra={
          <>
            <Button
              icon={<ReloadOutlined />}
              loading={loading}
              onClick={() =>
                load(
                  page,
                  pageSize,
                  appliedKeyword,
                  appliedStatus,
                  appliedFileId
                )
              }
            >
              刷新
            </Button>
            {canManage ? (
              <>
                <Button
                  icon={<SyncOutlined />}
                  loading={syncing}
                  onClick={() => void handleSync()}
                >
                  同步状态
                </Button>
                <Button
                  type="primary"
                  icon={<CloudUploadOutlined />}
                  onClick={openUpload}
                >
                  上传媒资
                </Button>
              </>
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
            ? '上传后状态为「转码中」，页面每 8 秒自动同步一次，完成后变为「可用」。媒资库只存储视频，腾讯云密钥只存在于服务端。'
            : '当前账号为普通管理员，仅可查看媒资库。上传、改名、删除与同步转码状态需要超级管理员权限。'
        }
      />

      <Card className="mb-4">
        <Form<MediaFilterValues>
          form={filterForm}
          layout="inline"
          initialValues={{ keyword: '', status: undefined }}
          onFinish={handleSearch}
          style={{ rowGap: 12 }}
        >
          <Form.Item
            name="keyword"
            label="文件名"
            style={{ flex: '1 1 240px', maxWidth: 360 }}
          >
            <Input
              allowClear
              placeholder="输入视频名称模糊搜索"
              maxLength={100}
              style={{ width: '100%' }}
            />
          </Form.Item>
          <Form.Item
            label="类型"
            tooltip="当前媒资库仅存储视频，不支持音频或图片"
          >
            <Select
              value="video"
              disabled
              style={{ width: 110 }}
              options={[{ label: '视频', value: 'video' }]}
            />
          </Form.Item>
          <Form.Item name="status" label="转码状态">
            <Select
              allowClear
              placeholder="全部"
              style={{ width: 130 }}
              options={STATUS_OPTIONS}
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

        <Collapse
          ghost
          size="small"
          style={{ marginTop: 8 }}
          items={[
            {
              key: 'advanced',
              label: '高级筛选',
              children: (
                <div style={{ maxWidth: 460 }}>
                  <Typography.Text
                    type="secondary"
                    style={{ display: 'block', marginBottom: 4, fontSize: 12 }}
                  >
                    FileId 精确查询
                  </Typography.Text>
                  <Input
                    allowClear
                    placeholder="例如：52858908xxxx"
                    maxLength={200}
                    value={fileIdInput}
                    onChange={(event) => setFileIdInput(event.target.value)}
                    onPressEnter={() => filterForm.submit()}
                  />
                  <Typography.Text
                    type="secondary"
                    style={{ display: 'block', marginTop: 4, fontSize: 11 }}
                  >
                    腾讯云 VOD 返回的 FileId，常见于课时文档或日志
                  </Typography.Text>
                </div>
              )
            }
          ]}
        />

        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            marginTop: 10
          }}
        >
          <Segmented
            value={viewMode}
            onChange={(value) => setViewMode(value as 'grid' | 'table')}
            options={[
              { label: '卡片', value: 'grid', icon: <AppstoreOutlined /> },
              { label: '表格', value: 'table', icon: <BarsOutlined /> }
            ]}
          />
        </div>
      </Card>

      {error ? (
        <Alert
          type="error"
          showIcon
          className="mb-4"
          message="媒资列表加载失败"
          description={error}
          action={
            <Button
              size="small"
              onClick={() =>
                load(
                  page,
                  pageSize,
                  appliedKeyword,
                  appliedStatus,
                  appliedFileId
                )
              }
            >
              重试
            </Button>
          }
        />
      ) : null}

      {viewMode === 'grid' ? (
        <Card>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              flexWrap: 'wrap',
              gap: 8,
              marginBottom: 14
            }}
          >
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              共 {total} 个视频
              {keyword ? ` · 搜索「${keyword}」` : ''}
              {appliedFileId ? ` · FileId「${appliedFileId}」` : ''}
            </Typography.Text>
            {loading ? (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                加载中…
              </Typography.Text>
            ) : null}
          </div>

          {items.length > 0 ? (
            <Row gutter={[16, 16]}>{gridCards}</Row>
          ) : (
            <Empty
              style={{ padding: '40px 0' }}
              description={
                loading
                  ? '正在加载媒资…'
                  : appliedKeyword || appliedFileId || appliedStatus !== undefined
                    ? '没有匹配的媒资'
                    : '媒资库还是空的'
              }
            >
              {!loading && canManage ? (
                <Button
                  type="primary"
                  icon={<CloudUploadOutlined />}
                  onClick={openUpload}
                >
                  上传第一个视频
                </Button>
              ) : null}
            </Empty>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 18 }}>
            <Pagination
              current={page}
              pageSize={pageSize}
              total={total}
              showSizeChanger
              pageSizeOptions={PAGE_SIZE_OPTIONS}
              showTotal={(count) => `共 ${count} 个`}
              disabled={loading}
              onChange={(nextPage, nextPageSize) =>
                load(
                  nextPage,
                  nextPageSize,
                  appliedKeyword,
                  appliedStatus,
                  appliedFileId
                )
              }
            />
          </div>
        </Card>
      ) : (
        <Card styles={{ body: { padding: 0 } }}>
          <Table<VodMedia>
            rowKey="id"
            columns={columns}
            dataSource={items}
            loading={loading}
            scroll={{ x: 950 }}
            title={() => (
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                共 {total} 个视频
                {keyword ? ` · 搜索「${keyword}」` : ''}
              </Typography.Text>
            )}
            locale={{
              emptyText: loading
                ? '正在加载媒资…'
                : '暂无媒资，上传后即可在课时中选择'
            }}
            pagination={{
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              pageSizeOptions: TABLE_PAGE_SIZE_OPTIONS,
              showTotal: (count) => `共 ${count} 个`,
              onChange: (nextPage, nextPageSize) =>
                load(
                  nextPage,
                  nextPageSize,
                  appliedKeyword,
                  appliedStatus,
                  appliedFileId
                )
            }}
          />
        </Card>
      )}

      <Modal
        open={uploadOpen}
        title="上传媒资"
        width={580}
        okText={uploading ? '上传中…' : '开始上传'}
        cancelText={uploading ? '取消上传' : '取消'}
        okButtonProps={{ disabled: !uploadFile || uploading, loading: uploading }}
        cancelButtonProps={{ danger: uploading }}
        onOk={() => void startUpload()}
        onCancel={closeUploadModal}
        maskClosable={!uploading}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 14 }}
          message="上传后自动执行加密转码任务流，转码完成前不能绑定课时。失败不会写入媒资库，可直接重新上传。"
        />

        {uploadLocalError || uploadError ? (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 14 }}
            message={uploadLocalError || uploadError}
          />
        ) : null}

        <Upload.Dragger
          accept=".mp4,video/mp4"
          multiple={false}
          maxCount={1}
          fileList={[] as UploadFile[]}
          showUploadList={false}
          disabled={uploading}
          beforeUpload={(file) => {
            pickUploadFile(file as File)
            // 文件由 mediaSlice.uploadMedia 走后端 multipart，不交给 antd 上传。
            return Upload.LIST_IGNORE
          }}
          openFileDialogOnClick={!uploading}
          style={{ background: '#fafaf9' }}
        >
          <p className="ant-upload-drag-icon" style={{ marginBottom: 4 }}>
            <CloudUploadOutlined style={{ color: '#a47436', fontSize: 30 }} />
          </p>
          <p style={{ margin: 0, fontWeight: 600 }}>
            点击选择视频，或拖拽到此处
          </p>
          <p
            style={{
              margin: '4px 0 0',
              fontSize: 12,
              color: '#78716c'
            }}
          >
            仅支持 MP4，单个视频不超过 {MAX_UPLOAD_MB}MB
          </p>
        </Upload.Dragger>

        {uploadFile ? (
          <div
            style={{
              marginTop: 12,
              padding: '10px 12px',
              border: '1px solid #e7e5e4',
              borderRadius: 8,
              background: '#fff'
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 12
              }}
            >
              <Typography.Text strong ellipsis style={{ maxWidth: 380 }}>
                {uploadFile.name}
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {formatFileSize(uploadFile.size)}
              </Typography.Text>
            </div>

            {uploading ? (
              <div style={{ marginTop: 10 }}>
                <Progress
                  percent={uploadPercent < 0 ? 0 : uploadPercent}
                  status="active"
                  size="small"
                  showInfo={uploadPercent >= 0}
                />
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                  {uploadPercent < 0
                    ? '正在上传…'
                    : uploadPercent >= 100
                      ? '文件已送达，服务器正在提交腾讯云处理，请稍候…'
                      : `已上传 ${uploadPercent}%`}
                </Typography.Text>
              </div>
            ) : (
              <div style={{ marginTop: 6 }}>
                <Typography.Link
                  style={{ fontSize: 12 }}
                  onClick={() => {
                    setUploadFile(null)
                    uploadInputRef.current?.click()
                  }}
                >
                  重新选择
                </Typography.Link>
              </div>
            )}
          </div>
        ) : null}

        <input
          ref={uploadInputRef}
          type="file"
          accept=".mp4,video/mp4"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) {
              pickUploadFile(file)
            }
            // 允许重复选择同一个文件。
            event.target.value = ''
          }}
        />
      </Modal>

      <Modal
        open={editTarget !== null}
        title="编辑媒资名称"
        width={420}
        okText="保存"
        cancelText="取消"
        confirmLoading={updating}
        onOk={() => renameForm.submit()}
        onCancel={() => {
          if (!updating) {
            setEditTarget(null)
          }
        }}
        destroyOnClose
      >
        <Form<MediaRenameValues>
          form={renameForm}
          layout="vertical"
          onFinish={(values) => void handleRename(values)}
          preserve={false}
        >
          <Form.Item
            name="video_name"
            label="视频名称"
            rules={[
              { required: true, whitespace: true, message: '请输入视频名称' },
              { max: 200, message: '视频名称不能超过 200 个字符' }
            ]}
            extra="FileId、时长、转码状态与封面由腾讯云 VOD 维护，不能在此修改。"
          >
            <Input placeholder="请输入视频名称" maxLength={200} autoFocus />
          </Form.Item>
        </Form>
      </Modal>

      <MediaPreviewModal
        media={previewTarget}
        onClose={() => setPreviewTarget(null)}
      />
    </div>
  )
}
