const ensureSuccess = (response, action) => {
  if (!response || Number(response.code) >= 400) {
    throw new Error(`${response?.code || 500}: ${response?.message || `${action} 失败`}`)
  }
  return response.data || {}
}

export function buildShareUrl(token, href = globalThis.location?.href) {
  const normalizedToken = String(token || '').trim()
  if (!normalizedToken) throw new Error('分享令牌为空')
  if (!href) throw new Error('当前环境无法生成分享链接')

  const url = new URL(href)
  url.search = ''
  url.hash = ''
  url.searchParams.set('share', normalizedToken)
  return url.toString()
}

export class ShareClient {
  constructor(options = {}) {
    if (!options.controlClient) throw new Error('ShareClient 需要 controlClient')
    this.controlClient = options.controlClient
  }

  async request(action, data, auth = null) {
    const response = await this.controlClient.request(action, data, auth)
    return ensureSuccess(response, action)
  }

  async createShareLink(documentId, options = {}, auth = null) {
    const data = await this.request('create_share_link', {
      document_id: documentId,
      password: options.password || null,
      expires_at: options.expiresAt ?? null,
      max_downloads: options.maxDownloads ?? null,
    }, auth)
    if (!data.share?.token) throw new Error('create_share_link 未返回 share.token')
    return data.share
  }

  async listShareLinks(auth = null) {
    const data = await this.request('list_share_links', {}, auth)
    if (!Array.isArray(data.shares)) throw new Error('list_share_links 未返回 shares')
    return data.shares
  }

  async revokeShareLink(token, auth = null) {
    const data = await this.request('revoke_share_link', { token }, auth)
    if (!data.token) throw new Error('revoke_share_link 未返回 token')
    return data.token
  }

  async prepareShareDownload(token, password = null) {
    const data = await this.request('prepare_share_download', {
      token,
      password: password || null,
    })
    if (!data.task_id || !data.download_url || !data.ticket) {
      throw new Error('prepare_share_download 返回的传输会话不完整')
    }
    return data
  }
}
