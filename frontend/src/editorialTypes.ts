export type EditorialDepth = 'scan' | 'focused' | 'full'
export interface EditorialProfile {
  depth: EditorialDepth; platform: 'general' | 'fanqie'; genre: string; voice: string; preserve: string[]
  allowed_changes: 'review_only' | 'copyedit'; unit_ids: string[]; categories: string[]; blocking_severities: string[]
  continuity_mode?: 'manual' | 'tracked'
  quality_dimensions?: QualityDimension[]
}
export interface EditorialAnchor {
  source: 'working' | 'baseline'; unit_id: string; paragraph_id: string; unit_revision: number
  paragraph_sha256: string; quote: string; start: number; end: number; offset_unit: 'unicode_code_point'
}
export interface EditorialSummary {
  id: string; name: string; source_project_id: string; source_edition_id: string | null; source_name: string
  revision: number; manuscript_revision: number; manuscript_sha256: string; updated_at: string
  status: string; quality_outcome: string; profile: EditorialProfile; edition_id: string | null; can_finalize: boolean
  readiness: { ready: boolean; reasons: string[] }; next_action: { instruction: string; tool: string }
  finding_counts: Record<string, number>; patch_counts: Record<string, number>
  story_coverage: StoryCoverage
  quality: EditorialQuality
  units: { id: string; title: string; revision: number; paragraph_count: number; characters: number; selected: boolean }[]
  coverage: { total_units: number; selected_units: number; total_paragraphs: number; scanned_paragraphs: number; reviewed_paragraphs: number
    required_chunks: number; missing_chunk_ids: string[]; audit_units: number; applied_patches: number; verified_patches: number }
}
export interface EditorialFinding {
  id: string; category: string; severity: string; status: string; message: string; evidence: EditorialAnchor[]
  suggested_action: string; disposition_reason?: string; origin: string
  dimension?: QualityDimension | null
}
export interface EditorialPatch {
  id: string; status: string; anchor: EditorialAnchor; before: string; after: string; reason: string; finding_ids: string[]
  verified_manuscript_revision?: number
  goals?: { dimension: QualityDimension; expected_improvement: string }[]
  preservation?: string | null
  quality_assessment?: { dimensions: QualityDimension[]; outcome: 'improved' | 'retained' | 'not_improved'
    comparison: string; preservation: 'passed' | 'failed'; preservation_reason: string }
}
export interface EditorialFact {
  id: string; statement: string; status: string; perspective: string; value: string | null; date: string | null
  account: string | null; currency: string | null; settlement: string; evidence: EditorialAnchor[]
}
export interface EditorialChunk {
  id: string; unit_id: string; title: string; unit_revision: number
  paragraphs: { id: string; text: string; start: number; end: number; paragraph_sha256: string }[]
}
export interface EditorialPageData<T> { items: T[]; total: number; offset: number; next_cursor: string | null; revision: number }

export const qualityDimensions = [
  { id: 'template_repetition', label: '模板与重复', group: 'deslop' },
  { id: 'redundant_explanation', label: '重复解释', group: 'deslop' },
  { id: 'precision', label: '用词与具体性', group: 'literary' },
  { id: 'rhythm', label: '句段节奏', group: 'literary' },
  { id: 'imagery', label: '意象与修辞', group: 'literary' },
  { id: 'dialogue_voice', label: '人物声音', group: 'literary' },
  { id: 'subtext', label: '对白潜台词', group: 'literary' },
  { id: 'narrative_restraint', label: '叙述分寸', group: 'literary' },
] as const
export type QualityDimension = typeof qualityDimensions[number]['id']
export const dimensionName = (id: string) => qualityDimensions.find(d => d.id === id)?.label || id
export interface EditorialQuality {
  mode: 'scan' | 'legacy' | 'specialized'; ready: boolean; review_complete: boolean; pending: number; deferred: number
  dimensions: { id: QualityDimension; label: string; group: string; instruction: string; reviewed_chunks: number
    audit_complete: boolean; pending: number; deferred: number }[]
}
export interface EditorialReview {
  id: string; current: boolean; manuscript_revision: number; at: string
  report: { kind: 'chunk' | 'audit' | 'findings'; chunk_id?: string; summary: string
    quality_assessments?: { dimension: QualityDimension; outcome: 'passed' | 'issues' | 'not_applicable'
      rationale: string; evidence: EditorialAnchor[]; finding_indexes: number[]; finding_ids: string[] }[] }
}
export interface EditorialContext extends EditorialPageData<EditorialChunk> {
  offset: number; previous_cursor: string | null; source: 'working' | 'baseline'
  location: { status: 'exact' | 'text_matches' | 'stale'; unit_id: string; paragraph_id: string
    start: number; end: number; located_start: number } | null
}
export interface EditorialSource {
  source_release_sha256: string; source_edition_id: string | null; name: string
  units: { id: string; title: string; paragraph_count: number }[]
}
export interface StoryCoverage {
  mode: 'manual' | 'tracked'; reviewed_units: number; total_units: number; missing_unit_ids: string[]
  entities: StoryCount; relations: StoryCount; knowledge: StoryCount
}
interface StoryCount { total: number; confirmed: number; stale: number }
export interface StoryEntity {
  id: string; name: string; kind: string; description: string; status: string; current: boolean; confirmed: boolean
  aliases: { name: string; evidence: EditorialAnchor[] }[]; evidence: EditorialAnchor[]
}
export interface StoryRelation {
  id: string; source_id: string; target_id: string; label: string; polarity: string; perspective: string
  observer_id: string | null; explanation: string; status: string; current: boolean; confirmed: boolean
  from_unit_id: string; through_unit_id: string | null; story_time: string | null; evidence: EditorialAnchor[]
}
export interface StoryKnowledge {
  id: string; holder_id: string; fact_id: string; state: string; acquisition: string; status: string; current: boolean; confirmed: boolean
  from_unit_id: string; through_unit_id: string | null; story_time: string | null; evidence: EditorialAnchor[]
}
export interface StoryReview {
  unit_id: string; summary: string; current: boolean; entity_ids: string[]; relation_ids: string[]; knowledge_ids: string[]; evidence: EditorialAnchor[]
}
export type StoryKind = 'entities' | 'relations' | 'knowledge' | 'reviews'
export type StoryItem = StoryEntity | StoryRelation | StoryKnowledge | StoryReview
export interface StoryPage extends EditorialPageData<StoryItem> {
  nodes: StoryEntity[]; facts: EditorialFact[]; coverage: StoryCoverage; at_unit_id: string | null
}
