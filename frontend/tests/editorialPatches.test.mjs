import assert from 'node:assert/strict'
import { test } from 'node:test'
import { patchIneligible, patchSelectionProblem } from '../src/editorialPatches.ts'

const session = { edition_id: null, profile: { allowed_changes: 'copyedit' }, units: [{ id: 'u1', revision: 2 }, { id: 'u2', revision: 1 }] }
const patch = { id: 'a', status: 'proposed', anchor: { unit_id: 'u1', paragraph_id: 'p1', unit_revision: 2 } }

test('only current proposed patches can be applied', () => {
  assert.equal(patchIneligible(patch, session), null)
  assert.match(patchIneligible({ ...patch, anchor: { ...patch.anchor, unit_revision: 1 } }, session), /重新审读/)
  assert.match(patchIneligible({ ...patch, anchor: { ...patch.anchor, unit_id: 'missing' } }, session), /重新审读/)
  assert.match(patchIneligible({ ...patch, status: 'applied' }, session), /已处理/)
})

test('read-only and frozen sessions cannot apply proposals', () => {
  assert.match(patchIneligible(patch, { ...session, edition_id: 'saved' }), /已保存/)
  assert.match(patchIneligible(patch, { ...session, profile: { allowed_changes: 'review_only' } }), /只允许审阅/)
})

test('same-chapter different-paragraph batches are valid; alternatives for one paragraph conflict', () => {
  const next = { ...patch, id: 'b', anchor: { ...patch.anchor, paragraph_id: 'p2' } }
  assert.equal(patchSelectionProblem([patch, next]), null)
  assert.match(patchSelectionProblem([patch, { ...patch, id: 'b' }]), /同一段落/)
  assert.equal(patchSelectionProblem([patch, { ...patch, id: 'b', anchor: { ...patch.anchor, unit_id: 'u2' } }]), null)
})

test('batch limit is enforced before sending a mutation', () => {
  const patches = Array.from({ length: 101 }, (_, i) => ({ ...patch, anchor: { ...patch.anchor, paragraph_id: `p${i}` } }))
  assert.equal(patchSelectionProblem(patches.slice(0, 100)), null)
  assert.match(patchSelectionProblem(patches), /最多应用 100/)
})
