"""Public, bounded contracts for editorial work. Manuscript text is never stripped."""
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .adaptation_models import Identifier, Name, StrictModel, Text
from .editorial_dimensions import DIMENSIONS, QualityDimension

Hash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Prose = Annotated[str, StringConstraints(min_length=1, max_length=200000)]
Category = Literal["timeline", "reference", "relationship", "knowledge", "money",
                   "causality", "prose", "dialogue", "pov", "structure", "length", "format"]
Severity = Literal["error", "warning", "suggestion"]
ReviewCategory = Literal["prose", "dialogue", "pov", "causality"]


class EditorialProfile(StrictModel):
    depth: Literal["scan", "focused", "full"] = "focused"
    platform: Literal["general", "fanqie"] = "fanqie"
    genre: Name = "小说"
    voice: Text = "尊重人物声音、原有叙事视角和表达习惯；仅修改有具体依据的问题。"
    preserve: list[Text] = Field(default_factory=lambda: ["保留情节、人物动机、事实与信息揭示顺序"], max_length=30)
    allowed_changes: Literal["review_only", "copyedit"] = "copyedit"
    unit_ids: list[Identifier] = Field(default_factory=list, max_length=200)
    blocking_severities: list[Severity] = Field(default_factory=lambda: ["error"], max_length=3)
    categories: list[ReviewCategory] = Field(default_factory=lambda: ["prose", "dialogue", "pov", "causality"], min_length=1, max_length=4)
    continuity_mode: Literal["manual", "tracked"] = "tracked"
    quality_dimensions: list[QualityDimension] = Field(default_factory=lambda: list(DIMENSIONS), max_length=8)

    @model_validator(mode="after")
    def unique_lists(self):
        for name in ("unit_ids", "categories", "blocking_severities", "quality_dimensions"):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} 不可重复")
        if self.depth != "scan":
            if not self.quality_dimensions:
                raise ValueError("文学审读须选择至少一个专项维度")
            if not {DIMENSIONS[d]["category"] for d in self.quality_dimensions} <= set(self.categories):
                raise ValueError("审读类别须包含所选专项的行文或对白类别")
        return self


class CreateEditorial(StrictModel):
    name: Name
    source_release_sha256: Hash
    source_edition_id: Identifier | None = None
    profile: EditorialProfile = Field(default_factory=EditorialProfile)
    request_id: Identifier


class EditorialWrite(StrictModel):
    expected_revision: int = Field(ge=0)
    request_id: Identifier


class Anchor(StrictModel):
    source: Literal["working", "baseline"] = "working"
    unit_id: Identifier
    paragraph_id: Identifier
    unit_revision: int = Field(ge=1)
    paragraph_sha256: Hash
    quote: Prose
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    offset_unit: Literal["unicode_code_point"] = "unicode_code_point"


class LocateEditorialEvidence(StrictModel):
    anchor: Anchor
    source: Literal["working", "baseline"] | None = None


class EditorialFinding(StrictModel):
    category: Category
    severity: Severity
    message: Text
    evidence: list[Anchor] = Field(min_length=1, max_length=20)
    suggested_action: Literal["copyedit", "structural_revision", "review"] = "review"
    dimension: QualityDimension | None = None


class QualityAssessment(StrictModel):
    dimension: QualityDimension
    outcome: Literal["passed", "issues", "not_applicable"]
    rationale: Text
    evidence: list[Anchor] = Field(min_length=1, max_length=20)
    # Indexes refer to this report's findings; IDs refer to already saved findings.
    finding_indexes: list[int] = Field(default_factory=list, max_length=50)
    finding_ids: list[Identifier] = Field(default_factory=list, max_length=50)


class Fact(StrictModel):
    id: Identifier
    statement: Text
    status: Literal["candidate", "confirmed", "disputed"] = "candidate"
    perspective: Literal["event", "belief", "reader_knowledge"] = "event"
    evidence: list[Anchor] = Field(min_length=1, max_length=10)
    # Numeric interpretation is supplied by the editor, never guessed from prose.
    value: Annotated[str, StringConstraints(pattern=r"^-?\d{1,16}(?:\.\d{1,6})?$")] | None = None
    date: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")] | None = None
    measure: Name | None = None
    account: Name | None = None
    currency: Name | None = None
    settlement: Literal["paid", "unredeemed", "custody", "not_applicable"] = "not_applicable"


class Constraint(StrictModel):
    id: Identifier
    operation: Literal["sum", "difference", "product", "days_between", "years_between"]
    operand_ids: list[Identifier] = Field(min_length=2, max_length=30)
    result_id: Identifier
    explanation: Text


class ChunkReview(StrictModel):
    kind: Literal["chunk"] = "chunk"
    manuscript_sha256: Hash
    chunk_id: Identifier
    reviewed_paragraph_ids: list[Identifier] = Field(min_length=1, max_length=30)
    categories: list[ReviewCategory] = Field(min_length=1, max_length=4)
    summary: Text
    evidence: list[Anchor] = Field(min_length=1, max_length=20)
    findings: list[EditorialFinding] = Field(default_factory=list, max_length=50)
    facts: list[Fact] = Field(default_factory=list, max_length=50)
    constraints: list[Constraint] = Field(default_factory=list, max_length=30)
    quality_assessments: list[QualityAssessment] = Field(default_factory=list, max_length=8)


class AuditReview(StrictModel):
    kind: Literal["audit"]
    manuscript_sha256: Hash
    unit_revisions: dict[Identifier, int]
    chapter_summaries: dict[Identifier, Text]
    summary: Text
    evidence: list[Anchor] = Field(min_length=1, max_length=400)
    findings: list[EditorialFinding] = Field(default_factory=list, max_length=50)
    facts: list[Fact] = Field(default_factory=list, max_length=50)
    constraints: list[Constraint] = Field(default_factory=list, max_length=30)
    quality_assessments: list[QualityAssessment] = Field(default_factory=list, max_length=8)


class FindingReport(StrictModel):
    # Recording an observation does not attest a whole chunk or literary rubric.
    kind: Literal["findings"]
    manuscript_sha256: Hash
    summary: Text
    evidence: list[Anchor] = Field(min_length=1, max_length=20)
    findings: list[EditorialFinding] = Field(min_length=1, max_length=50)


EditorialReport = Annotated[ChunkReview | AuditReview | FindingReport, Field(discriminator="kind")]


class SubmitEditorialReview(EditorialWrite):
    report: EditorialReport


StoryStatus = Literal["candidate", "confirmed", "disputed", "withdrawn"]


class StoryAlias(StrictModel):
    name: Name
    evidence: list[Anchor] = Field(min_length=1, max_length=5)


class StoryEntity(StrictModel):
    id: Identifier
    name: Name
    kind: Literal["character", "group", "item", "event", "location"] = "character"
    description: Text
    status: StoryStatus = "candidate"
    aliases: list[StoryAlias] = Field(default_factory=list, max_length=30)
    evidence: list[Anchor] = Field(min_length=1, max_length=10)


class StoryScope(StrictModel):
    # Narrative applicability, NOT an automatically inferred story chronology.
    from_unit_id: Identifier
    through_unit_id: Identifier | None = None
    story_time: Name | None = None
    status: StoryStatus = "candidate"
    evidence: list[Anchor] = Field(min_length=1, max_length=10)


class StoryRelation(StoryScope):
    id: Identifier
    source_id: Identifier
    target_id: Identifier
    label: Name
    polarity: Literal["affirmed", "denied"] = "affirmed"
    perspective: Literal["event", "belief", "reader_knowledge"] = "event"
    observer_id: Identifier | None = None
    explanation: Text

    @model_validator(mode="after")
    def perspective_owner(self):
        if (self.perspective == "belief") != (self.observer_id is not None):
            raise ValueError("人物认知必须填写 observer_id；客观事件与读者信息不填写")
        return self


class StoryKnowledge(StoryScope):
    id: Identifier
    holder_id: Identifier
    fact_id: Identifier
    state: Literal["knows", "believes", "denies", "unaware"]
    acquisition: Text


class StoryChapterReview(StrictModel):
    unit_id: Identifier
    summary: Text
    entity_ids: list[Identifier] = Field(default_factory=list, max_length=500)
    relation_ids: list[Identifier] = Field(default_factory=list, max_length=500)
    knowledge_ids: list[Identifier] = Field(default_factory=list, max_length=500)
    evidence: list[Anchor] = Field(min_length=1, max_length=20)


class StoryUpdate(StrictModel):
    manuscript_sha256: Hash
    entities: list[StoryEntity] = Field(default_factory=list, max_length=50)
    relations: list[StoryRelation] = Field(default_factory=list, max_length=50)
    knowledge: list[StoryKnowledge] = Field(default_factory=list, max_length=50)
    chapter_reviews: list[StoryChapterReview] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def nonempty(self):
        if not any((self.entities, self.relations, self.knowledge, self.chapter_reviews)):
            raise ValueError("请提交人物、关系、知情记录或逐章核对")
        return self


class SubmitEditorialStory(EditorialWrite):
    update: StoryUpdate


class PatchGoal(StrictModel):
    dimension: QualityDimension
    expected_improvement: Text


class EditorialPatch(StrictModel):
    finding_ids: list[Identifier] = Field(min_length=1, max_length=20)
    anchor: Anchor
    before: Prose
    after: Prose
    reason: Text
    evidence: list[Anchor] = Field(min_length=1, max_length=20)
    reverses_patch_id: Identifier | None = None
    goals: list[PatchGoal] = Field(default_factory=list, max_length=8)
    preservation: Text | None = None


class SubmitEditorialPatch(EditorialWrite):
    patch: EditorialPatch


class ApplyEditorialPatches(EditorialWrite):
    patch_ids: list[Identifier] = Field(min_length=1, max_length=100)
    expected_manuscript_sha256: Hash


class PatchAssessment(StrictModel):
    patch_id: Identifier
    dimensions: list[QualityDimension] = Field(default_factory=list, max_length=8)
    outcome: Literal["improved", "retained", "not_improved"]
    comparison: Text
    preservation: Literal["passed", "failed"]
    preservation_reason: Text


class EditorialVerification(StrictModel):
    manuscript_sha256: Hash
    finding_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    patch_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    outcome: Literal["resolved", "dismissed", "deferred", "open"]
    reason: Text
    evidence: list[Anchor] = Field(min_length=1, max_length=100)
    # Pending proposals may be explicitly abandoned; applied changes stay in history.
    discard_patch_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    patch_assessments: list[PatchAssessment] = Field(default_factory=list, max_length=100)


class SubmitEditorialVerification(EditorialWrite):
    verification: EditorialVerification


class FinalizeEditorial(EditorialWrite):
    name: Name
    expected_manuscript_sha256: Hash
