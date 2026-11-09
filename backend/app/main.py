from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, File, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from .config import ROOT, Settings
from .adaptation import Adaptations, adaptation_guide
from .adaptation_models import (BookSource, NewAdaptation, SubmitAnalysis, SubmitPlan, SubmitDraft,
                                SubmitAdaptationReview, FinalizeAdaptation, SubmitFramework, UpdateAdaptation,
                                NewDeepRewrite, SubmitRewriteAudit)
from .catalog import source_catalog
from .service import Studio
from .editorial import Editorials
from .editorial_api import editorial_router
from .editorial_text import EditorialError
from .auth import Accounts
from .auth_api import AuthenticationMiddleware, auth_router


def create_app(data_dir: Path | None = None) -> FastAPI:
    settings = Settings(**({"data_dir": data_dir} if data_dir else {}))
    studio = Studio(settings)
    adaptations = Adaptations(studio)
    editorials = Editorials(studio)
    accounts = Accounts(studio.store, settings)
    remote_mcp = None

    @asynccontextmanager
    async def lifespan(_app):
        try:
            async with remote_mcp.session_manager.run():
                yield
        finally:
            studio.store.close()

    app = FastAPI(title="续章 · XUZHANG", version="0.3.0", lifespan=lifespan)
    app.state.studio = studio
    app.state.adaptations = adaptations
    app.state.editorials = editorials
    app.state.accounts = accounts
    app.add_middleware(AuthenticationMiddleware, accounts=accounts, settings=settings)
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins,
                       allow_credentials=True, allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["Content-Type", "Authorization", "X-CSRF-Token", "MCP-Protocol-Version"])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(set(settings.allowed_hosts + [urlsplit(settings.public_url).hostname])))
    app.include_router(auth_router(accounts, settings))

    @app.exception_handler(ValueError)
    async def value_error(_request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(EditorialError)
    async def editorial_error(_request, exc):
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail})

    @app.exception_handler(KeyError)
    async def missing_error(_request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc).strip("'")})

    @app.get("/api/health")
    def health():
        with studio.store.connection() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "app": "xuzhang", "database": "postgresql"}

    @app.get("/api/system")
    def system_info():
        return {"mcp": {"url": settings.public_url + "/mcp/", "api_url": settings.public_url},
                "limits": {"max_upload_mb": settings.max_upload_bytes // (1024 * 1024)},
                "storage": "PostgreSQL", "name": "续章", "version": "0.3.0"}

    @app.get("/api/books")
    def books():
        return studio.list_books()

    @app.get("/api/source-catalog")
    def catalog():
        return source_catalog()

    @app.get("/api/adaptation-guide")
    def guide(section: str = "workflow"):
        return adaptation_guide(section)

    @app.post("/api/books", status_code=201)
    async def upload(file: UploadFile = File(...)):
        content = await file.read(settings.max_upload_bytes + 1)
        await file.close()
        return studio.import_book(content, Path(file.filename or "novel.epub").name)

    @app.post("/api/demo")
    def demo():
        return studio.demo()

    @app.get("/api/books/{book_id}")
    def book(book_id: str):
        return studio.book(book_id)

    @app.get("/api/books/{book_id}/chapters/{chapter_id}")
    def read_chapter(book_id: str, chapter_id: str):
        return studio.read_chapter(book_id, chapter_id)

    @app.get("/api/books/{book_id}/original")
    def original(book_id: str):
        content, media_type, filename = studio.original(book_id)
        return download(content, media_type, filename)

    @app.put("/api/books/{book_id}/source")
    def set_source(book_id: str, request: BookSource):
        return studio.set_source(book_id, request.model_dump(exclude_unset=True))

    @app.get("/api/adaptations")
    def all_adaptations(book_id: str | None = None):
        return adaptations.list(book_id)

    @app.get("/api/books/{book_id}/adaptations")
    def list_adaptations(book_id: str):
        return adaptations.list(book_id)

    @app.post("/api/books/{book_id}/adaptations", status_code=201)
    def create_adaptation(book_id: str, request: NewAdaptation):
        return adaptations.create(book_id, request.model_dump())

    @app.get("/api/adaptations/{project_id}")
    def get_adaptation(project_id: str):
        return adaptations.get(project_id)

    @app.put("/api/adaptations/{project_id}/brief")
    def update_brief(project_id: str, request: UpdateAdaptation):
        return adaptations.update_brief(project_id, request.name, request.brief.model_dump(), request.chapter_ids, request.expected_revision)

    @app.put("/api/adaptations/{project_id}/framework")
    def save_framework(project_id: str, request: SubmitFramework):
        return adaptations.save_framework(project_id, request.framework.model_dump(), request.confirm, request.expected_revision)

    @app.get("/api/adaptations/{project_id}/handoff")
    def handoff(project_id: str):
        return adaptations.handoff(project_id)

    @app.post('/api/adaptations/{project_id}/deep-rewrites', status_code=201)
    def create_deep_rewrite(project_id: str, request: NewDeepRewrite):
        return adaptations.create_rewrite(project_id, request.model_dump())

    @app.get('/api/adaptations/{project_id}/source-chapters/{chapter_id}')
    def read_source_chapter(project_id: str, chapter_id: str):
        return adaptations.read_source_chapter(project_id, chapter_id)

    @app.put('/api/adaptations/{project_id}/rewrite-audit')
    def submit_rewrite_audit(project_id: str, request: SubmitRewriteAudit):
        return adaptations.submit_rewrite_audit(project_id, request.audit.model_dump(), request.expected_revision)

    @app.get("/api/adaptations/{project_id}/context")
    def adaptation_context(project_id: str, stage: str = "auto", cursor: int | None = None, limit: int = 1, unit_id: str | None = None):
        return adaptations.context(project_id, stage, cursor, limit, unit_id)

    @app.post("/api/adaptations/{project_id}/analyses")
    def submit_analysis(project_id: str, request: SubmitAnalysis):
        return adaptations.submit_analysis(project_id, request.chunk_id, request.analysis.model_dump(), request.expected_revision)

    @app.put("/api/adaptations/{project_id}/plan")
    def save_plan(project_id: str, request: SubmitPlan):
        return adaptations.save_plan(project_id, request.plan.model_dump(), request.expected_revision)

    @app.get("/api/adaptations/{project_id}/units/{unit_id}")
    def read_adaptation_unit(project_id: str, unit_id: str):
        return adaptations.read_unit(project_id, unit_id)

    @app.put("/api/adaptations/{project_id}/units/{unit_id}/draft")
    def submit_draft(project_id: str, unit_id: str, request: SubmitDraft):
        return adaptations.submit_draft(project_id, unit_id, request.draft.model_dump(), request.expected_revision)

    @app.put("/api/adaptations/{project_id}/units/{unit_id}/review")
    def submit_adaptation_review(project_id: str, unit_id: str, request: SubmitAdaptationReview):
        return adaptations.submit_review(project_id, unit_id, request.review.model_dump(), request.expected_revision)

    @app.post("/api/adaptations/{project_id}/finalize", status_code=201)
    def finalize_adaptation(project_id: str, request: FinalizeAdaptation):
        return adaptations.finalize(project_id, request.name, request.expected_revision)

    @app.get("/api/adaptation-versions/{version_id}/export")
    def export_adaptation(version_id: str, format: str = Query(default="epub", pattern="^(epub|txt|md|json)$")):
        return download(*adaptations.export(version_id, format))

    app.include_router(editorial_router(editorials, download))
    from .mcp_server import create_mcp
    remote_mcp = create_mcp(settings, api_app=app)
    app.mount("/mcp", remote_mcp.streamable_http_app())
    dist = ROOT / "frontend/dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


def download(content: bytes, media_type: str, filename: str):
    return Response(content, media_type=media_type, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


app = create_app()
