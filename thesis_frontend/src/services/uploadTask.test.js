import { describe, expect, it, vi } from 'vitest'
import { prepareDocumentUpload } from './uploadTask'

describe('prepareDocumentUpload', () => {
  it('creates a new document when the name is unused', async () => {
    const request = vi.fn(async () => ({
      code: 200,
      data: { document_id: 'doc-1', task_data: { task_id: 'task-1' } },
    }))
    await expect(prepareDocumentUpload(request, 'folder-1', 'photo.jpg')).resolves.toEqual({
      documentId: 'doc-1', taskId: 'task-1', newRevision: false,
    })
  })

  it('creates a new revision when the filename already exists', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ code: 409, data: { duplicate_id: 'doc-1' } })
      .mockResolvedValueOnce({ code: 200, data: { task_data: { task_id: 'task-2' } } })
    await expect(prepareDocumentUpload(request, 'folder-1', 'photo.jpg')).resolves.toEqual({
      documentId: 'doc-1', taskId: 'task-2', newRevision: true,
    })
    expect(request.mock.calls[1][0]).toBe('upload_document')
  })

  it('rejects a second upload while the existing one is active', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ code: 409, data: { duplicate_id: 'doc-1' } })
      .mockResolvedValueOnce({ code: 409, data: { task_status: 'in_progress' } })
    await expect(prepareDocumentUpload(request, 'folder-1', 'photo.jpg'))
      .rejects.toThrow('已有上传正在进行')
  })
})
