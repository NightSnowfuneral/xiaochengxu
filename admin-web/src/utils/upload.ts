import axios from 'axios'

import { getImageUploadPresign } from '../api/courseApi'

const MAX_IMAGE_SIZE = 10 * 1024 * 1024

const IMAGE_TYPES: Record<string, string> = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp'
}

function fileExtension(filename: string): string {
  const normalized = filename.replace(/\\/g, '/')
  const dot = normalized.lastIndexOf('.')
  return dot >= 0 ? normalized.slice(dot + 1).toLowerCase() : ''
}

/**
 * 图片直传 COS：
 * 1. 管理员鉴权请求后端签发短期 PUT 预签名；
 * 2. 浏览器直接 PUT 到 COS，二进制不经过业务服务器；
 * 3. 返回公开访问 URL 供课程三张图片字段使用。
 * 这里使用原生 axios，而不是带 Admin Token 的 apiClient，避免把令牌发给 COS。
 */
export async function uploadImageToCos(
  file: File,
  onProgress?: (percent: number | null) => void
): Promise<string> {
  const extension = fileExtension(file.name)
  const expectedType = IMAGE_TYPES[extension]
  if (!expectedType) {
    throw new Error('仅支持 JPG、JPEG、PNG、WebP 格式的图片')
  }
  if (file.size <= 0) {
    throw new Error('图片文件为空，请重新选择')
  }
  if (file.size > MAX_IMAGE_SIZE) {
    throw new Error('图片不能超过 10MB')
  }

  const declaredType = file.type.trim().toLowerCase()
  if (declaredType) {
    const normalized =
      declaredType === 'image/jpg' ? 'image/jpeg' : declaredType
    if (normalized !== expectedType) {
      throw new Error('图片类型与文件扩展名不一致')
    }
  }

  const presign = await getImageUploadPresign({
    filename: file.name,
    content_type: expectedType,
    expires_in: 600
  })

  try {
    await axios.put(presign.upload_url, file, {
      headers: presign.headers,
      timeout: 60000,
      onUploadProgress: (event) => {
        if (!onProgress) {
          return
        }
        if (event.total && event.total > 0) {
          onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)))
        } else {
          onProgress(null)
        }
      }
    })
  } catch (error) {
    if (axios.isAxiosError(error)) {
      if (!error.response) {
        throw new Error(
          '图片上传失败：无法连接 COS，请检查存储桶 CORS 是否允许 PUT 与 Content-Type 请求头'
        )
      }
      throw new Error(
        `图片上传失败（HTTP ${error.response.status}），请重试或检查 COS 预签名配置`
      )
    }
    throw new Error('图片上传失败，请稍后重试')
  }

  onProgress?.(100)
  return presign.public_url
}
