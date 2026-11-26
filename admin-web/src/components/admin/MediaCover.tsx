import { useEffect, useState, type ReactNode } from 'react'
import { PlayCircleOutlined } from '@ant-design/icons'

import { formatDuration } from '../../utils/format'

interface MediaCoverProps {
  coverUrl: string | null | undefined
  title: string
  height?: number
  /** 不传时不展示右下角时长。 */
  durationSeconds?: number
  /** 左上角角标，例如转码状态或入库状态。 */
  badge?: ReactNode
  emptyText?: string
}

/** 媒资封面：VOD 首帧截图，缺失或加载失败时展示占位。后台不播放视频。 */
export default function MediaCover({
  coverUrl,
  title,
  height = 152,
  durationSeconds,
  badge,
  emptyText = '暂无封面'
}: MediaCoverProps) {
  const [broken, setBroken] = useState(false)

  useEffect(() => {
    setBroken(false)
  }, [coverUrl])

  const showImage = Boolean(coverUrl) && !broken

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
          src={coverUrl ?? ''}
          alt={`${title} 封面`}
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
          {emptyText}
        </div>
      )}

      {badge ? (
        <div style={{ position: 'absolute', top: 8, left: 8 }}>{badge}</div>
      ) : null}

      {durationSeconds !== undefined ? (
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
          {formatDuration(durationSeconds)}
        </div>
      ) : null}
    </div>
  )
}
