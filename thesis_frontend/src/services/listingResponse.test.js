import { describe, expect, it } from 'vitest'
import { splitListingItems } from './listingResponse'

describe('splitListingItems', () => {
  it('splits protocol-26 items into folders and documents', () => {
    const folder = { type: 'directory', id: 'folder-1', name: 'Pictures' }
    const document = { type: 'document', id: 'doc-1', title: 'photo.jpg' }

    expect(splitListingItems({ items: [folder, document] })).toEqual({
      folders: [folder],
      documents: [document],
    })
  })

  it('keeps compatibility with the legacy response fields', () => {
    const folders = [{ id: 'folder-1' }]
    const documents = [{ id: 'doc-1' }]
    expect(splitListingItems({ folders, documents })).toEqual({ folders, documents })
  })
})
