import { describe, expect, it } from 'vitest'
import { buildRevisionListRequest, childDirectories } from './documentOperations'

describe('document operations protocol', () => {
  it('uses page_size when listing revision history', () => {
    const request = buildRevisionListRequest('doc-1')
    expect(request).toEqual({ document_id: 'doc-1', page_size: 50 })
    expect(request).not.toHaveProperty('limit')
  })

  it('reads move destinations from protocol-26 items', () => {
    const folder = { type: 'directory', id: 'folder-1', name: 'Pictures' }
    const document = { type: 'document', id: 'doc-1', title: 'photo.jpg' }
    expect(childDirectories({ items: [folder, document] })).toEqual([folder])
  })
})
