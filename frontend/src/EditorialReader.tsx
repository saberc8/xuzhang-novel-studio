import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, LocateFixed, RefreshCw } from 'lucide-react'
import { api } from './api'
import { highlightEvidence } from './editorialReading'
import type { EditorialAnchor, EditorialContext, EditorialSummary } from './editorialTypes'

const locationLabels = {
  exact: '已定位证据，引文与所选正文版本一致。',
  text_matches: '所选正文中的引文一致，但来源版本或章节修订不同；原记录仍须按当前稿复核。',
  stale: '这处引用已过期。正在显示同一段落的现有文字，不高亮旧坐标；请核对下方原引用。',
}

export function EditorialReader({ session, focus }: { session: EditorialSummary; focus: EditorialAnchor | null }) {
  const [navigation, setNavigation] = useState({
    unit: focus?.unit_id || session.units.find(u => u.selected)!.id,
    source: focus?.source || 'working',
    cursor: null as string | null,
  })
  const { unit, source, cursor } = navigation
  const [data, setData] = useState<EditorialContext | null>(null)
  const [location, setLocation] = useState<EditorialContext['location']>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const target = useRef<HTMLElement>(null)
  const reader = useRef<HTMLElement>(null)
  const activeFocus = focus?.unit_id === unit ? focus : null

  useEffect(() => {
    const controller = new AbortController()
    setData(null); setError('')
    const params = new URLSearchParams({ unit_id: unit, source })
    if (cursor) params.set('cursor', cursor)
    const locating = activeFocus && !cursor
    const request = locating
      ? api<EditorialContext>(`/editorial-reviews/${session.id}/context/locate`, {
        method: 'POST', body: JSON.stringify({ anchor: activeFocus, source }), signal: controller.signal,
      })
      : api<EditorialContext>(`/editorial-reviews/${session.id}/context?${params}`, { signal: controller.signal })
    request.then(result => {
      if (controller.signal.aborted) return
      setData(result)
      if (result.location || !cursor) setLocation(result.location)
    }).catch(e => { if (!controller.signal.aborted) setError(e.message) })
    return () => controller.abort()
  }, [session.id, unit, source, cursor, activeFocus, attempt])

  useEffect(() => {
    if (!data) return
    if (target.current) target.current.scrollIntoView({ block: 'center' })
    else if (data.location || cursor) reader.current?.scrollIntoView({ block: 'start' })
  }, [data, cursor])

  function select(next: typeof navigation) {
    setData(null); setLocation(null); setNavigation(next)
  }
  function relocate() {
    select({ unit: focus?.unit_id || unit, source, cursor: null })
    setAttempt(value => value + 1)
  }

  return <section className="adapt-card editorial-reader" ref={reader}>
    <div className="editorial-reader-controls">
      <label>章节<select value={unit} onChange={e => select({ ...navigation, unit: e.target.value, cursor: null })}>{session.units.filter(u => u.selected).map(u => <option key={u.id} value={u.id}>{u.title}</option>)}</select></label>
      <label>正文版本<select value={source} onChange={e => select({ ...navigation, source: e.target.value as 'working' | 'baseline', cursor: null })}><option value="working">当前稿</option><option value="baseline">本轮来源稿</option></select></label>
      {focus && <button className="button button-secondary" onClick={relocate}><LocateFixed size={15} />返回证据位置</button>}
    </div>
    {activeFocus && location && <div className={`editorial-location ${location.status === 'stale' ? 'editorial-location-stale' : ''}`} role="status">
      <p>{locationLabels[location.status]}</p>
      <details open={location.status === 'stale'}><summary>原引用 · {activeFocus.paragraph_id} · 第 {activeFocus.start + 1}–{activeFocus.end} 个字</summary><blockquote>{activeFocus.quote}</blockquote></details>
    </div>}
    {error && <div role="alert" className="form-error"><p>{error}</p><button className="button button-secondary" onClick={relocate}><RefreshCw size={15} />重新读取</button></div>}
    {!data && !error && <p role="status">正在读取正文…</p>}
    {data && <p className="editorial-help">本章第 {data.offset + 1} / {data.total} 个阅读分块{activeFocus && location?.status !== 'stale' && ' · 引用跨分块时可翻页查看后续高亮'}</p>}
    {data?.items.map(chunk => <div key={chunk.id}><h2>{chunk.title}</h2>{chunk.paragraphs.map(paragraph => {
      const parts = location?.status === 'stale' ? null : highlightEvidence(chunk, paragraph, activeFocus)
      return <div className="editorial-paragraph" key={`${paragraph.id}:${paragraph.start}`}>
        <small>{paragraph.id}{paragraph.start ? ' · 续段' : ''}</small>
        <p>{parts ? <>{parts.before}<mark ref={target}>{parts.quote}</mark>{parts.after}</> : paragraph.text}</p>
      </div>
    })}</div>)}
    {data && <div className="editorial-pagination">
      <span>第 {data.offset + 1} / {data.total} 块</span>
      <button className="button button-secondary" disabled={!data.previous_cursor} onClick={() => setNavigation({ ...navigation, cursor: data.previous_cursor })}><ArrowLeft size={14} />上一页</button>
      <button className="button button-secondary" disabled={!data.next_cursor} onClick={() => setNavigation({ ...navigation, cursor: data.next_cursor })}>下一页<ArrowRight size={14} /></button>
    </div>}
  </section>
}
