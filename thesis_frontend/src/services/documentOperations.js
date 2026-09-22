import { splitListingItems } from './listingResponse'

export const buildRevisionListRequest = (documentId, pageSize = 50) => ({
  document_id: documentId,
  page_size: pageSize,
})

export const childDirectories = (responseData) =>
  splitListingItems(responseData).folders
