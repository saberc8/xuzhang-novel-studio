import { ArrowRight, BookOpen, CheckCircle2 } from 'lucide-react'
import type { Adaptation, AdaptationDraft, Comparison } from './types'

export function TranslationFlow({ project }: { project: Adaptation }) {
  return <section className="translation-flow adapt-card">
    <div className="adapt-section-heading"><div><h2>全译流程</h2></div></div>
    <div className="rewrite-flow"><span>原文与段落</span><ArrowRight size={14} /><strong>完整中文译稿</strong><ArrowRight size={14} /><span>故事解析</span><ArrowRight size={14} /><span>编辑改编框架</span><ArrowRight size={14} /><span>独立深度重写</span></div>
    <p className="adapt-prose">按原章逐段全译，保留原作背景与信息顺序。{project.release ? '译稿已冻结，可创建重写项目。' : '全部所选章节完成翻译和审校后，才能冻结译稿并重写。'}</p>
  </section>
}

export function AlignedTranslation({ original, draft, loading = false, error = '' }: { original: Comparison | null; draft: AdaptationDraft | null; loading?: boolean; error?: string }) {
  const translated = new Map(draft?.source_paragraph_ids?.map((id, i) => [id, draft.paragraphs[i]]))
  return <section className="translation-aligned">
    <div className="adapt-reading-heading"><span><BookOpen size={14} /> 原文与译文</span><span>{loading ? '正在载入原文与译文…' : error ? '载入失败' : original ? `${translated.size} / ${original.paragraphs.length} 段已对齐` : '暂无参考原文'}</span></div>
    {loading ? <p role="status">正在载入原文与译文…</p> : error ? <p role="alert" className="form-error">原文或译文载入失败，请重新打开本章重试。</p> : <div className="translation-aligned-body">{original?.paragraphs.map(p => <div className="translation-pair" key={p.id}><div><small>原文 · {p.id}</small><p>{p.original}</p></div><div><small>{translated.has(p.id) ? <CheckCircle2 size={12} /> : null} 译文</small><p>{translated.get(p.id) || '等待 Codex 提交完整译文'}</p></div></div>)}</div>}
    {!!original?.layout_notes?.length && <details className="translation-layout"><summary>另行记录的 {original.layout_notes.length} 项版面信息</summary>{original.layout_notes.map(n => <p key={n.paragraph_id}>{n.paragraph_id} · {n.kind === 'heading' ? '章节标题（显示于目录）' : n.kind === 'illustration_caption' ? '原版插图说明' : '原版插图占位'}：{n.text}</p>)}<p>这些条目保留在来源记录中，不计为小说正文段落。</p></details>}
  </section>
}
