import { describe, expect, it, vi } from 'vitest'
import { buildShareUrl, ShareClient } from './shareClient'

const makeControlClient = () => ({
  request: vi.fn(async (action) => {
    if (action === 'create_share_link') {
      return { code: 200, data: { share: { token: 'share-token', document_id: 'doc-1' } } }
    }
    if (action === 'list_share_links') {
      return { code: 200, data: { shares: [{ token: 'share-token', document_id: 'doc-1' }] } }
    }
    if (action === 'revoke_share_link') {
      return { code: 200, data: { token: 'share-token' } }
    }
    return {
      code: 200,
      data: {
        task_id: 'task-1',
        download_url: '/api/v1/transfers/task-1/content',
        ticket: 'short-lived-ticket',
        size: 42,
      },
    }
  }),
})

describe('ShareClient production contracts', () => {
  it('uses the exact authenticated create/list/revoke actions and fields', async () => {
    const controlClient = makeControlClient()
    const client = new ShareClient({ controlClient })
    const auth = { username: 'alice', token: 'session-token' }

    await client.createShareLink('doc-1', {
      password: 'secret',
      expiresAt: 2_000_000_000,
      maxDownloads: 3,
    }, auth)
    await client.listShareLinks(auth)
    await client.revokeShareLink('share-token', auth)

    expect(controlClient.request.mock.calls).toEqual([
      ['create_share_link', {
        document_id: 'doc-1',
        password: 'secret',
        expires_at: 2_000_000_000,
        max_downloads: 3,
      }, auth],
      ['list_share_links', {}, auth],
      ['revoke_share_link', { token: 'share-token' }, auth],
    ])
  })

  it('prepares an anonymous download without forwarding account auth', async () => {
    const controlClient = makeControlClient()
    const client = new ShareClient({ controlClient })

    const prepared = await client.prepareShareDownload('share-token', 'secret')

    expect(prepared).toMatchObject({ task_id: 'task-1', ticket: 'short-lived-ticket' })
    expect(controlClient.request).toHaveBeenCalledWith(
      'prepare_share_download',
      { token: 'share-token', password: 'secret' },
      null,
    )
  })

  it('builds a clean share URL without retaining unrelated query data', () => {
    expect(buildShareUrl('a b', 'https://drive.test/files?debug=true#old'))
      .toBe('https://drive.test/files?share=a+b')
  })
})
