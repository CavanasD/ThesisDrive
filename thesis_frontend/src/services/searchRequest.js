export const buildSearchRequest = (query, options = {}) => ({
  query: query.trim(),
  page_size: options.pageSize ?? 50,
  sort_by: options.sortBy ?? 'name',
  sort_order: options.sortOrder ?? 'asc',
})
