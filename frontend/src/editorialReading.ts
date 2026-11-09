import type { EditorialAnchor, EditorialChunk } from './editorialTypes'

// Coordinates from Python/MCP count Unicode code points, not JavaScript UTF-16.
// A quote can span several chunks; validate and highlight only this fragment.
export function highlightEvidence(chunk: EditorialChunk, paragraph: EditorialChunk['paragraphs'][number], anchor: EditorialAnchor | null) {
  if (!anchor || chunk.unit_id !== anchor.unit_id || paragraph.id !== anchor.paragraph_id
    || paragraph.paragraph_sha256 !== anchor.paragraph_sha256) return null
  const start = Math.max(anchor.start, paragraph.start)
  const end = Math.min(anchor.end, paragraph.end)
  if (start >= end) return null
  const points = Array.from(paragraph.text)
  const quote = points.slice(start - paragraph.start, end - paragraph.start).join('')
  if (quote !== Array.from(anchor.quote).slice(start - anchor.start, end - anchor.start).join('')) return null
  return { before: points.slice(0, start - paragraph.start).join(''), quote, after: points.slice(end - paragraph.start).join('') }
}
