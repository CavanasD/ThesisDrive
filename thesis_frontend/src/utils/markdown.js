const escapeHtml = (value) => String(value)
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;')

const readDelimited = (source, start, marker) => {
  const end = source.indexOf(marker, start + marker.length)
  if (end === -1) return null
  return { content: source.slice(start + marker.length, end), end: end + marker.length }
}

export function renderMarkdownInline(source) {
  let html = ''
  let index = 0
  while (index < source.length) {
    if (source.startsWith('**', index)) {
      const match = readDelimited(source, index, '**')
      if (match) {
        html += `<strong>${renderMarkdownInline(match.content)}</strong>`
        index = match.end
        continue
      }
    }
    if (source[index] === '`') {
      const match = readDelimited(source, index, '`')
      if (match) {
        html += `<code>${escapeHtml(match.content)}</code>`
        index = match.end
        continue
      }
    }
    if (source[index] === '[') {
      const link = source.slice(index).match(/^\[([^\]]+)\]\(([^)\s]+)\)/)
      if (link) {
        const target = link[2]
        if (/^https?:\/\//i.test(target)) {
          html += `<a href="${escapeHtml(target)}" target="_blank" rel="noreferrer noopener">${escapeHtml(link[1])}</a>`
        } else {
          html += escapeHtml(link[0])
        }
        index += link[0].length
        continue
      }
    }
    html += escapeHtml(source[index])
    index += 1
  }
  return html
}

export function renderSafeMarkdown(markdown = '') {
  const lines = String(markdown).replaceAll('\r\n', '\n').split('\n')
  const output = []
  let paragraph = []
  let listType = ''
  let listItems = []
  let codeLines = []
  let inCode = false

  const flushParagraph = () => {
    if (!paragraph.length) return
    output.push(`<p>${paragraph.map(renderMarkdownInline).join('<br>')}</p>`)
    paragraph = []
  }
  const flushList = () => {
    if (!listItems.length) return
    output.push(`<${listType}>${listItems.map((item) => `<li>${renderMarkdownInline(item)}</li>`).join('')}</${listType}>`)
    listType = ''
    listItems = []
  }

  for (const line of lines) {
    if (line.trim().startsWith('```')) {
      flushParagraph()
      flushList()
      if (inCode) {
        output.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
        codeLines = []
      }
      inCode = !inCode
      continue
    }
    if (inCode) {
      codeLines.push(line)
      continue
    }
    if (!line.trim()) {
      flushParagraph()
      flushList()
      continue
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/)
    if (heading) {
      flushParagraph()
      flushList()
      const level = heading[1].length
      output.push(`<h${level}>${renderMarkdownInline(heading[2])}</h${level}>`)
      continue
    }
    const unordered = line.match(/^\s*[-*]\s+(.+)$/)
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/)
    if (unordered || ordered) {
      flushParagraph()
      const nextType = ordered ? 'ol' : 'ul'
      if (listType && listType !== nextType) flushList()
      listType = nextType
      listItems.push((ordered || unordered)[1])
      continue
    }
    const quote = line.match(/^>\s?(.*)$/)
    if (quote) {
      flushParagraph()
      flushList()
      output.push(`<blockquote>${renderMarkdownInline(quote[1])}</blockquote>`)
      continue
    }
    flushList()
    paragraph.push(line)
  }

  if (inCode && codeLines.length) {
    output.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
  }
  flushParagraph()
  flushList()
  return output.join('')
}
