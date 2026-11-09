import { useEffect, useState } from 'react'
import { ArrowLeft, ArrowRight, FileSearch } from 'lucide-react'
import { api } from './api'
import { dimensionName, qualityDimensions } from './editorialTypes'
import { patchIneligible, patchSelectionProblem } from './editorialPatches'
import type { EditorialAnchor, EditorialFact, EditorialFinding, EditorialPageData, EditorialPatch, EditorialReview, EditorialSummary } from './editorialTypes'

const findingNames: Record<string, string> = { open: '待处理', proposed: '已有修改建议', needs_recheck: '待重新核对', resolved: '已解决', dismissed: '已说明保留原因', deferred: '留待后续' }
const categoryNames: Record<string, string> = { timeline: '时间', reference: '指代', relationship: '人物关系', knowledge: '知情边界', money: '财务', causality: '因果', prose: '行文', dialogue: '对白', pov: '视角', structure: '结构', length: '篇幅', format: '格式' }
const severityNames: Record<string, string> = { error: '需修正', warning: '需核对', suggestion: '建议' }
export type RecordKind = 'findings' | 'patches' | 'facts' | 'quality'
type RecordItem = EditorialFinding | EditorialPatch | EditorialFact | EditorialReview

export function EvidenceList({ evidence, onEvidence }: { evidence: EditorialAnchor[]; onEvidence: (a: EditorialAnchor) => void }) {
  return <div className="editorial-evidence">{evidence.map((a, i) => <blockquote key={i}><p>{a.quote}</p><button className="text-button" onClick={() => onEvidence(a)}>查看 {a.unit_id} · {a.paragraph_id} 的上下文<ArrowRight size={13} /></button></blockquote>)}</div>
}

export function EditorialRecords({ session, kind, onEvidence, onApply, busy }: { session: EditorialSummary; kind: RecordKind; onEvidence: (a: EditorialAnchor) => void; onApply: (ids: string[]) => void; busy: boolean }) {
  const [data, setData] = useState<EditorialPageData<RecordItem> | null>(null)
  const [paging, setPaging] = useState<{ revision: number; cursor: string | null; previous: (string | null)[] }>({ revision: session.revision, cursor: null, previous: [] })
  const [selection, setSelection] = useState<{ revision: number; patches: EditorialPatch[] }>({ revision: session.revision, patches: [] })
  const [filters, setFilters] = useState({ unit_id: '', category: '', dimension: '', status: '', query: '' })
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const current = paging.revision === session.revision ? paging : { revision: session.revision, cursor: null, previous: [] }
  const selected = selection.revision === session.revision ? selection.patches : []
  const visible = data?.revision === session.revision ? data : null
  const selectionProblem = patchSelectionProblem(selected)
  function filter(key: keyof typeof filters, value: string) {
    setFilters(f => ({ ...f, [key]: value })); setPaging({ revision: session.revision, cursor: null, previous: [] })
  }
  function select(patch: EditorialPatch, checked: boolean) {
    setSelection({ revision: session.revision, patches: checked ? [...selected, patch] : selected.filter(p => p.id !== patch.id) })
  }
  useEffect(() => {
    const controller = new AbortController()
    setData(null); setError('')
    const params = new URLSearchParams({ kind: kind === 'quality' ? 'reviews' : kind, limit: '20' })
    if (current.cursor) params.set('cursor', current.cursor)
    if (kind === 'findings') for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value)
    api<EditorialPageData<RecordItem>>(`/editorial-reviews/${session.id}/records?${params}`, { signal: controller.signal })
      .then(setData).catch(e => { if (e.name !== 'AbortError') setError(e.message) })
    return () => controller.abort()
  }, [session.id, session.revision, kind, current.cursor, filters])
  return <div className="editorial-records">
    {kind === 'findings' && <form className="editorial-filters" onSubmit={e => { e.preventDefault(); filter('query', search.trim()) }}>
      <label>章节<select value={filters.unit_id} onChange={e => filter('unit_id', e.target.value)}><option value="">全部章节</option>{session.units.filter(u => u.selected).map(u => <option key={u.id} value={u.id}>{u.title}</option>)}</select></label>
      <label>类别<select value={filters.category} onChange={e => filter('category', e.target.value)}><option value="">全部类别</option>{Object.entries(categoryNames).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
      <label>专项<select value={filters.dimension} onChange={e => filter('dimension', e.target.value)}><option value="">全部专项</option>{qualityDimensions.map(d => <option key={d.id} value={d.id}>{d.label}</option>)}</select></label>
      <label>状态<select value={filters.status} onChange={e => filter('status', e.target.value)}><option value="">全部状态</option>{Object.entries(findingNames).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
      <label>搜索问题<div className="editorial-search"><input type="search" maxLength={120} value={search} onChange={e => setSearch(e.target.value)} placeholder="问题描述中的关键词" /><button className="button button-secondary" type="submit">搜索</button></div></label>
      {Object.values(filters).some(Boolean) && <button type="button" className="text-button" onClick={() => { setFilters({ unit_id: '', category: '', dimension: '', status: '', query: '' }); setSearch(''); setPaging({ revision: session.revision, cursor: null, previous: [] }) }}>清除筛选</button>}
    </form>}
    {kind === 'patches' && !session.edition_id && <div className="editorial-batch adapt-card">
      <p>同一章的修改建议请一起选择、批量应用；应用后会更新章节，未应用的旧建议需要重新审读。</p>
      <div className="editorial-actions"><strong>已选 {selected.length} 处</strong><button className="button button-secondary" disabled={!selected.length || busy} onClick={() => setSelection({ revision: session.revision, patches: [] })}>清空选择</button><button className="button button-primary" disabled={busy || !selected.length || !!selectionProblem} onClick={() => onApply(selected.map(p => p.id))}>批量应用所选修改</button></div>
      {selectionProblem && <p role="alert" className="form-error">{selectionProblem}</p>}
    </div>}
    {kind === 'quality' && <p className="editorial-help">仅当前有效报告计入覆盖统计；问题处理进度见“问题与证据”。</p>}
    {error && <p role="alert" className="form-error">{error}</p>}
    {!visible && !error && <p role="status">正在读取记录…</p>}
    {visible && <>
      {!visible.items.length && <div className="adapt-empty"><FileSearch size={28} /><h3>{kind === 'findings' ? '当前条件下没有问题记录' : kind === 'patches' ? '尚未提出修改' : kind === 'quality' ? '尚未提交专项审读报告' : '尚未登记事实'}</h3><p>检查或审读完成后，对应的证据与判断会显示在这里。</p></div>}
      {visible.items.map(item => {
        if (kind === 'findings') {
          const f = item as EditorialFinding
          return <article className="adapt-card editorial-finding" key={f.id}><div className="editorial-tags"><span className={`badge ${f.severity === 'error' ? 'badge-amber' : 'badge-neutral'}`}>{severityNames[f.severity]}</span><span>{f.dimension ? dimensionName(f.dimension) : categoryNames[f.category]}</span><span>{findingNames[f.status]} · {f.origin === 'rule' ? '程序候选' : '审读判断'}</span></div><h3>{f.message}</h3><EvidenceList evidence={f.evidence} onEvidence={onEvidence} />{f.disposition_reason && <p className="editorial-help">处理依据：{f.disposition_reason}</p>}</article>
        }
        if (kind === 'patches') {
          const p = item as EditorialPatch, unavailable = patchIneligible(p, session), checked = selected.some(s => s.id === p.id)
          return <article className="adapt-card" key={p.id}>
            <div className="adapt-section-heading"><h3>{p.anchor.unit_id} · {p.anchor.paragraph_id}</h3><span className="badge badge-neutral">{p.status === 'proposed' ? (unavailable ? '需要重新确认' : '待应用') : p.status === 'discarded' ? '已放弃' : p.verified_manuscript_revision === session.manuscript_revision ? '已应用并复核' : '已应用，待复核'}</span></div>
            <div className="editorial-diff"><div><small>修改前</small><p>{p.before}</p></div><div><small>修改后</small><p>{p.after}</p></div></div><p className="editorial-help">修改理由：{p.reason}</p>
            {!!p.goals?.length && <ul className="editorial-goals">{p.goals.map(g => <li key={g.dimension}><strong>{dimensionName(g.dimension)}：</strong>{g.expected_improvement}</li>)}</ul>}
            {p.preservation && <p className="editorial-help">保留项检查：{p.preservation}</p>}
            {p.quality_assessment && <div className="editorial-location"><strong>复核记录 · {{ improved: '已有改善', retained: '达到约定目标', not_improved: '尚未改善' }[p.quality_assessment.outcome]} · 保留项{p.quality_assessment.preservation === 'passed' ? '通过' : '未通过'}</strong><p>{p.quality_assessment.comparison}</p><p>{p.quality_assessment.preservation_reason}</p>{p.verified_manuscript_revision !== session.manuscript_revision && <p>这条记录尚未完成当前稿验收，请重新核对。</p>}</div>}
            {p.status === 'proposed' && !session.edition_id && <div className="editorial-actions"><label className="editorial-select"><input type="checkbox" aria-label={`选择修改 ${p.anchor.unit_id} ${p.anchor.paragraph_id}`} checked={checked} disabled={busy || !!unavailable || (!checked && selected.length >= 100)} onChange={e => select(p, e.target.checked)} />加入批量应用</label><button className="button button-secondary" disabled={busy || !!unavailable} onClick={() => onApply([p.id])}>单独应用</button>{unavailable && <span>{unavailable}</span>}</div>}
          </article>
        }
        if (kind === 'quality') {
          const r = item as EditorialReview
          return <article className="adapt-card" key={r.id}><div className="editorial-tags"><strong>{r.report.kind === 'audit' ? '跨章专项结论' : r.report.kind === 'findings' ? '问题登记 · 不计审读覆盖' : `分块审读 · ${r.report.chunk_id}`}</strong><span className="badge badge-neutral">{r.current ? '当前有效' : '历史记录'}</span><span>正文版本 {r.manuscript_revision}</span></div><p className="adapt-prose">{r.report.summary}</p>{r.report.quality_assessments?.length ? r.report.quality_assessments.map(a => <details key={a.dimension} className="editorial-assessment"><summary>{dimensionName(a.dimension)} · {{ passed: '本次审读未发现问题', issues: '发现问题', not_applicable: '本处不适用' }[a.outcome]}</summary><p>{a.rationale}</p><EvidenceList evidence={a.evidence} onEvidence={onEvidence} />{a.outcome === 'issues' && <p className="editorial-help">已关联 {a.finding_indexes.length + a.finding_ids.length} 个问题，处理进度见“问题与证据”。</p>}</details>) : <p className="editorial-help">{r.report.kind === 'findings' ? '本条仅登记具体问题，不授予分块或跨章审读覆盖。' : '这条历史通用报告未包含逐维度专项结论。'}</p>}</article>
        }
        const f = item as EditorialFact
        return <article className="adapt-card" key={f.id}><div className="editorial-tags"><span>{{ candidate: '候选', confirmed: '已确认', disputed: '有争议' }[f.status]}</span><span>{{ event: '实际事件', belief: '人物认知', reader_knowledge: '读者已知' }[f.perspective]}</span></div><h3>{f.statement}</h3><p>{[f.date, f.value, f.currency, f.account].filter(Boolean).join(' · ')}</p><EvidenceList evidence={f.evidence} onEvidence={onEvidence} /></article>
      })}
      <div className="editorial-pagination"><span>第 {Math.floor(visible.offset / 20) + 1} / {Math.max(1, Math.ceil(visible.total / 20))} 页 · 共 {visible.total} 项</span><button className="button button-secondary" disabled={!current.previous.length} onClick={() => setPaging({ ...current, cursor: current.previous[current.previous.length - 1], previous: current.previous.slice(0, -1) })}><ArrowLeft size={14} />上一页</button><button className="button button-secondary" disabled={!visible.next_cursor} onClick={() => setPaging({ ...current, cursor: visible.next_cursor, previous: [...current.previous, current.cursor] })}>下一页<ArrowRight size={14} /></button></div>
    </>}
  </div>
}
