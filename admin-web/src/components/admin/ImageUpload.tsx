import { useState } from 'react'
import { Input, Progress, Typography, Upload } from 'antd'
import { LoadingOutlined, PictureOutlined } from '@ant-design/icons'

import { uploadImageToCos } from '../../utils/upload'

interface AdminImageUploadProps {
  label: string
  /** 由 Form.Item 注入；单独使用时需要显式传入。 */
  value?: string
  onChange?: (url: string) => void
  disabled?: boolean
}

/**
 * 课程图片上传：沿用原有「后端预签名 → 浏览器直传 COS」逻辑。
 * 同时保留 URL 输入框，便于迁移历史资源。
 */
export default function AdminImageUpload({
  label,
  value = '',
  onChange,
  disabled = false
}: AdminImageUploadProps) {
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState<number | null>(0)
  const [error, setError] = useState<string | null>(null)
  const [broken, setBroken] = useState(false)

  const handleUpload = async (file: File) => {
    setUploading(true)
    setProgress(0)
    setError(null)
    try {
      const publicUrl = await uploadImageToCos(file, setProgress)
      setBroken(false)
      onChange?.(publicUrl)
    } catch (uploadError) {
      setError(
        uploadError instanceof Error
          ? uploadError.message
          : '图片上传失败，请稍后重试'
      )
    } finally {
      setUploading(false)
      setProgress(null)
    }
  }

  return (
    <div>
      <Upload
        accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
        showUploadList={false}
        disabled={disabled || uploading}
        beforeUpload={(file) => {
          void handleUpload(file)
          // 阻止 antd 自行上传，文件由 uploadImageToCos 直传 COS。
          return Upload.LIST_IGNORE
        }}
      >
        <div
          style={{
            position: 'relative',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: 130,
            overflow: 'hidden',
            border: '1px dashed #d6d3d1',
            borderRadius: 8,
            background: '#fafaf9',
            cursor: disabled || uploading ? 'not-allowed' : 'pointer'
          }}
        >
          {value && !broken ? (
            <img
              src={value}
              alt={`${label}预览`}
              onError={() => setBroken(true)}
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'contain'
              }}
            />
          ) : (
            <div style={{ textAlign: 'center', color: '#a8a29e' }}>
              {uploading ? (
                <LoadingOutlined style={{ fontSize: 24 }} />
              ) : (
                <PictureOutlined style={{ fontSize: 24 }} />
              )}
              <div style={{ marginTop: 6, fontSize: 12 }}>
                {uploading ? '上传中…' : '点击上传图片'}
              </div>
            </div>
          )}
        </div>
      </Upload>

      {uploading ? (
        <Progress
          size="small"
          percent={progress ?? 0}
          status="active"
          style={{ marginTop: 8 }}
        />
      ) : null}

      <Input
        size="small"
        value={value}
        onChange={(event) => {
          setBroken(false)
          setError(null)
          onChange?.(event.target.value)
        }}
        placeholder="或粘贴图片 https:// 地址"
        disabled={disabled || uploading}
        style={{ marginTop: 8 }}
      />

      {error ? (
        <Typography.Text type="danger" style={{ fontSize: 12 }}>
          {error}
        </Typography.Text>
      ) : null}
    </div>
  )
}
