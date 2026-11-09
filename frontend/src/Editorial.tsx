import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, Check, Copy, Download, GitBranch, Loader2, Plus, RefreshCw } from 'lucide-react'
import { api, post } from './api'
import { CopyBlock, Modal } from './components'
import { RewriteEditor } from './DeepRewrite'
import { EditorialStory } from './EditorialStory'
import { EditorialReader } from './EditorialReader'
import { EditorialRecords } from './EditorialRecords'
import { qualityDimensions } from './editorialTypes'
import type { Adaptation } from './types'
import type { EditorialAnchor, EditorialDepth, EditorialSource, EditorialSummary, QualityDimension } from './editorialTypes'

const openReview = (id: string) => { window.location.hash = `/editorial/${id}` }
const depthNames = { scan: '程序扫描', focused: '重点审读', full: '全文审读' }
const statusNames: Record<string, string> = { created: '等待检查', reviewing: '正在审读', correcting: '待修改', rechecking: '待复核', ready: '可保存', completed: '本轮已保存' }
const outcomeNames: Record<string, string> = { scan_only: '程序扫描记录', focused_review: '重点审读记录', full_review: '全文审读记录', needs_structural_revision: '保留结构问题' }

// Keep one retry key for an identical intent, including after an ambiguous network error.
function useRequests() {
  const keys = useRef(new Map<string, string>())
  return async <T,>(path: string, body: object): Promise<T> => {
    const intent = JSON.stringify([path, body])
    let key = keys.current.get(intent)
    if (!key) { key = crypto.randomUUID(); keys.current.set(intent, key) }
    return post<T>(path, { ...body, request_id: key })
  }
}

export function EditorialProjects({ project }: { project: Adaptation }) {
  const [reviews, setReviews] = useState<EditorialSummary[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    let pending = false
    setLoading(true); setReviews([]); setError('')
    async function refresh() {
      if (pending) return
      pending = true
      try {
        const next = await api<EditorialSummary[]>(`/adaptations/${project.id}/editorial-reviews`, { signal: controller.signal })
        if (!controller.signal.aborted) { setReviews(next); setError('') }
      } catch (e) { if (!controller.signal.aborted) setError((e as Error).message) }
      finally { pending = false; if (!controller.signal.aborted) setLoading(false) }
    }
    void refresh()
    const timer = setInterval(refresh, 4000)
    return () => { controller.abort(); clearInterval(timer) }
  }, [project.id])
  return <section className="adapt-card">
    <div className="adapt-section-heading"><div><h2>文字质检</h2></div><button className="button button-primary" disabled={loading || !!error} onClick={() => setCreating(true)}><Plus size={16} />建立审稿任务</button></div>
    <p className="adapt-prose">基于冻结稿审读和精修，修改另存为新版本。</p>
    {error && <p role="alert" className="form-error">{error}</p>}
    {loading && <p role="status" className="framework-foot"><Loader2 size={15} className="spin" />正在读取审稿任务…</p>}
    <div className="editorial-session-list">{reviews.map(r => <button key={r.id} onClick={() => openReview(r.id)}><div><strong>{r.name}</strong><small>{depthNames[r.profile.depth]} · {r.coverage.selected_units} 章 · 已读 {r.coverage.reviewed_paragraphs} / {r.coverage.total_paragraphs} 段</small></div><span className="badge badge-neutral">{statusNames[r.status]}</span><ArrowRight size={16} /></button>)}</div>
    {!loading && !reviews.length && !error && <p className="framework-foot">暂无审稿任务。</p>}
    {creating && <CreateEditorial project={project} reviews={reviews} onClose={() => setCreating(false)} />}
  </section>
}

function CreateEditorial({ project, reviews, onClose, initialEdition = '' }: { project: Adaptation; reviews: EditorialSummary[]; onClose: () => void; initialEdition?: string }) {
  const [name, setName] = useState(`${project.name.slice(0, 105)} · 文字精修`)
  const [depth, setDepth] = useState<EditorialDepth>('focused')
  const [permission, setPermission] = useState<'copyedit' | 'review_only'>('copyedit')
  const [edition, setEdition] = useState(initialEdition)
  const [source, setSource] = useState<EditorialSource | null>(null)
  const [scope, setScope] = useState<string[]>([])
  const [voice, setVoice] = useState('尊重人物声音、原有叙事视角和表达习惯；仅修改有具体依据的问题。')
  const [genre, setGenre] = useState('小说')
  const [preserve, setPreserve] = useState('保留情节、人物动机、事实与信息揭示顺序')
  const [dimensions, setDimensions] = useState<QualityDimension[]>(qualityDimensions.map(d => d.id))
  const [continuity, setContinuity] = useState<'manual' | 'tracked'>('tracked')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const send = useRequests()
  useEffect(() => {
    const controller = new AbortController()
    setSource(null); setError('')
    api<EditorialSource>(`/adaptations/${project.id}/editorial-source${edition ? `?edition_id=${edition}` : ''}`, { signal: controller.signal })
      .then(s => { setSource(s); setScope(s.units.map(u => u.id)) }).catch(e => { if (e.name !== 'AbortError') setError(e.message) })
    return () => controller.abort()
  }, [project.id, edition])
  return <Modal title="新建审稿任务" onClose={onClose} wide>
    <form className="editor-form" onSubmit={async e => {
      e.preventDefault(); if (!source || !scope.length || busy || (depth !== 'scan' && !dimensions.length)) return
      setBusy(true); setError('')
      try {
        const next = await send<EditorialSummary>(`/adaptations/${project.id}/editorial-reviews`, {
          name, source_release_sha256: source.source_release_sha256, source_edition_id: edition || null,
          profile: { depth, allowed_changes: permission, voice, genre, preserve: preserve.split('\n').map(s => s.trim()).filter(Boolean), quality_dimensions: depth === 'scan' ? [] : dimensions, unit_ids: scope, platform: 'fanqie', continuity_mode: continuity },
        })
        openReview(next.id)
      } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
    }}>
      <label>任务名称<input required maxLength={120} value={name} onChange={e => setName(e.target.value)} /></label>
      <label>来源版本<select value={edition} onChange={e => setEdition(e.target.value)}><option value="">原冻结版 · {project.name}</option>{reviews.filter(r => r.edition_id).map(r => <option value={r.edition_id!} key={r.id}>{r.name} · 精修版</option>)}</select></label>
      <label>审读深度<select value={depth} onChange={e => setDepth(e.target.value as EditorialDepth)}>{Object.entries(depthNames).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label>
      <p className="editorial-help">{depth === 'scan' ? '执行规则检查并列出候选；报告不包含文学审读结论。' : depth === 'focused' ? '全量扫描，审读每章首尾和全部风险块，再做跨章复核。报告明确显示未读段落。' : '逐块阅读所选章节的全部正文，再完成跨章复核。修改后需要重新审读当前稿。'}</p>
      {depth !== 'scan' && <label>跨章一致性<select value={continuity} onChange={e => setContinuity(e.target.value as 'manual' | 'tracked')}><option value="tracked">建立人物、关系与知情账本，逐章核对</option><option value="manual">沿用跨章文字审读</option></select></label>}
      <label>允许的操作<select value={permission} onChange={e => setPermission(e.target.value as 'copyedit' | 'review_only')}><option value="copyedit">审阅并进行段落精修</option><option value="review_only">只审阅，保留正文</option></select></label>
      {depth !== 'scan' && <fieldset className="editorial-scope editorial-dimension-options"><legend>专项审读 · 已选 {dimensions.length} / 8 项</legend>{(['deslop', 'literary'] as const).map(group => <section key={group}><strong>{group === 'deslop' ? '去 AI 味' : '文学性'}</strong><div>{qualityDimensions.filter(d => d.group === group).map(d => <label key={d.id}><input type="checkbox" checked={dimensions.includes(d.id)} onChange={e => setDimensions(current => e.target.checked ? [...current, d.id] : current.filter(id => id !== d.id))} />{d.label}</label>)}</div></section>)}<p className="editorial-help">逐项提交判断、理由与原文证据。专项问题须修改复核、说明保留原因或明确暂缓；暂缓项仍会阻止专项验收通过。</p>{!dimensions.length && <p role="alert" className="form-error">请至少选择一个专项维度。</p>}</fieldset>}
      <label>作品类型<input required maxLength={120} value={genre} onChange={e => setGenre(e.target.value)} /></label>
      <label>文风要求<textarea required maxLength={6000} rows={3} value={voice} onChange={e => setVoice(e.target.value)} /></label>
      <label>必须保留的内容（每行一项，最多 30 项）<textarea maxLength={6000} rows={3} value={preserve} onChange={e => setPreserve(e.target.value)} /></label>
      <fieldset className="editorial-scope"><legend>审查章节 · 已选 {scope.length} 章</legend><button type="button" className="text-button" onClick={() => setScope(source?.units.map(u => u.id) || [])}>选择全部</button><button type="button" className="text-button" onClick={() => setScope([])}>清空选择</button><div>{source?.units.map(u => <label key={u.id}><input type="checkbox" checked={scope.includes(u.id)} onChange={e => setScope(current => e.target.checked ? [...current, u.id] : current.filter(id => id !== u.id))} />{u.title}</label>)}</div></fieldset>
      <p className="editorial-help">检查参考番茄小说质量要求。结构调整会保留为后续重写事项；具体表达是否需要修改，依据本书语境判断。</p>
      {error && <p role="alert" className="form-error">{error}</p>}
      <div className="modal-actions"><button type="button" className="button button-secondary" onClick={onClose} disabled={busy}>取消</button><button className="button button-primary" disabled={busy || !source || !scope.length || (depth !== 'scan' && !dimensions.length) || preserve.split('\n').filter(s => s.trim()).length > 30}>{busy && <Loader2 size={15} className="spin" />}建立审稿任务</button></div>
    </form>
  </Modal>
}

export function EditorialPage({ reviewId, notify }: { reviewId: string; notify: (message: string, error?: boolean) => void }) {
  const [session, setSession] = useState<EditorialSummary | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [handoff, setHandoff] = useState('')
  const [view, setView] = useState<'findings' | 'patches' | 'facts' | 'quality' | 'story' | 'reading'>('findings')
  const [returnView, setReturnView] = useState<typeof view | null>(null)
  const scrollPositions = useRef<Partial<Record<typeof view, number>>>({})
  const tabs = useRef<HTMLElement>(null)
  const [focus, setFocus] = useState<EditorialAnchor | null>(null)
  const [project, setProject] = useState<Adaptation | null>(null)
  const [continuation, setContinuation] = useState<'review' | 'rewrite' | null>(null)
  const send = useRequests()
  const activeRequest = useRef(false)
  const accept = (next: EditorialSummary) => setSession(current => current && current.revision > next.revision ? current : next)
  useEffect(() => {
    if (session) document.title = `${session.name} · 续章`
  }, [session?.name])
  useEffect(() => {
    let cancelled = false, pending = false
    async function refresh() {
      if (pending || activeRequest.current) return
      pending = true
      try {
        const next = await api<EditorialSummary>(`/editorial-reviews/${reviewId}`)
        if (!cancelled) { accept(next); setError('') }
      } catch (e) { if (!cancelled) setError((e as Error).message) } finally { pending = false }
    }
    void refresh(); const timer = setInterval(refresh, 4000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [reviewId])
  async function action(path: string, body: object = {}) {
    if (!session || activeRequest.current) return
    activeRequest.current = true; setBusy(true); setError('')
    try {
      accept(await send<EditorialSummary>(`/editorial-reviews/${reviewId}/${path}`, { ...body, expected_revision: session.revision }))
    } catch (e) {
      setError((e as Error).message)
      try { accept(await api<EditorialSummary>(`/editorial-reviews/${reviewId}`)) } catch { /* Preserve useful error. */ }
    } finally { activeRequest.current = false; setBusy(false) }
  }
  async function continueFrom(kind: 'review' | 'rewrite') {
    if (!session) return
    try { setProject(await api<Adaptation>(`/adaptations/${session.source_project_id}`)); setContinuation(kind) }
    catch (e) { notify((e as Error).message, true) }
  }
  function navigate(next: typeof view) {
    scrollPositions.current[view] = window.scrollY
    setView(next)
    requestAnimationFrame(() => window.scrollTo({ top: scrollPositions.current[next] ?? (tabs.current ? tabs.current.getBoundingClientRect().top + window.scrollY - 20 : 0), behavior: 'instant' }))
  }
  function showEvidence(anchor: EditorialAnchor) {
    setFocus(anchor); setReturnView(view); navigate('reading')
  }
  if (!session) return <main className="adapt-main"><p role={error ? 'alert' : 'status'}>{error || '正在恢复审稿任务…'}</p></main>
  const c = session.coverage
  return <main className="adapt-main editorial-main">
    <button className="text-button" onClick={() => { window.location.hash = `/projects/${session.source_project_id}` }}><ArrowLeft size={15} />返回来源项目</button>
    <div className="project-detail-heading"><div><h1>{session.name}</h1><p>来源《{session.source_name}》 · {depthNames[session.profile.depth]} · {c.selected_units} / {c.total_units} 章</p></div><div className="project-heading-actions"><span className="badge badge-neutral">{statusNames[session.status]}</span><button className="button button-primary" onClick={async () => {
      try { setHandoff((await api<{ prompt: string }>(`/editorial-reviews/${reviewId}/handoff`)).prompt) }
      catch (e) { notify((e as Error).message, true) }
    }}><Copy size={15} />交给 Codex 审稿</button></div></div>
    {error && <p role="alert" className="form-error">{error}</p>}
    <div className="editorial-metrics" aria-label="当前稿审查覆盖">
      <Metric label="程序扫描" count={c.scanned_paragraphs} total={c.total_paragraphs} unit="段" />
      <Metric label="文学审读" count={c.reviewed_paragraphs} total={c.total_paragraphs} unit="段" />
      <Metric label="跨章复核" count={c.audit_units} total={c.selected_units} unit="章" />
      <Metric label="修改后复核" count={c.verified_patches} total={c.applied_patches} unit="处" />
    </div>
    <section className="adapt-card editorial-quality" aria-label="去 AI 味与文学性专项状态">
      <div className="adapt-section-heading"><h2>去 AI 味与文学性</h2><span className={`badge ${session.quality.ready ? 'badge-green' : 'badge-neutral'}`}>{session.quality.mode === 'legacy' ? '旧版通用审读' : session.quality.mode === 'scan' ? '仅程序扫描' : session.quality.ready ? '专项验收通过' : '专项尚未通过'}</span></div>
      {session.quality.mode === 'specialized' ? <details className="editorial-quality-details"><summary>查看 {session.quality.dimensions.length} 项检查 · {session.quality.dimensions.reduce((total, d) => total + d.pending, 0)} 项待处理 · {session.quality.dimensions.reduce((total, d) => total + d.deferred, 0)} 项暂缓</summary><div className="editorial-quality-grid">{session.quality.dimensions.map(d => <div key={d.id}><strong>{d.label}</strong><span>已审 {d.reviewed_chunks} 块 · 跨章{d.audit_complete ? '已核对' : '待核对'}</span><span>{d.pending} 项待处理 · {d.deferred} 项暂缓</span><p>{d.instruction}</p></div>)}</div></details> : <p className="editorial-help">{session.quality.mode === 'scan' ? '规则只提供重复与句式候选，本轮未进行文学专项审读。' : '此任务建立于专项契约启用前，历史报告保留原有结论。以保存版本新建审稿任务后，可进行逐维度专项验收。'}</p>}
    </section>
    <section className="editorial-next adapt-card"><div><strong>{session.next_action.instruction}</strong><details className="editorial-brief"><summary>{session.profile.allowed_changes === 'review_only' ? '本轮仅审阅' : '本轮允许段落精修'} · 查看文风要求</summary><p>{session.profile.voice}</p></details></div>{!session.edition_id && <div><button className="button button-secondary" disabled={busy} onClick={() => void action('checks')}><RefreshCw size={15} className={busy ? 'spin' : ''} />运行程序检查</button><button className="button button-primary" disabled={busy || !session.can_finalize} onClick={() => void action('finalize', { name: session.name, expected_manuscript_sha256: session.manuscript_sha256 })}><Check size={15} />保存本轮版本</button></div>}</section>
    {session.readiness.reasons.length > 0 && <details className="editorial-risks"><summary>待处理与保留事项 · {session.readiness.reasons.length} 项</summary><ul>{session.readiness.reasons.map((reason, i) => <li key={i}>{reason}</li>)}</ul></details>}
    {session.edition_id && <section className="adapt-card editorial-delivery"><div><h2>{outcomeNames[session.quality_outcome]}已保存</h2><p>候选定稿条件：{session.readiness.ready ? '本轮约定已满足' : '仍有待处理事项'}。覆盖范围与遗留问题随报告保留。</p></div><div className="editorial-actions">{['epub', 'txt', 'md', 'json', 'report', 'patches', 'zip'].map(format => <a key={format} className="button button-secondary" href={`/api/editorial-editions/${session.edition_id}/export?format=${format}`}><Download size={14} />{{ report: '审稿报告', patches: '修改对照', json: '完整记录' }[format] || format.toUpperCase()}</a>)}</div><div className="editorial-actions"><button className="text-button" onClick={() => void continueFrom('review')}><Plus size={14} />以精修版再审</button><button className="text-button" onClick={() => void continueFrom('rewrite')}><GitBranch size={14} />接续深度重写</button></div></section>}
    <nav className="adapt-tabs" ref={tabs} aria-label="审稿内容">{([['findings', '问题与证据'], ['quality', '专项审读'], ['patches', '修改对照'], ['facts', '数值与事实'], ['story', '人物与故事图谱'], ['reading', '阅读正文']] as const).map(([id, name]) => <button key={id} className={view === id ? 'active' : ''} onClick={() => navigate(id)}>{name}</button>)}</nav>
    {(['findings', 'quality', 'patches', 'facts'] as const).map(kind => <div hidden={view !== kind} key={`${session.id}:${kind}`}><EditorialRecords session={session} kind={kind} busy={busy} onEvidence={showEvidence} onApply={ids => void action('apply', { patch_ids: ids, expected_manuscript_sha256: session.manuscript_sha256 })} /></div>)}
    <div hidden={view !== 'story'}><EditorialStory session={session} onEvidence={showEvidence} /></div>
    {view === 'reading' && <>{returnView && returnView !== 'reading' && <button className="button button-secondary editorial-back" onClick={() => navigate(returnView)}><ArrowLeft size={14} />返回刚才的列表</button>}<EditorialReader key={[session.id, session.manuscript_revision, focus?.source, focus?.unit_id, focus?.paragraph_id, focus?.paragraph_sha256, focus?.unit_revision, focus?.start, focus?.end].join(':')} session={session} focus={focus} /></>}
    {handoff && <Modal title="交给 Codex 审稿" onClose={() => setHandoff('')} wide><div className="codex-modal-content"><CopyBlock value={handoff} label="复制审稿任务" /><p className="editorial-help">把任务发送到已连接 novelstudio MCP 的 Codex 会话；中断后继续使用同一会话编号。</p></div></Modal>}
    {continuation === 'review' && project && <CreateEditorial project={project} reviews={[session]} initialEdition={session.edition_id!} onClose={() => setContinuation(null)} />}
    {continuation === 'rewrite' && project && <RewriteEditor project={project} editorialEditionId={session.edition_id!} onClose={() => setContinuation(null)} onSaved={next => { window.location.hash = `/projects/${next.id}` }} />}
  </main>
}

function Metric({ label, count, total, unit }: { label: string; count: number; total: number; unit: string }) {
  return <div><span>{label}</span><strong>{count.toLocaleString()} <small>/ {total.toLocaleString()} {unit}</small></strong><progress max={total || 1} value={count} aria-label={label} /></div>
}
