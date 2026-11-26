import { useCallback, useEffect, useState } from 'react'
import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Checkbox,
  Col,
  Form,
  InputNumber,
  Row,
  Skeleton,
  Space,
  Switch,
  TimePicker,
  Typography
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'

import {
  fetchAppointmentSlotConfig,
  saveAppointmentSlotConfig
} from '../../api/appointmentApi'
import { getErrorMessage } from '../../api/request'
import type {
  AppointmentSlotConfig,
  AppointmentSlotConfigPayload
} from '../../types'
import { formatShanghaiDateTime } from '../../utils/format'

const WEEKDAY_OPTIONS = [
  { label: '周一', value: 1 },
  { label: '周二', value: 2 },
  { label: '周三', value: 3 },
  { label: '周四', value: 4 },
  { label: '周五', value: 5 },
  { label: '周六', value: 6 },
  { label: '周日', value: 7 }
]

interface SlotConfigFormValues {
  weekdays: number[]
  startTime: Dayjs
  endTime: Dayjs
  slot_minutes: number
  slot_capacity: number
  advance_days: number
  min_advance_hours: number
  enabled: boolean
}

function toFormValues(config: AppointmentSlotConfig): SlotConfigFormValues {
  return {
    weekdays: config.weekdays,
    startTime: dayjs(`2000-01-01T${config.work_start_time}:00`),
    endTime: dayjs(`2000-01-01T${config.work_end_time}:00`),
    slot_minutes: config.slot_minutes,
    slot_capacity: config.slot_capacity,
    advance_days: config.advance_days,
    min_advance_hours: config.min_advance_hours,
    enabled: config.enabled
  }
}

/** 系统配置 · 预约设置：维护可预约星期、工作时段与时段规则。 */
export default function AppointmentSlotConfigPanel() {
  const { message } = AntdApp.useApp()
  const [form] = Form.useForm<SlotConfigFormValues>()
  const [config, setConfig] = useState<AppointmentSlotConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetchAppointmentSlotConfig()
      setConfig(response)
      form.setFieldsValue(toFormValues(response))
    } catch (loadError) {
      setError(getErrorMessage(loadError))
    } finally {
      setLoading(false)
    }
  }, [form])

  useEffect(() => {
    void load()
  }, [load])

  const handleSave = async (values: SlotConfigFormValues) => {
    if (!values.startTime || !values.endTime) {
      return
    }
    const payload: AppointmentSlotConfigPayload = {
      weekdays: values.weekdays,
      work_start_time: values.startTime.format('HH:mm'),
      work_end_time: values.endTime.format('HH:mm'),
      slot_minutes: values.slot_minutes,
      slot_capacity: values.slot_capacity,
      advance_days: values.advance_days,
      min_advance_hours: values.min_advance_hours,
      enabled: Boolean(values.enabled)
    }
    setSaving(true)
    try {
      const updated = await saveAppointmentSlotConfig(payload)
      setConfig(updated)
      form.setFieldsValue(toFormValues(updated))
      message.success('预约设置已保存，小程序下次进入预约页生效')
    } catch (saveError) {
      message.error(getErrorMessage(saveError))
    } finally {
      setSaving(false)
    }
  }

  if (loading && !config) {
    return (
      <Card>
        <Skeleton active paragraph={{ rows: 6 }} />
      </Card>
    )
  }

  return (
    <div>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="预约时段配置"
        description="按配置的工作时段自动切分预约胶囊；学员只能选择「开始时间 + 最少提前小时数」之后的时段。修改保存后立即影响新预约，不会影响已创建的预约。"
      />

      {error ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message="预约设置加载失败"
          description={error}
          action={
            <Button size="small" onClick={() => void load()}>
              重试
            </Button>
          }
        />
      ) : null}

      <Card
        title="时段规则"
        extra={
          <Space size={12}>
            {config ? (
              <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                更新于 {formatShanghaiDateTime(config.updated_at)}
              </Typography.Text>
            ) : null}
            <Button
              size="small"
              icon={<ReloadOutlined />}
              loading={loading}
              onClick={() => void load()}
            >
              刷新
            </Button>
          </Space>
        }
      >
        <Form<SlotConfigFormValues>
          form={form}
          layout="vertical"
          onFinish={(values) => void handleSave(values)}
          disabled={saving}
        >
          <Form.Item
            name="enabled"
            label="预约功能"
            valuePropName="checked"
            extra="关闭后 C 端不再展示可预约时段，已有预约不受影响。"
          >
            <Switch checkedChildren="开放" unCheckedChildren="关闭" />
          </Form.Item>

          <Form.Item
            name="weekdays"
            label="开放星期"
            rules={[
              {
                required: true,
                type: 'array',
                min: 1,
                message: '至少选择一个开放日'
              }
            ]}
          >
            <Checkbox.Group options={WEEKDAY_OPTIONS} />
          </Form.Item>

          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item
                name="startTime"
                label="工作开始时间"
                rules={[{ required: true, message: '请选择开始时间' }]}
              >
                <TimePicker format="HH:mm" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item
                name="endTime"
                label="工作结束时间"
                rules={[
                  { required: true, message: '请选择结束时间' },
                  {
                    validator: (_rule, value: Dayjs | undefined) => {
                      const start = form.getFieldValue('startTime') as
                        | Dayjs
                        | undefined
                      if (value && start && !value.isAfter(start)) {
                        return Promise.reject(
                          new Error('结束时间必须晚于开始时间')
                        )
                      }
                      return Promise.resolve()
                    }
                  }
                ]}
              >
                <TimePicker format="HH:mm" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item
                name="slot_minutes"
                label="单个时段时长（分钟）"
                rules={[{ required: true, message: '请输入时段时长' }]}
                extra="15-720 分钟；不足一个完整时段的尾部时间不生成胶囊"
              >
                <InputNumber
                  min={15}
                  max={720}
                  precision={0}
                  style={{ width: '100%' }}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item
                name="slot_capacity"
                label="每时段可预约人数"
                rules={[{ required: true, message: '请输入时段容量' }]}
              >
                <InputNumber
                  min={1}
                  max={100}
                  precision={0}
                  style={{ width: '100%' }}
                />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item
                name="advance_days"
                label="可提前预约天数"
                rules={[{ required: true, message: '请输入可提前预约天数' }]}
                extra="包含今天，最多 90 天"
              >
                <InputNumber
                  min={1}
                  max={90}
                  precision={0}
                  style={{ width: '100%' }}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item
                name="min_advance_hours"
                label="最少提前预约（小时）"
                rules={[{ required: true, message: '请输入最少提前小时数' }]}
                extra="同时作为学员取消预约的截止窗口"
              >
                <InputNumber
                  min={0}
                  max={720}
                  precision={0}
                  style={{ width: '100%' }}
                />
              </Form.Item>
            </Col>
          </Row>

          <Space>
            <Button type="primary" htmlType="submit" loading={saving}>
              保存预约设置
            </Button>
            <Button
              disabled={saving || !config}
              onClick={() => config && form.setFieldsValue(toFormValues(config))}
            >
              还原未保存修改
            </Button>
          </Space>
        </Form>
      </Card>
    </div>
  )
}
