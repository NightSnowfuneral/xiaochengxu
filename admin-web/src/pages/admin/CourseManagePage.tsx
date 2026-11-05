import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Col,
  Collapse,
  Divider,
  Form,
  Image,
  Input,
  Modal,
  Popconfirm,
  Row,
  Space,
  Switch,
  Table,
  Tooltip,
  Typography
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'

import { getErrorMessage } from '../../api/request'
import AdminImageUpload from '../../components/admin/ImageUpload'
import AdminPageHeader from '../../components/admin/PageHeader'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  createCourse,
  deleteCourse,
  fetchCourses,
  selectCourseManage,
  updateCourse
} from '../../store/slices/courseManageSlice'
import type { Course, CourseCreatePayload } from '../../types'
import {
  centsToYuanInput,
  formatDateTime,
  formatMoney,
  parseYuanToCents
} from '../../utils/format'
import { isHttpUrl } from '../../utils/validation'

interface CourseFilterValues {
  keyword?: string
}

interface CourseFormValues {
  title: string
  lecturer: string
  description: string
  priceYuan: string
  cover_big: string
  cover_small: string
  icon_url: string
  is_hot_topic: boolean
}

const EMPTY_COURSE_FORM: CourseFormValues = {
  title: '',
  lecturer: '',
  description: '',
  priceYuan: '0.00',
  cover_big: '',
  cover_small: '',
  icon_url: '',
  is_hot_topic: false
}

function toFormValues(course: Course | null): CourseFormValues {
  if (!course) {
    return { ...EMPTY_COURSE_FORM }
  }
  return {
    title: course.title,
    lecturer: course.lecturer,
    description: course.description,
    priceYuan: centsToYuanInput(course.price),
    cover_big: course.cover_big,
    cover_small: course.cover_small,
    icon_url: course.icon_url,
    is_hot_topic: course.is_hot_topic
  }
}

export default function CourseManagePage() {
  const dispatch = useAppDispatch()
  const navigate = useNavigate()
  const { message } = AntdApp.useApp()
  const [filterForm] = Form.useForm<CourseFilterValues>()
  const [courseForm] = Form.useForm<CourseFormValues>()

  const {
    items,
    total,
    page,
    pageSize,
    keyword: appliedKeyword,
    hotOnly: appliedHotOnly,
    loading,
    error,
    saving,
    deletingId
  } = useAppSelector(selectCourseManage)

  const [formOpen, setFormOpen] = useState(false)
  const [editingCourse, setEditingCourse] = useState<Course | null>(null)
  const [hotOnlyInput, setHotOnlyInput] = useState(false)

  const load = (
    nextPage: number,
    nextPageSize = pageSize,
    nextKeyword = appliedKeyword,
    nextHotOnly = appliedHotOnly
  ) => {
    void dispatch(
      fetchCourses({
        page: nextPage,
        pageSize: nextPageSize,
        keyword: nextKeyword,
        hotOnly: nextHotOnly
      })
    )
  }

  useEffect(() => {
    load(1, 20, '', false)
    // 首次进入加载默认列表。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dispatch])

  const openCreate = () => {
    setEditingCourse(null)
    setFormOpen(true)
  }

  const openEdit = (course: Course) => {
    setEditingCourse(course)
    setFormOpen(true)
  }

  useEffect(() => {
    if (!formOpen) {
      return
    }
    courseForm.setFieldsValue(toFormValues(editingCourse))
  }, [formOpen, editingCourse, courseForm])

  const handleFinish = async (values: CourseFormValues) => {
    const price = parseYuanToCents(values.priceYuan)
    if (price === null) {
      return
    }
    const payload: CourseCreatePayload = {
      title: values.title.trim(),
      lecturer: values.lecturer.trim(),
      description: values.description.trim(),
      price,
      cover_big: values.cover_big.trim(),
      cover_small: values.cover_small.trim(),
      icon_url: values.icon_url.trim(),
      is_hot_topic: Boolean(values.is_hot_topic)
    }

    try {
      if (editingCourse) {
        await dispatch(
          updateCourse({ id: editingCourse.id, payload })
        ).unwrap()
        message.success('课程已更新')
      } else {
        await dispatch(createCourse(payload)).unwrap()
        message.success('课程已创建，可继续添加课时')
      }
      setFormOpen(false)
      setEditingCourse(null)
      load(editingCourse ? page : 1, pageSize, appliedKeyword, appliedHotOnly)
    } catch (saveError) {
      message.error(getErrorMessage(saveError))
    }
  }

  const handleHotToggle = async (course: Course, checked: boolean) => {
    try {
      await dispatch(
        updateCourse({
          id: course.id,
          payload: { is_hot_topic: checked }
        })
      ).unwrap()
      message.success(checked ? '已加入首页热门' : '已取消首页热门')
      load(page, pageSize, appliedKeyword, appliedHotOnly)
    } catch (toggleError) {
      message.error(getErrorMessage(toggleError))
    }
  }

  const handleDelete = async (course: Course) => {
    try {
      await dispatch(deleteCourse(course.id)).unwrap()
      message.success(`课程「${course.title}」已删除`)
      const nextPage = items.length === 1 && page > 1 ? page - 1 : page
      load(nextPage, pageSize, appliedKeyword, appliedHotOnly)
    } catch (deleteError) {
      message.error(getErrorMessage(deleteError))
    }
  }

  const columns: ColumnsType<Course> = [
    {
      title: '课程',
      dataIndex: 'title',
      key: 'course',
      width: 330,
      render: (_value, course) => (
        <Space size={12}>
          <Image
            src={course.cover_small}
            alt=""
            width={64}
            height={42}
            style={{ objectFit: 'cover', borderRadius: 8 }}
            preview={false}
            fallback="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI2NCIgaGVpZ2h0PSI0MiI+PHJlY3Qgd2lkdGg9IjY0IiBoZWlnaHQ9IjQyIiBmaWxsPSIjZjVmNWY0Ii8+PC9zdmc+"
          />
          <div style={{ minWidth: 0 }}>
            <Tooltip title={course.title}>
              <Typography.Text
                strong
                ellipsis
                style={{ display: 'block', maxWidth: 230 }}
              >
                {course.title}
              </Typography.Text>
            </Tooltip>
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              ID #{course.id}
            </Typography.Text>
          </div>
        </Space>
      )
    },
    {
      title: '讲师',
      dataIndex: 'lecturer',
      key: 'lecturer',
      width: 130,
      ellipsis: { showTitle: false },
      render: (value: string) => <Tooltip title={value}>{value}</Tooltip>
    },
    {
      title: '价格',
      dataIndex: 'price',
      key: 'price',
      width: 110,
      render: (value: number) => (
        <Typography.Text strong>{formatMoney(value)}</Typography.Text>
      )
    },
    {
      title: '上架',
      key: 'published',
      width: 90,
      render: () => (
        <Tooltip title="课程创建后即上架；当前数据模型没有下架字段">
          <Switch size="small" checked disabled />
        </Tooltip>
      )
    },
    {
      title: '热门',
      dataIndex: 'is_hot_topic',
      key: 'is_hot_topic',
      width: 90,
      render: (value: boolean, course) => (
        <Switch
          size="small"
          checked={value}
          loading={saving}
          onChange={(checked) => void handleHotToggle(course, checked)}
        />
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
    {
      title: '操作',
      key: 'actions',
      width: 180,
      fixed: 'right',
      render: (_value, course) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => openEdit(course)}>
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            onClick={() => navigate(`/lessons?courseId=${course.id}`)}
          >
            课时
          </Button>
          <Popconfirm
            title="删除课程？"
            description="删除后不可恢复；存在课时、订单或授权记录时后端会拒绝删除。"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true, loading: deletingId === course.id }}
            onConfirm={() => handleDelete(course)}
          >
            <Button type="link" size="small" danger disabled={deletingId !== null}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      )
    }
  ]

  return (
    <div>
      <AdminPageHeader
        eyebrow="COURSES"
        title="课程管理"
        description="维护课程基础信息、价格与三张独立图片。课程删除后不可恢复；存在课时、订单、课程授权或赠课记录的课程会被后端拒绝删除。"
        extra={
          <>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => load(page, pageSize)}
              loading={loading}
            >
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              新增课程
            </Button>
          </>
        }
      />

      <Card className="mb-4">
        <Form<CourseFilterValues>
          form={filterForm}
          layout="inline"
          initialValues={{ keyword: '' }}
          onFinish={(values) =>
            load(1, pageSize, values.keyword?.trim() ?? '', hotOnlyInput)
          }
          style={{ rowGap: 12 }}
        >
          <Form.Item
            name="keyword"
            label="课程名称"
            style={{ flex: '1 1 240px', maxWidth: 380 }}
          >
            <Input
              allowClear
              placeholder="输入课程标题搜索"
              maxLength={100}
              style={{ width: '100%' }}
            />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={loading}>
                查询
              </Button>
              <Button
                onClick={() => {
                  filterForm.resetFields()
                  setHotOnlyInput(false)
                  load(1, pageSize, '', false)
                }}
              >
                重置
              </Button>
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
                <Space size={8}>
                  <Switch
                    size="small"
                    checked={hotOnlyInput}
                    onChange={setHotOnlyInput}
                  />
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    只看首页热门课程
                  </Typography.Text>
                </Space>
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
          message="课程列表加载失败"
          description={error}
          action={
            <Button size="small" onClick={() => load(page, pageSize)}>
              重试
            </Button>
          }
        />
      ) : null}

      <Card styles={{ body: { padding: 0 } }}>
        <Table<Course>
          rowKey="id"
          columns={columns}
          dataSource={items}
          loading={loading}
          scroll={{ x: 1100 }}
          title={() => (
            <Space size={8} wrap>
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                共 {total} 门课程
              </Typography.Text>
              {appliedKeyword ? (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  · 关键词「{appliedKeyword}」
                </Typography.Text>
              ) : null}
              {appliedHotOnly ? (
                <Typography.Text style={{ fontSize: 12, color: '#a47436' }}>
                  · 仅热门
                </Typography.Text>
              ) : null}
            </Space>
          )}
          locale={{
            emptyText: loading
              ? '正在加载课程…'
              : '暂无符合条件的课程，点击「新增课程」开始创建'
          }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: ['10', '20', '50'],
            showTotal: (count) => `共 ${count} 门`,
            onChange: (nextPage, nextPageSize) =>
              load(nextPage, nextPageSize, appliedKeyword, appliedHotOnly)
          }}
        />
      </Card>

      <Modal
        open={formOpen}
        title={editingCourse ? '编辑课程' : '新增课程'}
        width={580}
        okText="保存课程"
        cancelText="取消"
        confirmLoading={saving}
        onOk={() => courseForm.submit()}
        onCancel={() => {
          if (!saving) {
            setFormOpen(false)
            setEditingCourse(null)
          }
        }}
        destroyOnClose
      >
        <Form<CourseFormValues>
          form={courseForm}
          layout="vertical"
          requiredMark
          initialValues={EMPTY_COURSE_FORM}
          onFinish={(values) => void handleFinish(values)}
          preserve={false}
        >
          <Divider orientation="left" plain style={{ marginTop: 0 }}>
            基础信息
          </Divider>

          <Form.Item
            name="title"
            label="课程标题"
            rules={[
              { required: true, whitespace: true, message: '请输入课程标题' },
              { max: 200, message: '课程标题不能超过 200 个字符' }
            ]}
          >
            <Input placeholder="例如：商学院增长实战课" maxLength={200} />
          </Form.Item>

          <Form.Item
            name="lecturer"
            label="讲师"
            rules={[
              { required: true, whitespace: true, message: '请输入讲师姓名' },
              { max: 100, message: '讲师姓名不能超过 100 个字符' }
            ]}
          >
            <Input placeholder="讲师姓名" maxLength={100} />
          </Form.Item>

          <Form.Item
            name="description"
            label="课程描述"
            rules={[
              { required: true, whitespace: true, message: '请输入课程描述' },
              { max: 10000, message: '课程描述不能超过 10000 个字符' }
            ]}
          >
            <Input.TextArea
              rows={4}
              maxLength={10000}
              showCount
              placeholder="介绍课程内容、适合人群与学习收获"
            />
          </Form.Item>

          <Divider orientation="left" plain>
            价格与分类
          </Divider>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="priceYuan"
                label="课程价格（元）"
                rules={[
                  { required: true, message: '请输入课程价格' },
                  {
                    validator: (_rule, value: string) =>
                      parseYuanToCents(value ?? '') === null
                        ? Promise.reject(
                            new Error('请输入合法金额，最多两位小数')
                          )
                        : Promise.resolve()
                  }
                ]}
                extra="以元输入，提交时转换为分；0 表示免费课"
              >
                <Input prefix="¥" placeholder="0.00" inputMode="decimal" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="is_hot_topic"
                label="首页热门"
                valuePropName="checked"
              >
                <Switch checkedChildren="热门" unCheckedChildren="普通" />
              </Form.Item>
            </Col>
          </Row>

          <Divider orientation="left" plain>
            课程图片
          </Divider>

          <Row gutter={12}>
            <Col span={8}>
              <Form.Item
                name="cover_big"
                label="封面大图"
                rules={[
                  { required: true, message: '请上传封面大图' },
                  {
                    validator: (_rule, value: string) =>
                      value && !isHttpUrl(value)
                        ? Promise.reject(
                            new Error('必须是 http(s) 图片地址')
                          )
                        : Promise.resolve()
                  }
                ]}
              >
                <AdminImageUpload label="封面大图" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="cover_small"
                label="列表封面"
                rules={[
                  { required: true, message: '请上传列表封面' },
                  {
                    validator: (_rule, value: string) =>
                      value && !isHttpUrl(value)
                        ? Promise.reject(
                            new Error('必须是 http(s) 图片地址')
                          )
                        : Promise.resolve()
                  }
                ]}
              >
                <AdminImageUpload label="列表封面" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="icon_url"
                label="课程图标"
                rules={[
                  { required: true, message: '请上传课程图标' },
                  {
                    validator: (_rule, value: string) =>
                      value && !isHttpUrl(value)
                        ? Promise.reject(
                            new Error('必须是 http(s) 图片地址')
                          )
                        : Promise.resolve()
                  }
                ]}
              >
                <AdminImageUpload label="课程图标" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  )
}
