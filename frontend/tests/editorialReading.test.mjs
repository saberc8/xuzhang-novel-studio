import assert from 'node:assert/strict'
import { test } from 'node:test'
import { highlightEvidence } from '../src/editorialReading.ts'

const paragraph = { id: 'p1', text: '门前𠮷先生交出铜钥匙。', start: 0, end: 11, paragraph_sha256: 'digest' }
const chunk = { unit_id: 'u1', paragraphs: [paragraph] }
const anchor = { unit_id: 'u1', paragraph_id: 'p1', paragraph_sha256: 'digest', start: 2, end: 5, quote: '𠮷先生' }

test('rare characters use code point offsets', () => {
  assert.deepEqual(highlightEvidence(chunk, paragraph, anchor), { before: '门前', quote: '𠮷先生', after: '交出铜钥匙。' })
})

test('evidence spanning chunks highlights each overlapping fragment', () => {
  assert.deepEqual(highlightEvidence(chunk, { ...paragraph, text: '门前𠮷先', end: 4 }, anchor), { before: '门前', quote: '𠮷先', after: '' })
  assert.deepEqual(highlightEvidence(chunk, { ...paragraph, text: '生交出铜钥匙。', start: 4 }, anchor), { before: '', quote: '生', after: '交出铜钥匙。' })
})

test('no highlight outside the quote or in a different chapter with the same paragraph ID', () => {
  assert.equal(highlightEvidence(chunk, { ...paragraph, text: '铜钥匙。', start: 7 }, anchor), null)
  assert.equal(highlightEvidence({ ...chunk, unit_id: 'u2' }, paragraph, anchor), null)
})

test('changed paragraph hash or mismatched quote never highlights old coordinates', () => {
  assert.equal(highlightEvidence(chunk, { ...paragraph, paragraph_sha256: 'new-digest' }, anchor), null)
  assert.equal(highlightEvidence(chunk, paragraph, { ...anchor, quote: '另一个人' }), null)
})

test('empty focus and neighboring paragraphs are safe', () => {
  assert.equal(highlightEvidence(chunk, paragraph, null), null)
  assert.equal(highlightEvidence(chunk, { ...paragraph, id: 'p2' }, anchor), null)
})
