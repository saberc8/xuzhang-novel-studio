import { useEffect, useId, useState } from 'react'
import { ArrowLeft, ArrowRight, Search } from 'lucide-react'
import { api } from './api'
import type { EditorialAnchor, EditorialSummary, StoryEntity, StoryKind, StoryKnowledge, StoryPage, StoryRelation, StoryReview } from './editorialTypes'

const states: Record<string, string> = { candidate: '候选', confirmed: '已确认', disputed: '有争议', withdrawn: '已撤回' }
const perspectives: Record<string, string> = { event: '客观记录', belief: '人物认知', reader_knowledge: '读者已知' }
const knowledgeStates: Record<string, string> = { knows: '知道', believes: '相信', denies: '否认', unaware: '明确不知情' }
const kinds: [StoryKind, string][] = [['relations', '人物关系'], ['entities', '人物与实体'], ['knowledge', '谁知道什么'], ['reviews', '逐章核对']]

export function EditorialStory({ session, onEvidence }: { session: EditorialSummary; onEvidence: (a: EditorialAnchor) => void }) {
  const [kind, setKind] = useState<StoryKind>('relations')
  const [unit, setUnit] = useState('')
  const [entity, setEntity] = useState('')
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const c = session.story_coverage
  return <section className="editorial-story">
    <div className="adapt-card">
      <div className="adapt-section-heading"><h2>人物与故事账本</h2><span className="badge badge-neutral">已核对 {c.reviewed_units} / {c.total_units} 章</span></div>
      <p className="editorial-help">关系与知情状态随章节变化，每条记录都能回到原文。确认数只统计当前稿及当前依赖均已确认的记录。</p>
      <div className="story-counts">{([['entities', '人物与实体'], ['relations', '关系'], ['knowledge', '知情记录']] as const).map(([key, label]) => <span key={key}>{label} <strong>{c[key].confirmed} / {c[key].total}</strong>{c[key].stale > 0 && <small> · {c[key].stale} 条待更新</small>}</span>)}</div>
      {c.mode === 'manual' && <p className="editorial-help">此会话沿用跨章文字审读；人物账本覆盖单独记录。</p>}
      <div className="story-controls">
        <label>阅读至此章<select value={unit} onChange={e => setUnit(e.target.value)}><option value="">查看全稿已登记记录</option>{session.units.filter(u => u.selected).map(u => <option key={u.id} value={u.id}>{u.title}</option>)}</select></label>
        <form onSubmit={e => { e.preventDefault(); setQuery(draft.trim()); setEntity('') }}><label>查找姓名或别名<input maxLength={120} value={draft} onChange={e => setDraft(e.target.value)} placeholder="输入人物姓名" /></label><button className="button button-secondary"><Search size={15} />查找</button></form>
      </div>
      {(entity || query) && <button className="text-button" onClick={() => { setEntity(''); setQuery(''); setDraft('') }}>清除人物筛选</button>}
      {unit && <p className="editorial-help">显示在此章适用、且所引证据已出现的记录。章序与故事发生时间可能不同；倒叙和同章内的先后，需对照故事时间与原文。</p>}
    </div>
    <nav className="adapt-tabs" aria-label="故事账本内容">{kinds.map(([id, label]) => <button key={id} className={id === kind ? 'active' : ''} onClick={() => setKind(id)}>{label}</button>)}</nav>
    <StoryRecords key={`${session.revision}:${kind}:${unit}:${entity}:${query}`} session={session} kind={kind} unit={unit} entity={entity} query={query} onEvidence={onEvidence} onEntity={id => { setEntity(id); setQuery(''); setDraft('') }} />
  </section>
}

function StoryRecords({ session, kind, unit, entity, query, onEvidence, onEntity }: {
  session: EditorialSummary; kind: StoryKind; unit: string; entity: string; query: string
  onEvidence: (a: EditorialAnchor) => void; onEntity: (id: string) => void
}) {
  const [data, setData] = useState<StoryPage | null>(null)
  const [cursor, setCursor] = useState<string | null>(null)
  const [previous, setPrevious] = useState<(string | null)[]>([])
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    setData(null); setError('')
    const params = new URLSearchParams({ kind, limit: '6' })
    if (unit) params.set('at_unit_id', unit)
    if (entity) params.set('entity_id', entity)
    if (query) params.set('query', query)
    if (cursor) params.set('cursor', cursor)
    api<StoryPage>(`/editorial-reviews/${session.id}/story?${params}`, { signal: controller.signal }).then(setData)
      .catch(e => { if (e.name !== 'AbortError') setError(e.message) })
    return () => controller.abort()
  }, [session.id, kind, unit, entity, query, cursor])
  if (error) return <p role="alert" className="form-error">{error}</p>
  if (!data) return <p role="status">正在读取人物与故事记录…</p>
  const nodes = Object.fromEntries(data.nodes.map(n => [n.id, n]))
  const names = (id: string) => nodes[id]?.name || id
  const chapter = (id: string) => session.units.find(u => u.id === id)?.title || id
  return <div className="editorial-records">
    {!data.items.length && <div className="adapt-empty"><h3>{entity || query || unit ? '当前筛选下没有记录' : '尚未登记这类故事记录'}</h3><p>交给 Codex 阅读正文后，人物、关系与知情证据会显示在这里。未登记表示尚无记录。</p></div>}
    {kind === 'relations' && data.items.length > 0 && <RelationDiagram relations={data.items as StoryRelation[]} nodes={data.nodes} onEntity={onEntity} />}
    {data.items.map((item, index) => {
      const relation = item as StoryRelation, character = item as StoryEntity, knowledge = item as StoryKnowledge, review = item as StoryReview
      return <article className="adapt-card" key={'id' in item ? item.id : `${review.unit_id}:${index}`}>
        <div className="editorial-tags"><span className={`badge ${item.current ? 'badge-neutral' : 'badge-amber'}`}>{item.current ? ('status' in item ? states[item.status] : '当前稿已核对') : '待更新，不能作为当前结论'}</span>
          {'confirmed' in item && item.current && item.status === 'confirmed' && !item.confirmed && <span>关联记录尚未确认</span>}
          {kind === 'relations' && <span>{perspectives[relation.perspective]}{relation.observer_id ? ` · ${names(relation.observer_id)}` : ''}</span>}
        </div>
        {kind === 'entities' ? <><h3><button className="text-button" onClick={() => onEntity(character.id)}>{character.name}</button></h3><p>{character.description}</p>{character.aliases.length > 0 && <p className="editorial-help">有证据的别名：{character.aliases.map(a => a.name).join('、')}</p>}</>
          : kind === 'relations' ? <><h3>{names(relation.source_id)} → {names(relation.target_id)} · {relation.polarity === 'denied' ? '否认：' : ''}{relation.label}</h3><p>{relation.explanation}</p></>
          : kind === 'knowledge' ? <><h3>{names(knowledge.holder_id)} · {knowledgeStates[knowledge.state]}</h3><p>{data.facts.find(f => f.id === knowledge.fact_id)?.statement || knowledge.fact_id}</p><p className="editorial-help">获取或判断依据：{knowledge.acquisition}</p></>
          : <><h3>{chapter(review.unit_id)}</h3><p>{review.summary}</p><p className="editorial-help">核对 {review.entity_ids.length} 个实体、{review.relation_ids.length} 条关系、{review.knowledge_ids.length} 条知情记录</p></>}
        {(kind === 'relations' || kind === 'knowledge') && <p className="editorial-help">叙事适用：{chapter(relation.from_unit_id)} → {relation.through_unit_id ? chapter(relation.through_unit_id) : '后续章节'}{relation.story_time ? ` · 故事时间：${relation.story_time}` : ''}</p>}
        <div className="editorial-evidence">{item.evidence.map((a, i) => <blockquote key={i}><p>{a.quote}</p><button className="text-button" onClick={() => onEvidence(a)}>查看 {chapter(a.unit_id)} · {a.paragraph_id} 的原文<ArrowRight size={13} /></button></blockquote>)}</div>
      </article>
    })}
    <div className="editorial-pagination"><span>当前筛选共 {data.total} 条；图只展示当前页</span><button className="button button-secondary" disabled={!previous.length} onClick={() => { setCursor(previous[previous.length - 1]); setPrevious(previous.slice(0, -1)) }}><ArrowLeft size={14} />上一页</button><button className="button button-secondary" disabled={!data.next_cursor} onClick={() => { setPrevious([...previous, cursor]); setCursor(data.next_cursor) }}>下一页<ArrowRight size={14} /></button></div>
  </div>
}

function RelationDiagram({ relations, nodes, onEntity }: { relations: StoryRelation[]; nodes: StoryEntity[]; onEntity: (id: string) => void }) {
  const marker = useId().replace(/:/g, '')
  const ids = new Set(relations.flatMap(r => [r.source_id, r.target_id]))
  const displayed = nodes.filter(n => ids.has(n.id))
  const positions = Object.fromEntries(displayed.map((n, i) => {
    const angle = -Math.PI / 2 + i * 2 * Math.PI / displayed.length
    return [n.id, { x: 410 + 290 * Math.cos(angle), y: 280 + 200 * Math.sin(angle) }]
  }))
  return <div className="adapt-card story-diagram"><p className="editorial-help">当前页关系图 · 箭头表示记录方向；虚线表示候选、争议、过期或撤回。点击人物聚焦，详细证据见下方。</p>
    <svg viewBox="0 0 820 560" role="group" aria-label="当前页人物关系图">
      <defs><marker id={marker} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" /></marker></defs>
      {relations.map((r, i) => {
        const a = positions[r.source_id], b = positions[r.target_id]
        if (!a || !b) return null
        const dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy) || 1
        const bend = 20 + i * 11, mx = (a.x + b.x) / 2 - dy / length * bend, my = (a.y + b.y) / 2 + dx / length * bend
        const self = r.source_id === r.target_id
        const d = self ? `M ${a.x - 20} ${a.y - 24} C ${a.x - 130} ${a.y - 115}, ${a.x + 130} ${a.y - 115}, ${a.x + 20} ${a.y - 24}` : `M ${a.x} ${a.y} Q ${mx} ${my}, ${b.x - dx / length * 65} ${b.y - dy / length * 30}`
        const label = `${r.polarity === 'denied' ? '否认·' : ''}${r.label}${r.perspective === 'belief' ? '（认知）' : r.perspective === 'reader_knowledge' ? '（读者）' : ''}`
        return <g key={r.id} className={r.confirmed ? 'story-edge' : 'story-edge unconfirmed'}><path d={d} markerEnd={`url(#${marker})`} /><text x={self ? a.x : (a.x + 2 * mx + b.x) / 4} y={self ? a.y - 85 : (a.y + 2 * my + b.y) / 4 - 8} textAnchor="middle">{label.length > 16 ? label.slice(0, 15) + '…' : label}</text><title>{label} · {r.explanation}</title></g>
      })}
      {displayed.map(n => <g key={n.id} className={`story-node ${n.confirmed ? '' : 'unconfirmed'}`} transform={`translate(${positions[n.id].x},${positions[n.id].y})`} role="button" tabIndex={0} aria-label={`聚焦 ${n.name}`} onClick={() => onEntity(n.id)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onEntity(n.id) } }}><rect x="-66" y="-25" width="132" height="50" rx="12" /><text textAnchor="middle" y="5">{n.name.length > 8 ? n.name.slice(0, 7) + '…' : n.name}</text><title>{n.name} · {n.description}</title></g>)}
    </svg>
  </div>
}
