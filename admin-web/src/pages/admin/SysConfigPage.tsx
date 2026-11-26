import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Descriptions,
  Empty,
  Input,
  Popconfirm,
  Skeleton,
  Space,
  Tabs,
  Tag,
  Typography
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'

import { getErrorMessage } from '../../api/request'
import AppointmentSlotConfigPanel from '../../components/admin/AppointmentSlotConfigPanel'
import AdminPageHeader from '../../components/admin/PageHeader'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  fetchConfigs,
  resetAllConfigs,
  resetConfig,
  selectSysConfig,
  updateConfig
} from '../../store/slices/sysConfigSlice'
import type { SystemConfig } from '../../types'
import { formatDateTime } from '../../utils/format'

const MAX_CONFIG_LENGTH = 4096
const TAB_KEYS = new Set(['tab_home_text', 'tab_course_text'])
const SECRET_PATTERN = /(secret|password|private|api_?key|token|mch_?key)/i

interface ConfigGroup {
  key: string
  title: string
  description: string
  items: SystemConfig[]
}

const GROUP_DEFINITIONS: Array<{
  key: string
  title: string
  description: string
  keys: string[]
}> = [
  {
    key: 'home',
    title: '首页文案',
    description: '小程序首页的标题、副标题、热门板块标题与公告。',
    keys: ['home_title', 'home_subtitle', 'home_hot_title', 'home_notice']
  },
  {
    key: 'course',
    title: '课程广场',
    description: '课程广场页面标题与搜索框占位文案。',
    keys: ['course_square_title', 'search_placeholder']
  },
  {
    key: 'tabs',
    title: '底部 Tab 文案',
    description: '小程序固定两个 Tab 的文字，不支持新增、删除或改顺序。',
    keys: ['tab_home_text', 'tab_course_text']
  }
]

interface ConfigRowProps {
  item: SystemConfig
  draft: string
  busy: boolean
  saving: boolean
  resetting: boolean
  last: boolean
  onChange: (value: string) => void
  onSave: () => void
  onReset: () => void
}

function ConfigRow({
  item,
  draft,
  busy,
  saving,
  resetting,
  last,
  onChange,
  onSave,
  onReset
}: ConfigRowProps) {
  const isTab = TAB_KEYS.has(item.config_key)
  const isSecret = SECRET_PATTERN.test(item.config_key)
  const isAtDefault = item.config_value === item.default_value
  const dirty = draft !== item.config_value

  return (
    <div
      style={{
        padding: '16px 0',
        borderBottom: last ? 'none' : '1px solid #f5f5f4'
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 8
        }}
      >
        <div style={{ minWidth: 0 }}>
          <Space size={6} wrap>
            <Typography.Text strong>
              {item.description || item.config_key}
            </Typography.Text>
            {isTab ? (
              <Tag color="warning" bordered={false} style={{ borderRadius: 999 }}>
                底部 Tab
              </Tag>
            ) : null}
            {isSecret ? (
              <Tag color="error" bordered={false} style={{ borderRadius: 999 }}>
                敏感字段
              </Tag>
            ) : null}
            {isAtDefault ? (
              <Tag bordered={false} style={{ borderRadius: 999 }}>
                默认值
              </Tag>
            ) : (
              <Tag color="success" bordered={false} style={{ borderRadius: 999 }}>
                已自定义
              </Tag>
            )}
          </Space>
          <div style={{ marginTop: 3 }}>
            <Typography.Text
              code
              style={{ fontSize: 11, wordBreak: 'break-all' }}
            >
              {item.config_key}
            </Typography.Text>
          </div>
        </div>
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
          更新于 {formatDateTime(item.updated_at)}
        </Typography.Text>
      </div>

      <div style={{ marginTop: 10 }}>
        {isSecret ? (
          <Input.Password
            value={draft}
            onChange={(event) => onChange(event.target.value)}
            maxLength={MAX_CONFIG_LENGTH}
            visibilityToggle
            disabled={busy}
            placeholder="请输入配置值"
          />
        ) : isTab ? (
          <Input
            value={draft}
            onChange={(event) => onChange(event.target.value)}
            maxLength={MAX_CONFIG_LENGTH}
            disabled={busy}
            placeholder="请输入 Tab 文字"
          />
        ) : (
          <Input.TextArea
            value={draft}
            onChange={(event) => onChange(event.target.value)}
            rows={3}
            maxLength={MAX_CONFIG_LENGTH}
            showCount
            disabled={busy}
            style={{ resize: 'none' }}
          />
        )}

        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            gap: 8,
            marginTop: 4,
            fontSize: 11,
            color: '#a8a29e'
          }}
        >
          <span>{isTab ? '建议保持简短；留空会导致 Tab 无文字展示。' : ''}</span>
          <span>
            {isSecret ? '值不会明文回显给其他管理员 · ' : ''}
            {draft.length} / {MAX_CONFIG_LENGTH}
            {dirty ? (
              <span style={{ marginLeft: 6, color: '#b45309' }}>未保存</span>
            ) : null}
          </span>
        </div>
      </div>

      <div
        style={{
          marginTop: 10,
          padding: '8px 10px',
          borderRadius: 8,
          background: '#fafaf9',
          fontSize: 11,
          color: '#78716c'
        }}
      >
        出厂默认值：
        <Typography.Text
          type="secondary"
          style={{ fontSize: 11, wordBreak: 'break-all' }}
        >
          {item.default_value || '（空字符串）'}
        </Typography.Text>
      </div>

      <div
        style={{
          display: 'flex',
          justifyContent: 'flex-end',
          marginTop: 10
        }}
      >
        <Space size={8}>
          <Popconfirm
            title="恢复该项默认值？"
            description={
              <span>
                将把「{item.config_key}」恢复为出厂默认
                「{item.default_value || '空字符串'}」。未保存的编辑会丢失。
              </span>
            }
            okText="恢复默认"
            cancelText="取消"
            okButtonProps={{ danger: true, loading: resetting }}
            onConfirm={onReset}
          >
            <Button
              size="small"
              disabled={busy || (isAtDefault && !dirty)}
            >
              恢复默认
            </Button>
          </Popconfirm>
          <Button
            size="small"
            type="primary"
            disabled={!dirty || busy}
            loading={saving}
            onClick={onSave}
          >
            保存
          </Button>
        </Space>
      </div>
    </div>
  )
}

interface ServerManagedTabProps {
  title: string
  description: string
  fields: Array<{ label: string; note: string }>
  warning?: string
}

function ServerManagedTab({
  title,
  description,
  fields,
  warning
}: ServerManagedTabProps) {
  return (
    <div>
      <Alert
        type={warning ? 'warning' : 'info'}
        showIcon
        message={title}
        description={description}
        style={{ marginBottom: 16 }}
      />
      {warning ? (
        <Alert
          type="warning"
          showIcon
          message={warning}
          style={{ marginBottom: 16 }}
        />
      ) : null}
      <Descriptions
        bordered
        size="small"
        column={1}
        items={fields.map((field) => ({
          key: field.label,
          label: field.label,
          children: (
            <Space size={8} wrap>
              <Tag bordered={false}>服务端维护</Tag>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {field.note}
              </Typography.Text>
            </Space>
          )
        }))}
      />
      <Alert
        type="error"
        showIcon
        style={{ marginTop: 16 }}
        message="密钥永不下发浏览器"
        description="这些配置不属于系统配置接口的返回字段，后台不保存、不展示、也不提供编辑入口；APIv3 密钥、商户私钥等敏感值只允许通过部署环境的 .env 或挂载文件维护。"
      />
    </div>
  )
}

export default function SysConfigPage() {
  const dispatch = useAppDispatch()
  const { modal, message } = AntdApp.useApp()
  const {
    items,
    loading,
    error,
    savingKey,
    resettingKey,
    resettingAll
  } = useAppSelector(selectSysConfig)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [activeTab, setActiveTab] = useState('site')

  const busy =
    loading ||
    savingKey !== null ||
    resettingKey !== null ||
    resettingAll

  const loadConfigs = useCallback(async () => {
    try {
      const response = await dispatch(fetchConfigs()).unwrap()
      setDrafts(
        Object.fromEntries(
          response.items.map((item) => [
            item.config_key,
            item.config_value
          ])
        )
      )
    } catch {
      // 错误信息由 sysConfigSlice.error 展示。
    }
  }, [dispatch])

  useEffect(() => {
    void loadConfigs()
  }, [loadConfigs])

  const groups = useMemo<ConfigGroup[]>(() => {
    const used = new Set<string>()
    const result = GROUP_DEFINITIONS.map((definition) => {
      const groupedItems = definition.keys
        .map((key) => items.find((item) => item.config_key === key))
        .filter((item): item is SystemConfig => Boolean(item))
      groupedItems.forEach((item) => used.add(item.config_key))
      return {
        key: definition.key,
        title: definition.title,
        description: definition.description,
        items: groupedItems
      }
    }).filter((group) => group.items.length > 0)

    const leftovers = items.filter((item) => !used.has(item.config_key))
    if (leftovers.length > 0) {
      result.push({
        key: 'other',
        title: '其他配置',
        description: '后端新增的展示文案配置，自动归入此分组。',
        items: leftovers
      })
    }
    return result
  }, [items])

  const handleSave = async (item: SystemConfig) => {
    const configValue = drafts[item.config_key] ?? ''
    if (configValue.length > MAX_CONFIG_LENGTH) {
      message.error(
        `配置「${item.config_key}」不能超过 ${MAX_CONFIG_LENGTH} 个字符`
      )
      return
    }
    try {
      const updated = await dispatch(
        updateConfig({ configKey: item.config_key, configValue })
      ).unwrap()
      setDrafts((previous) => ({
        ...previous,
        [updated.config_key]: updated.config_value
      }))
      message.success(
        `「${item.description || item.config_key}」已保存，小程序下次 onShow 生效`
      )
    } catch (saveError) {
      message.error(getErrorMessage(saveError))
    }
  }

  const handleResetOne = async (item: SystemConfig) => {
    try {
      const updated = await dispatch(resetConfig(item.config_key)).unwrap()
      setDrafts((previous) => ({
        ...previous,
        [updated.config_key]: updated.config_value
      }))
      message.success(
        `「${item.description || item.config_key}」已恢复默认值`
      )
    } catch (resetError) {
      message.error(getErrorMessage(resetError))
    }
  }

  const handleResetAll = () => {
    modal.confirm({
      title: '站点文案全部恢复出厂默认？',
      content:
        '所有站点文案都会恢复为出厂默认值，所有未保存的编辑内容都会丢失。该操作无法撤销。',
      okText: '恢复默认',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const updatedItems = await dispatch(resetAllConfigs()).unwrap()
          setDrafts(
            Object.fromEntries(
              updatedItems.map((item) => [
                item.config_key,
                item.config_value
              ])
            )
          )
          message.success('站点文案已全部恢复为出厂默认值')
        } catch (resetError) {
          message.error(getErrorMessage(resetError))
        }
      }
    })
  }

  const siteCopyContent =
    loading && items.length === 0 ? (
      <Card>
        <Skeleton active paragraph={{ rows: 8 }} />
      </Card>
    ) : items.length === 0 ? (
      <Card>
        <Empty
          description={
            <div>
              <Typography.Text strong>暂无可编辑的配置项</Typography.Text>
              <div style={{ marginTop: 4, fontSize: 12, color: '#a8a29e' }}>
                配置由后端启动钩子初始化，请确认后端已正常启动。
              </div>
            </div>
          }
        />
      </Card>
    ) : (
      <div>
        {error ? (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message="系统配置加载失败"
            description={error}
            action={
              <Button size="small" onClick={() => void loadConfigs()}>
                重试
              </Button>
            }
          />
        ) : null}

        {groups.map((group) => (
          <Card
            key={group.key}
            title={group.title}
            extra={
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {group.description}
              </Typography.Text>
            }
            style={{ marginBottom: 16 }}
          >
            {group.items.map((item, index) => (
              <ConfigRow
                key={item.config_key}
                item={item}
                draft={drafts[item.config_key] ?? ''}
                busy={busy}
                saving={savingKey === item.config_key}
                resetting={resettingKey === item.config_key}
                last={index === group.items.length - 1}
                onChange={(value) =>
                  setDrafts((previous) => ({
                    ...previous,
                    [item.config_key]: value
                  }))
                }
                onSave={() => void handleSave(item)}
                onReset={() => void handleResetOne(item)}
              />
            ))}
          </Card>
        ))}
      </div>
    )

  return (
    <div>
      <AdminPageHeader
        eyebrow="SYSTEM"
        title="系统配置"
        description="站点文案配置只承载展示文案，不承载权限或价格；预约时段规则在「预约设置」中单独维护。配置键由后端初始化且不可修改、不可新增或删除。"
        extra={
          <>
            <Button
              icon={<ReloadOutlined />}
              loading={loading}
              onClick={() => void loadConfigs()}
            >
              刷新
            </Button>
            {activeTab === 'site' ? (
              <Button
                danger
                disabled={busy || items.length === 0}
                loading={resettingAll}
                onClick={handleResetAll}
              >
                站点文案恢复默认
              </Button>
            ) : null}
          </>
        }
      />

      <Alert
        type="info"
        showIcon
        className="mb-4"
        message="配置边界"
        description="后台只能编辑每条配置的当前值，不能修改配置键，也不能新增或删除配置项。修改保存后，小程序在页面 onShow 时拉取最新文案；底部 Tab 固定两个，仅支持修改文字。预约时段规则单独维护，保存后立即影响新预约。"
      />

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
            {
              key: 'wechat',
              label: '微信支付 V3 配置',
              children: (
                <ServerManagedTab
                  title="微信支付 V3 由服务端环境变量维护"
                  description="商户号、证书序列号、APIv3 密钥、商户私钥、微信支付公钥/公钥 ID 与回调地址属于部署级密钥配置，后端系统配置接口不会返回这些字段。"
                  fields={[
                    {
                      label: '商户号 MchID',
                      note: '部署环境变量，按微信商户平台信息配置'
                    },
                    {
                      label: '商户 API 证书序列号',
                      note: '部署环境变量，需与商户证书成对'
                    },
                    {
                      label: 'APIv3 密钥',
                      note: '仅服务端可见，用于回调报文解密'
                    },
                    {
                      label: '商户私钥',
                      note: '只挂载到服务端，永不下发浏览器'
                    },
                    {
                      label: '微信支付公钥 / 公钥 ID',
                      note: '公钥模式需成对配置'
                    },
                    {
                      label: '支付回调地址',
                      note: '部署与微信支付后台共同维护'
                    }
                  ]}
                  warning="若需调整微信支付参数，请修改服务器 .env / secrets 并重启后端；后台不提供密钥查看与掩码展示，避免任何敏感值进入浏览器。"
                />
              )
            },
            {
              key: 'miniapp',
              label: '小程序基础配置',
              children: (
                <ServerManagedTab
                  title="小程序配置由小程序项目与部署环境维护"
                  description="小程序 AppID、AppSecret、后端 API 地址与请求合法域名不属于系统文案配置，后台接口不返回、也不允许修改。"
                  fields={[
                    {
                      label: '小程序 AppID',
                      note: '小程序项目与微信公众平台配置'
                    },
                    {
                      label: '小程序 AppSecret',
                      note: '仅后端环境变量保存，永不下发'
                    },
                    {
                      label: 'API 基础地址',
                      note: '小程序构建变量与 Nginx 反向代理'
                    },
                    {
                      label: '请求合法域名',
                      note: '微信公众平台后台配置'
                    },
                    {
                      label: '底部 Tab 文字',
                      note: '可在「站点文案」中修改'
                    }
                  ]}
                  warning="小程序发布相关参数需要重新构建或登录微信公众平台调整，无法在管理后台在线修改。"
                />
              )
            },
            {
              key: 'site',
              label: '站点文案',
              children: siteCopyContent
            },
            {
              key: 'appointment',
              label: '预约设置',
              children: <AppointmentSlotConfigPanel />
            },
            {
              key: 'support',
              label: '客服信息',
              children: (
                <ServerManagedTab
                  title="客服信息暂未定义为系统配置"
                  description="当前后端系统配置接口只初始化站点文案相关的 7 个键，没有客服电话、客服微信或服务时间等配置键，因此本页不提供伪造的编辑表单。"
                  fields={[
                    {
                      label: '客服电话',
                      note: '暂无对应 config_key'
                    },
                    {
                      label: '客服微信',
                      note: '暂无对应 config_key'
                    },
                    {
                      label: '服务时间',
                      note: '暂无对应 config_key'
                    }
                  ]}
                  warning="如需在后台维护客服信息，请先由后端新增配置键并初始化默认值，再接入本页面；在此之前请通过小程序页面静态文案或部署配置维护。"
                />
              )
            }
        ]}
      />

      <Typography.Paragraph
        type="secondary"
        style={{ marginTop: 4, fontSize: 11, lineHeight: '20px' }}
      >
        配置保存会立即写入数据库，影响所有用户下一次 onShow 拉取到的展示文案。
        价格、权限与业务规则不通过系统配置管理。所有密钥类配置由服务端环境变量
        维护，前端只读取公开文案。
      </Typography.Paragraph>
    </div>
  )
}
