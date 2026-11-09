"""Typed tools registered on the existing novelstudio server."""
from typing import Literal

from .editorial_models import Anchor, EditorialProfile, EditorialReport, EditorialPatch, EditorialVerification, StoryUpdate
from .editorial_export import FORMATS


def register_editorial_tools(mcp, request, read, write, settings):
    @mcp.tool(annotations=read)
    async def get_editorial_story(review_id: str, kind: str = "relations", entity_id: str | None = None,
                                  at_unit_id: str | None = None, query: str | None = None,
                                  cursor: str | None = None, limit: int = 20) -> dict:
        """读取人物/关系/知情账本与逐章覆盖，kind=entities/relations/knowledge/reviews。

        at_unit_id 只显示此章适用且证据已出现的记录；章序不等于故事时间。
        支持实体聚焦、按姓名/别名查询和分页，图只含当前页依赖。
        """
        return await request("GET", f"/editorial-reviews/{review_id}/story",
                             params={k: v for k, v in {"kind": kind, "entity_id": entity_id, "at_unit_id": at_unit_id,
                                                       "query": query, "cursor": cursor, "limit": limit}.items() if v is not None})

    @mcp.tool(annotations=write)
    async def submit_editorial_story(review_id: str, update: StoryUpdate, expected_revision: int, request_id: str) -> dict:
        """带证据登记实体、关系、知情状态和逐章核对。先读 guide('editorial_story')。

        用稳定实体 ID，禁止按同名自动合并；客观事实、人物认知和读者信息分开。
        改稿或上游记录变化后重新确认，再复核关系与知情依赖。
        """
        return await request("POST", f"/editorial-reviews/{review_id}/story",
                             json={"update": update.model_dump(), "expected_revision": expected_revision, "request_id": request_id})

    @mcp.tool(annotations=read)
    async def get_editorial_source(project_id: str, edition_id: str | None = None) -> dict:
        """读取冻结来源的章节与精确对象哈希；创建审稿前使用。"""
        return await request("GET", f"/adaptations/{project_id}/editorial-source", params={"edition_id": edition_id} if edition_id else {})

    @mcp.tool(annotations=read)
    async def list_editorial_reviews(project_id: str) -> list[dict]:
        """列出来源项目的独立审稿会话，优先恢复已有任务。"""
        return await request("GET", f"/adaptations/{project_id}/editorial-reviews")

    @mcp.tool(annotations=write)
    async def create_editorial_review(project_id: str, source_release_sha256: str, name: str,
                                      profile: EditorialProfile, request_id: str, source_edition_id: str | None = None) -> dict:
        """从冻结版创建文字质检会话；先读 guide('editorial')；保留原版。"""
        return await request("POST", f"/adaptations/{project_id}/editorial-reviews",
                             json={"source_release_sha256": source_release_sha256, "source_edition_id": source_edition_id,
                                   "name": name, "profile": profile.model_dump(), "request_id": request_id})

    @mcp.tool(annotations=read)
    async def get_editorial_review(review_id: str) -> dict:
        """恢复审稿范围、修订、覆盖与 next_action，正文另行分页读取。"""
        return await request("GET", f"/editorial-reviews/{review_id}")

    @mcp.tool(annotations=read)
    async def audit_editorial_integrity(review_id: str) -> dict:
        """只读全量架构审计，支持冻结版：核对来源、正文清单、补丁回放、历史证据和实际导出，并按当前规则重扫。

        返回绑定修订的完整性结果、结构化事实/故事缺口与旧版验收状态。
        不写覆盖、不更改冻结版，不把规则回放或证据匹配当作全书文学复读。
        """
        return await request("GET", f"/editorial-reviews/{review_id}/integrity")

    @mcp.tool(annotations=read)
    async def get_editorial_handoff(review_id: str) -> dict:
        """读取当前审稿会话的交接任务与约定。"""
        return await request("GET", f"/editorial-reviews/{review_id}/handoff")

    @mcp.tool(annotations=read)
    async def get_editorial_context(review_id: str, source: str = "working", stage: str = "read",
                                    unit_id: str | None = None, cursor: str | None = None, limit: int = 1) -> dict:
        """分页读取原版或工作稿。游标绑定正文修订；limit 1–3；遵守段落起止码点。"""
        return await request("GET", f"/editorial-reviews/{review_id}/context",
                             params={k: v for k, v in {"source": source, "stage": stage, "unit_id": unit_id,
                                                       "cursor": cursor, "limit": limit}.items() if v is not None})

    @mcp.tool(annotations=read)
    async def locate_editorial_evidence(review_id: str, anchor: Anchor,
                                         source: Literal["working", "baseline"] | None = None) -> dict:
        """直接定位证据所在分块；可继续前后分页。只读，不确认或改写旧证据。

        默认读证据的 source；可切换 working/baseline 比较。
        location.status=exact 表示版本及引文匹配；text_matches 仅文字一致；
        stale 表示引文已过期，仅导航同一段落，不能据此认定问题已解决。
        """
        return await request("POST", f"/editorial-reviews/{review_id}/context/locate",
                             json={"anchor": anchor.model_dump(), "source": source})

    @mcp.tool(annotations=read)
    async def get_editorial_records(review_id: str, kind: str = "findings", cursor: str | None = None, limit: int = 20,
                                    unit_id: str | None = None, category: str | None = None,
                                    status: str | None = None, query: str | None = None, dimension: str | None = None) -> dict:
        """分页读取记录；findings 可按 unit_id/category/dimension/status/query 筛选，limit 1–50。"""
        return await request("GET", f"/editorial-reviews/{review_id}/records",
                             params={k: v for k, v in {"kind": kind, "cursor": cursor, "limit": limit,
                                                       "unit_id": unit_id, "category": category, "dimension": dimension,
                                                       "status": status, "query": query}.items() if v is not None})

    @mcp.tool(annotations=write)
    async def run_editorial_checks(review_id: str, expected_revision: int, request_id: str) -> dict:
        """对所选正文执行版本化程序扫描；候选需结合语境判断。"""
        return await request("POST", f"/editorial-reviews/{review_id}/checks",
                             json={"expected_revision": expected_revision, "request_id": request_id})

    @mcp.tool(annotations=write)
    async def submit_editorial_review(review_id: str, report: EditorialReport, expected_revision: int, request_id: str) -> dict:
        """kind=findings 仅登记问题不授予覆盖；chunk/audit 提交分块/跨章审读与事实，不能把 focused 冒充 full。"""
        return await request("POST", f"/editorial-reviews/{review_id}/reports",
                             json={"report": report.model_dump(), "expected_revision": expected_revision, "request_id": request_id})

    @mcp.tool(annotations=write)
    async def submit_editorial_patch(review_id: str, patch: EditorialPatch, expected_revision: int, request_id: str) -> dict:
        """登记有证据的单段精修候选；反向补丁形成新修订。"""
        return await request("POST", f"/editorial-reviews/{review_id}/patches",
                             json={"patch": patch.model_dump(), "expected_revision": expected_revision, "request_id": request_id})

    @mcp.tool(annotations=write)
    async def apply_editorial_patches(review_id: str, patch_ids: list[str], expected_revision: int,
                                      expected_manuscript_sha256: str, request_id: str) -> dict:
        """原子应用补丁；同段冲突或过期证据拒绝全部；应用后必须复核。"""
        return await request("POST", f"/editorial-reviews/{review_id}/apply",
                             json={"patch_ids": patch_ids, "expected_revision": expected_revision,
                                   "expected_manuscript_sha256": expected_manuscript_sha256, "request_id": request_id})

    @mcp.tool(annotations=write)
    async def submit_editorial_verification(review_id: str, verification: EditorialVerification,
                                             expected_revision: int, request_id: str) -> dict:
        """依据当前正文复核问题与补丁；误报、暂缓和放弃候选须给原因。"""
        return await request("POST", f"/editorial-reviews/{review_id}/verifications",
                             json={"verification": verification.model_dump(), "expected_revision": expected_revision, "request_id": request_id})

    @mcp.tool(annotations=write)
    async def finalize_editorial_review(review_id: str, name: str, expected_revision: int,
                                         expected_manuscript_sha256: str, request_id: str) -> dict:
        """覆盖与修改后复核完成后冻结精修版；保存状态与质量 readiness 分开。"""
        return await request("POST", f"/editorial-reviews/{review_id}/finalize",
                             json={"name": name, "expected_revision": expected_revision,
                                   "expected_manuscript_sha256": expected_manuscript_sha256, "request_id": request_id})

    @mcp.tool(annotations=read)
    async def get_editorial_export_url(edition_id: str, format: str = "epub") -> dict:
        """获取已校验的 epub/txt/md/json/report/patches/zip 下载地址与哈希。"""
        if format not in FORMATS:
            raise ValueError("不支持的精修导出格式")
        edition = await request("GET", f"/editorial-editions/{edition_id}")
        return {"url": f"{settings.api_url}/api/editorial-editions/{edition_id}/export?format={format}",
                "authentication": "请在已登录当前账号的浏览器下载，或在 HTTP 请求中提供个人 Bearer 密钥。",
                **edition["export_manifest"][format], "quality_outcome": edition["quality_outcome"], "readiness": edition["readiness"]}
