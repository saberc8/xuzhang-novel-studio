import type { EditorialPatch, EditorialSummary } from './editorialTypes'

export function patchIneligible(patch: EditorialPatch, session: EditorialSummary): string | null {
  if (session.edition_id) return '本轮版本已保存'
  if (session.profile.allowed_changes === 'review_only') return '本轮只允许审阅'
  if (patch.status !== 'proposed') return '这处修改已处理'
  if (session.units.find(u => u.id === patch.anchor.unit_id)?.revision !== patch.anchor.unit_revision)
    return '该章已更新，请重新审读并生成修改建议'
  return null
}

export function patchSelectionProblem(patches: EditorialPatch[]): string | null {
  if (patches.length > 100) return '每批最多应用 100 处修改'
  const locations = new Set<string>()
  for (const p of patches) {
    const location = JSON.stringify([p.anchor.unit_id, p.anchor.paragraph_id])
    if (locations.has(location)) return '同一段落有多份修改，请只选择其中一份'
    locations.add(location)
  }
  return null
}
