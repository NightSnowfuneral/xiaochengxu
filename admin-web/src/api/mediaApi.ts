import type {
  PageResponse,
  RemoteVodImportPayload,
  RemoteVodListParams,
  RemoteVodVideo,
  VodMedia,
  VodMediaListParams,
  VodMediaSyncResponse,
  VodMediaUpdatePayload
} from '../types'
import {
  apiDelete,
  apiGet,
  apiPost,
  apiPut,
  apiUpload,
  compactParams
} from './request'

export function listVodMedia(
  params: VodMediaListParams
): Promise<PageResponse<VodMedia>> {
  return apiGet<PageResponse<VodMedia>>('/admin/vod/list', {
    params: compactParams({
      page: params.page,
      page_size: params.page_size,
      keyword: params.keyword,
      file_id: params.file_id,
      status: params.status
    })
  })
}

export function listRemoteVod(
  params: RemoteVodListParams
): Promise<PageResponse<RemoteVodVideo>> {
  return apiGet<PageResponse<RemoteVodVideo>>('/admin/vod/remote-list', {
    params: compactParams({
      page: params.page,
      page_size: params.page_size,
      keyword: params.keyword,
      imported: params.imported === 'all' ? undefined : params.imported
    })
  })
}

export function importRemoteVod(
  payload: RemoteVodImportPayload
): Promise<VodMedia> {
  return apiPost<VodMedia>('/admin/vod/import', payload)
}

export function uploadVodMedia(
  file: File,
  options: {
    onProgress?: (percent: number) => void
    signal?: AbortSignal
  } = {}
): Promise<VodMedia> {
  const formData = new FormData()
  formData.append('file', file)
  return apiUpload<VodMedia>('/admin/vod/upload', formData, options)
}

export function syncVodMediaStatus(payload: {
  media_ids?: number[]
  file_ids?: string[]
}): Promise<VodMediaSyncResponse> {
  return apiPost<VodMediaSyncResponse>('/admin/vod/sync-status', payload)
}

export function updateVodMedia(
  mediaId: number,
  payload: VodMediaUpdatePayload
): Promise<VodMedia> {
  return apiPut<VodMedia>(`/admin/vod/${mediaId}`, payload)
}

export function deleteVodMedia(
  mediaId: number
): Promise<{ message: string }> {
  return apiDelete<{ message: string }>(`/admin/vod/${mediaId}`)
}
