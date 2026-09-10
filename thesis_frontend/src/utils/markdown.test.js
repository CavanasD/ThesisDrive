import { describe, expect, it } from 'vitest'
import { renderSafeMarkdown } from './markdown'

describe('renderSafeMarkdown', () => {
  it('renders the supported report syntax', () => {
    const html = renderSafeMarkdown('## 复现步骤\n1. 打开 **文件**\n2. 请求 `GET /api`')
    expect(html).toContain('<h2>复现步骤</h2>')
    expect(html).toContain('<ol>')
    expect(html).toContain('<strong>文件</strong>')
    expect(html).toContain('<code>GET /api</code>')
  })

  it('escapes raw html and refuses executable links', () => {
    const html = renderSafeMarkdown('<script>alert(1)</script> [x](javascript:alert(1))')
    expect(html).toContain('&lt;script&gt;')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('href="javascript:')
  })

  it('adds safe attributes to external links', () => {
    const html = renderSafeMarkdown('[证据](https://example.test/evidence)')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noreferrer noopener"')
  })
})
