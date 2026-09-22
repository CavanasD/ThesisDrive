import { describe, expect, it } from 'vitest'
import { buildSearchRequest } from './searchRequest'

describe('buildSearchRequest', () => {
  it('uses the protocol-26 page_size field', () => {
    expect(buildSearchRequest(' report ')).toEqual({
      query: 'report',
      page_size: 50,
      sort_by: 'name',
      sort_order: 'asc',
    })
    expect(buildSearchRequest('report')).not.toHaveProperty('limit')
  })
})
