export const splitListingItems = (data = {}) => {
  if (Array.isArray(data.items)) {
    return {
      folders: data.items.filter((item) => item?.type === 'directory'),
      documents: data.items.filter((item) => item?.type === 'document'),
    }
  }

  return {
    folders: Array.isArray(data.folders) ? data.folders : [],
    documents: Array.isArray(data.documents) ? data.documents : [],
  }
}
