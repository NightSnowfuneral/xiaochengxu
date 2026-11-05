import { useEffect, useMemo, useRef, useState } from 'react'
import { Select, Spin } from 'antd'

import { getAdminCourse, listAdminCourses } from '../../api/courseApi'

interface CourseOption {
  value: number
  label: string
}

interface AdminCourseSelectProps {
  /** 由 Form.Item 注入；单独使用时需要显式传入。 */
  value?: number | null
  onChange?: (courseId: number | null) => void
  /** 允许清空并选择「全部课程」 */
  allowClear?: boolean
  placeholder?: string
  disabled?: boolean
}

const SEARCH_DEBOUNCE_MS = 350

/**
 * 课程远程搜索下拉：首次加载 100 门课程，输入标题时防抖远程搜索；
 * 选中值不在当前列表时通过课程详情补齐名称，避免只显示裸 ID。
 */
export default function AdminCourseSelect({
  value = null,
  onChange,
  allowClear = false,
  placeholder = '搜索并选择课程',
  disabled = false
}: AdminCourseSelectProps) {
  const [options, setOptions] = useState<CourseOption[]>([])
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [fallbackTitle, setFallbackTitle] = useState<string | null>(null)
  const debounceRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (debounceRef.current !== null) {
        window.clearTimeout(debounceRef.current)
      }
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listAdminCourses({
      page: 1,
      page_size: 100,
      keyword: keyword.trim() || undefined
    })
      .then((response) => {
        if (cancelled) {
          return
        }
        setOptions(
          response.items.map((course) => ({
            value: course.id,
            label: `#${course.id} · ${course.title}`
          }))
        )
      })
      .catch(() => {
        // 页面上的操作反馈会提示具体错误；这里保持上一次选项。
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [keyword])

  useEffect(() => {
    if (!value) {
      setFallbackTitle(null)
      return
    }
    if (options.some((option) => option.value === value)) {
      return
    }
    let cancelled = false
    getAdminCourse(value)
      .then((course) => {
        if (!cancelled) {
          setFallbackTitle(course.title)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setFallbackTitle(`课程 #${value}`)
        }
      })
    return () => {
      cancelled = true
    }
    // options 加载完成后由 mergedOptions 直接命中，无需重复请求。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  const mergedOptions = useMemo(() => {
    if (!value) {
      return options
    }
    if (options.some((option) => option.value === value)) {
      return options
    }
    return [
      {
        value,
        label: `#${value} · ${fallbackTitle ?? '加载中…'}`
      },
      ...options
    ]
  }, [options, value, fallbackTitle])

  return (
    <Select<number>
      showSearch
      allowClear={allowClear}
      value={value ?? undefined}
      onChange={(nextValue) => onChange?.(nextValue ?? null)}
      onSearch={(nextKeyword) => {
        if (debounceRef.current !== null) {
          window.clearTimeout(debounceRef.current)
        }
        // 防抖远程搜索，避免每次输入都发起请求。
        debounceRef.current = window.setTimeout(() => {
          setKeyword(nextKeyword)
        }, SEARCH_DEBOUNCE_MS)
      }}
      filterOption={false}
      options={mergedOptions}
      loading={loading}
      disabled={disabled}
      placeholder={placeholder}
      style={{ width: '100%' }}
      notFoundContent={
        loading ? (
          <div className="py-3 text-center">
            <Spin size="small" />
          </div>
        ) : (
          '没有匹配的课程'
        )
      }
    />
  )
}
