"""HTTP adapter; editorial transitions live in Editorials."""
from fastapi import APIRouter, Query

from .editorial_models import (CreateEditorial, EditorialWrite, SubmitEditorialReview, SubmitEditorialPatch,
                               ApplyEditorialPatches, SubmitEditorialVerification, FinalizeEditorial, SubmitEditorialStory,
                               LocateEditorialEvidence)


def editorial_router(service, download):
    router = APIRouter(prefix="/api")

    @router.get("/adaptations/{project_id}/editorial-source")
    def source(project_id: str, edition_id: str | None = None):
        return service.source(project_id, edition_id)

    @router.get("/adaptations/{project_id}/editorial-reviews")
    def sessions(project_id: str):
        return service.list(project_id)

    @router.post("/adaptations/{project_id}/editorial-reviews", status_code=201)
    def create(project_id: str, request: CreateEditorial):
        return service.create(project_id, request.model_dump())

    @router.get("/editorial-reviews/{review_id}")
    def get(review_id: str):
        return service.get(review_id)

    @router.get("/editorial-reviews/{review_id}/handoff")
    def handoff(review_id: str):
        return service.handoff(review_id)

    @router.get("/editorial-reviews/{review_id}/integrity")
    def integrity(review_id: str):
        return service.integrity(review_id)

    @router.get("/editorial-reviews/{review_id}/context")
    def context(review_id: str, source: str = "working", stage: str = "read", unit_id: str | None = None,
                cursor: str | None = Query(default=None, max_length=500), limit: int = Query(default=1, ge=1, le=3)):
        return service.context(review_id, source, stage, unit_id, cursor, limit)

    @router.post("/editorial-reviews/{review_id}/context/locate")
    def locate(review_id: str, request: LocateEditorialEvidence):
        return service.locate(review_id, request.model_dump())

    @router.get("/editorial-reviews/{review_id}/records")
    def records(review_id: str, kind: str = "findings", cursor: str | None = Query(default=None, max_length=500),
                limit: int = Query(default=20, ge=1, le=50), unit_id: str | None = None, category: str | None = None,
                status: str | None = None, query: str | None = Query(default=None, max_length=120), dimension: str | None = None):
        return service.records(review_id, kind, cursor, limit, unit_id, category, status, query, dimension)

    @router.post("/editorial-reviews/{review_id}/checks")
    def checks(review_id: str, request: EditorialWrite):
        return service.run_checks(review_id, request.model_dump())

    @router.get("/editorial-reviews/{review_id}/story")
    def story(review_id: str, kind: str = "relations", entity_id: str | None = None,
              at_unit_id: str | None = None, query: str | None = Query(default=None, max_length=120),
              cursor: str | None = Query(default=None, max_length=500), limit: int = Query(default=20, ge=1, le=50)):
        return service.story(review_id, kind, entity_id, at_unit_id, query, cursor, limit)

    @router.post("/editorial-reviews/{review_id}/story")
    def update_story(review_id: str, request: SubmitEditorialStory):
        return service.submit_story(review_id, request.model_dump())

    @router.post("/editorial-reviews/{review_id}/reports")
    def report(review_id: str, request: SubmitEditorialReview):
        return service.submit_review(review_id, request.model_dump())

    @router.post("/editorial-reviews/{review_id}/patches")
    def patch(review_id: str, request: SubmitEditorialPatch):
        return service.submit_patch(review_id, request.model_dump())

    @router.post("/editorial-reviews/{review_id}/apply")
    def apply(review_id: str, request: ApplyEditorialPatches):
        return service.apply(review_id, request.model_dump())

    @router.post("/editorial-reviews/{review_id}/verifications")
    def verify(review_id: str, request: SubmitEditorialVerification):
        return service.verify(review_id, request.model_dump())

    @router.post("/editorial-reviews/{review_id}/finalize")
    def finalize(review_id: str, request: FinalizeEditorial):
        return service.finalize(review_id, request.model_dump())

    @router.get("/editorial-editions/{edition_id}")
    def edition(edition_id: str):
        return service.edition(edition_id)

    @router.get("/editorial-editions/{edition_id}/export")
    def export(edition_id: str, format: str = Query(default="epub", pattern="^(epub|txt|md|json|report|patches|zip)$")):
        return download(*service.export(edition_id, format))

    return router
