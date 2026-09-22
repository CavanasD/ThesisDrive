const responseError = (response, fallback) =>
  new Error(`${response?.code || 500}: ${response?.message || fallback}`)

export const prepareDocumentUpload = async (request, folderId, fileName) => {
  const created = await request('create_document', {
    folder_id: folderId,
    title: fileName,
    inherit_parent: true,
  }, true, false)

  if (created?.code === 200) {
    return {
      documentId: created.data?.document_id,
      taskId: created.data?.task_data?.task_id,
      newRevision: false,
    }
  }

  const duplicateId = created?.code === 409 ? created.data?.duplicate_id : null
  if (!duplicateId) throw responseError(created, '上传任务创建失败')

  const revision = await request('upload_document', { document_id: duplicateId }, true, false)
  if (revision?.code === 409 && revision.data?.task_status === 'in_progress') {
    throw new Error('该文件已有上传正在进行，请等待完成后再试')
  }
  if (revision?.code !== 200) throw responseError(revision, '文件重传任务创建失败')

  return {
    documentId: duplicateId,
    taskId: revision.data?.task_data?.task_id,
    newRevision: true,
  }
}
