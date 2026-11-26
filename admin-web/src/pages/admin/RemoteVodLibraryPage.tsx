import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  CloudDownloadOutlined,
  ReloadOutlined
} from '@ant-design/icons'

import { importRemoteVod, listRemoteVod } from '../../api/mediaApi'
import { getErrorMessage } from '../../api/request'
import MediaCover from '../../components/admin/MediaCover'
import AdminPageHeader from '../../components/admin/PageHeader'
import { MediaStatusTag } from '../../components/admin/StatusTags'
import { useAppSelector } from '../../store/hooks'
import type {
  RemoteVodImportFilter,
  RemoteVodVideo
} from '../../types'
import {
  formatDuration,
  formatShanghaiDateTime
} from '../../utils/format'

const PAGE_SIZE_OPTIONS = ['10', '20', '50']

const IMPORT_FILTER_OPTIONS: Array<{
  label: string
  value: RemoteVodImportFilter
}> = [
  { label: '全部', value: 'all' },
  { label: '已入库', value: 'imported' },
  { label: '未入库', value: 'not_imported' }
]

/** 腾讯云 VOD 视频库：与本地媒资库按 FileId 对比，可手动入库。 */
export default function RemoteVodLibraryPage() {
  const { message } = AntdApp.useApp()
  const navigate = useNavigate()
  const role = useAppSelector((state) => state.adminAuth.admin?.role)
  const canManage = role === 'super'

  const [items, setItems] = useState<RemoteVodVideo[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [keyword, setKeyword] = useState('')
  const [keywordInput, setKeywordInput] = useState('')
  const [importedFilter, setImportedFilter] =
    useState<RemoteVodImportFilter>('all')

  const [importTarget, setImportTarget] = useState<RemoteVodVideo | null>(null)
  const [importName, setImportName] = useState('')
  const [importing, setImporting] = useState(false)
  const [localTarget, setLocalTarget] = useState<RemoteVodVideo | null>(null)

  const load = useCallback(
    async (
      nextPage: number,
      nextPageSize = pageSize,
      nextKeyword = keyword,
      nextImported = importedFilter
    ) => {
      setLoading(true)
      setError(null)
      try {
        const result = await listRemoteVod({
          page: nextPage,
          page_size: nextPageSize,
          keyword: nextKeyword || undefined,
          imported: nextImported
        })
        setItems(result.items)
        setTotal(result.total)
        setPage(result.page)
        setPageSize(result.page_size)
      } catch (loadError) {
        setError(getErrorMessage(loadError))
        setItems([])
        setTotal(0)
      } finally {
        setLoading(false)
      }
    },
    [pageSize, keyword, importedFilter]
  )

  useEffect(() => {
    void load(1, 20, '', 'all')
    // 首次进入只加载一次默认列表。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleSearch = () => {
    const nextKeyword = keywordInput.trim()
    setKeyword(nextKeyword)
    void load(1, pageSize, nextKeyword, importedFilter)
  }

  const handleReset = () => {
    setKeywordInput('')
    setKeyword('')
    setImportedFilter('all')
    void load(1, pageSize, '', 'all')
  }

  const openImport = (item: RemoteVodVideo) => {
    setImportTarget(item)
    setImportName(item.video_name)
  }

  const closeImport = () => {
    if (!importing) {
      setImportTarget(null)
    }
  }

  const handleImport = async () => {
    if (!importTarget || importing) {
      return
    }
    const name = importName.trim()
    if (!name) {
      return
    }
    setImporting(true)
    try {
      const media = await importRemoteVod({
        file_id: importTarget.file_id,
        video_name: name
      })
      message.success(
        `「${media.video_name}」已入库，转码完成后即可在课时中绑定`
      )
      setImportTarget(null)
      const nextPage =
        importedFilter === 'not_imported' && items.length === 1 && page > 1
          ? page - 1
          : page
      await load(nextPage, pageSize, keyword, importedFilter)
    } catch (importError) {
      message.error(getErrorMessage(importError))
    } finally {
      setImporting(false)
    }
  }

  const columns: ColumnsType<RemoteVodVideo> = [
    {
      title: '封面',
      key: 'cover',
      width: 130,
      render: (_value, item) => (
        <div style={{ width: 104 }}>
          <MediaCover
            coverUrl={item.cover_url}
            title={item.video_name}
            height={60}
            durationSeconds={item.duration_seconds}
          />
        </div>
      )
    },
    {
      title: '视频名称 / FileId',
      key: 'name',
      render: (_value, item) => (
        <div style={{ minWidth: 0 }}>
          <Tooltip title={item.video_name}>
            <Typography.Text
              strong
              ellipsis
              style={{ display: 'block', maxWidth: 320 }}
            >
              {item.video_name}
            </Typography.Text>
          </Tooltip>
          <Typography.Text
            type="secondary"
            copyable={{ text: item.file_id }}
            style={{ fontSize: 11 }}
          >
            {item.file_id}
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
      title: 'VOD 创建时间',
      dataIndex: 'remote_created_at',
      key: 'remote_created_at',
      width: 160,
      render: (value: string | null) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {formatShanghaiDateTime(value)}
        </Typography.Text>
      )
    },
    {
      title: '入库状态',
      key: 'imported',
      width: 150,
      render: (_value, item) => {
        if (!item.imported) {
          return (
            <Tag bordered={false} style={{ borderRadius: 999 }}>
              未入库
            </Tag>
          )
        }
        return (
          <Space direction="vertical" size={2}>
            <Tag
              color="success"
              bordered={false}
              style={{ marginInlineEnd: 0, borderRadius: 999 }}
            >
              已入库
            </Tag>
            <Tooltip title={item.imported.video_name}>
              <Typography.Text
                type="secondary"
                ellipsis
                style={{ display: 'block', maxWidth: 130, fontSize: 11 }}
              >
                {item.imported.video_name}
              </Typography.Text>
            </Tooltip>
            <MediaStatusTag status={item.imported.status} />
          </Space>
        )
      }
    },
    {
      title: '操作',
      key: 'actions',
      width: canManage ? 120 : 90,
      fixed: 'right',
      render: (_value, item) => {
        if (item.imported) {
          return (
            <Button
              type="link"
              size="small"
              onClick={() => setLocalTarget(item)}
            >
              查看本地
            </Button>
          )
        }
        if (!canManage) {
          return (
            <Tooltip title="仅超级管理员可入库">
              <Button type="link" size="small" disabled>
                入库
              </Button>
            </Tooltip>
          )
        }
        return (
          <Button
            type="link"
            size="small"
            icon={<CloudDownloadOutlined />}
            onClick={() => openImport(item)}
          >
            入库
          </Button>
        )
      }
    }
  ]

  return (
    <div>
      <AdminPageHeader
        eyebrow="VOD LIBRARY"
        title="VOD视频库"
        description="直接读取腾讯云 VOD 应用内的视频，与本地媒资库按 FileId 对比。已入库的视频无需重复导入；远程删除不会自动清理本地记录。后台不加载、不播放视频。"
        extra={
          <>
            <Button
              icon={<ReloadOutlined />}
              loading={loading}
              onClick={() => void load(page, pageSize, keyword, importedFilter)}
            >
              刷新
            </Button>
            <Button onClick={() => navigate('/media')}>本地媒资库</Button>
          </>
        }
      />

      <Alert
        type={canManage ? 'info' : 'warning'}
        showIcon
        className="mb-4"
        message={
          canManage
            ? '入库只写入本地媒资索引，视频文件仍由腾讯云 VOD 保存。转码中的视频会以「转码中」状态入库，完成后在媒资管理页自动同步。'
            : '当前账号为普通管理员，仅可查看 VOD 视频库与入库状态。手动入库需要超级管理员权限。'
        }
      />

      <Card className="mb-4">
        <Form layout="inline" onFinish={handleSearch} style={{ rowGap: 12 }}>
          <Form.Item
            label="视频名称"
            style={{ flex: '1 1 260px', maxWidth: 380 }}
          >
            <Input
              allowClear
              value={keywordInput}
              maxLength={100}
              placeholder="视频名称或 FileId 模糊搜索"
              onChange={(event) => setKeywordInput(event.target.value)}
              onPressEnter={handleSearch}
            />
          </Form.Item>
          <Form.Item label="入库状态">
            <Select
              value={importedFilter}
              style={{ width: 130 }}
              options={IMPORT_FILTER_OPTIONS}
              onChange={(value: RemoteVodImportFilter) =>
                setImportedFilter(value)
              }
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
      </Card>

      {error ? (
        <Alert
          type="error"
          showIcon
          className="mb-4"
          message="VOD 视频库加载失败"
          description={error}
          action={
            <Button
              size="small"
              onClick={() => void load(page, pageSize, keyword, importedFilter)}
            >
              重试
            </Button>
          }
        />
      ) : null}

      <Card styles={{ body: { padding: 0 } }}>
        <Table<RemoteVodVideo>
          rowKey="file_id"
          columns={columns}
          dataSource={items}
          loading={loading}
          scroll={{ x: 980 }}
          title={() => (
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              共 {total} 个远程视频
              {keyword ? ` · 搜索「${keyword}」` : ''}
              {importedFilter === 'imported'
                ? ' · 仅已入库'
                : importedFilter === 'not_imported'
                  ? ' · 仅未入库'
                  : ''}
            </Typography.Text>
          )}
          locale={{
            emptyText: loading
              ? '正在读取腾讯云 VOD…'
              : error
                ? '加载失败，请重试'
                : '没有符合条件的视频'
          }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: PAGE_SIZE_OPTIONS,
            showTotal: (count) => `共 ${count} 个`,
            onChange: (nextPage, nextPageSize) =>
              void load(nextPage, nextPageSize, keyword, importedFilter)
          }}
        />
      </Card>

      <Modal
        open={importTarget !== null}
        title="入库到本地媒资库"
        width={520}
        okText={importing ? '入库中…' : '确认入库'}
        cancelText="取消"
        okButtonProps={{
          loading: importing,
          disabled: !importName.trim() || importing
        }}
        onOk={() => void handleImport()}
        onCancel={closeImport}
        maskClosable={!importing}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 14 }}
          message="入库只写入本地索引，不会复制视频文件。转码中的视频会先以「转码中」状态入库。"
        />

        {importTarget ? (
          <>
            <Typography.Text
              type="secondary"
              style={{ display: 'block', fontSize: 12 }}
            >
              FileId
            </Typography.Text>
            <Typography.Text
              copyable={{ text: importTarget.file_id }}
              style={{ display: 'block', marginBottom: 12, fontSize: 12 }}
            >
              {importTarget.file_id}
            </Typography.Text>

            <Typography.Text
              type="secondary"
              style={{ display: 'block', marginBottom: 4, fontSize: 12 }}
            >
              视频名称
            </Typography.Text>
            <Input
              value={importName}
              maxLength={200}
              showCount
              autoFocus
              disabled={importing}
              placeholder="默认使用 VOD 名称"
              onChange={(event) => setImportName(event.target.value)}
            />
          </>
        ) : null}
      </Modal>

      <Modal
        open={localTarget !== null}
        title="本地媒资"
        width={560}
        destroyOnClose
        footer={<Button onClick={() => setLocalTarget(null)}>关闭</Button>}
        onCancel={() => setLocalTarget(null)}
      >
        {localTarget?.imported ? (
          <>
            <MediaCover
              coverUrl={localTarget.cover_url}
              title={localTarget.imported.video_name}
              height={200}
              durationSeconds={localTarget.duration_seconds}
            />

            {localTarget.imported.status === 2 &&
            localTarget.imported.fail_reason ? (
              <Alert
                type="error"
                showIcon
                style={{ marginTop: 12 }}
                message="转码失败"
                description={localTarget.imported.fail_reason}
              />
            ) : null}

            <Descriptions
              column={1}
              size="small"
              style={{ marginTop: 16 }}
              items={[
                {
                  key: 'name',
                  label: '本地名称',
                  children: localTarget.imported.video_name
                },
                {
                  key: 'id',
                  label: '媒资 ID',
                  children: `#${localTarget.imported.media_id}`
                },
                {
                  key: 'status',
                  label: '转码状态',
                  children: (
                    <MediaStatusTag status={localTarget.imported.status} />
                  )
                },
                {
                  key: 'file_id',
                  label: 'FileId',
                  children: (
                    <Typography.Text copyable style={{ fontSize: 12 }}>
                      {localTarget.file_id}
                    </Typography.Text>
                  )
                }
              ]}
            />

            <Alert
              type="info"
              showIcon
              style={{ marginTop: 12 }}
              message="后台不加载、不播放视频。加密播放地址仅在学员端通过后端鉴权接口签发。"
            />

            <Button
              style={{ marginTop: 12 }}
              onClick={() => {
                setLocalTarget(null)
                navigate('/media')
              }}
            >
              前往媒资管理
            </Button>
          </>
        ) : null}
      </Modal>
    </div>
  )
}
