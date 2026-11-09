"""Editorial contract exercised via a real MCP client, including download bytes."""
import hashlib
import uuid


def anchor(chunk, paragraph):
    return {"source": "working", "unit_id": chunk["unit_id"], "paragraph_id": paragraph["id"],
            "unit_revision": chunk["unit_revision"], "paragraph_sha256": paragraph["paragraph_sha256"],
            "quote": paragraph["text"], "start": paragraph["start"], "end": paragraph["end"],
            "offset_unit": "unicode_code_point"}


async def check_editorial(session, http, parent_id, call):
    source = await call(session, "get_editorial_source", project_id=parent_id)
    guide = await call(session, "get_adaptation_guide", section="editorial")
    assert guide["ruleset_version"] and "editorial_patch" in guide["schemas"]
    assert "schema" in await call(session, "get_adaptation_guide", section="editorial_story")
    create = {"project_id": parent_id, "name": "文字精修 · MCP 验证", "profile": {"depth": "full"},
              "source_release_sha256": source["source_release_sha256"], "request_id": uuid.uuid4().hex}
    s = await call(session, "create_editorial_review", **create)
    assert await call(session, "create_editorial_review", **create) == s
    assert (await call(session, "list_editorial_reviews", project_id=parent_id))[0]["id"] == s["id"]
    assert s["id"] in (await call(session, "get_editorial_handoff", review_id=s["id"]))["prompt"]
    assert len(s["profile"]["quality_dimensions"]) == 8 and s["quality"]["mode"] == "specialized"

    def assessments(a, has_issue=False):
        return [{"dimension": d, "outcome": "issues" if has_issue and d == "precision" else "passed",
                 "rationale": "协议夹具：逐维度核对证据与约定，不作为文学能力评测。", "evidence": [a],
                 "finding_indexes": [0] if has_issue and d == "precision" else []}
                for d in s["profile"]["quality_dimensions"]]

    async def write(tool_name, **body):
        nonlocal s
        s = await call(session, tool_name, review_id=s["id"], expected_revision=s["revision"],
                       request_id=uuid.uuid4().hex, **body)
        return s

    await write("run_editorial_checks")
    context = await call(session, "get_editorial_context", review_id=s["id"])
    chunk = context["items"][0]
    p = chunk["paragraphs"][0]
    a = anchor(chunk, p)
    located = await call(session, "locate_editorial_evidence", review_id=s["id"], anchor=a)
    assert located["location"]["status"] == "exact" and located["items"] == [chunk]
    assert located["revision"] == s["revision"]
    report = {"kind": "chunk", "manuscript_sha256": s["manuscript_sha256"], "chunk_id": chunk["id"],
              "reviewed_paragraph_ids": [p["id"]], "categories": s["profile"]["categories"],
              "summary": "协议夹具：核对选择、记忆代价与脚印；这不是文学能力评测。",
              "evidence": [a], "findings": [{"category": "prose", "dimension": "precision", "severity": "suggestion",
                  "message": "协议夹具：补充一次环境回应，用于验证精修闭环。",
                  "evidence": [a], "suggested_action": "copyedit"}]}
    await write("submit_editorial_review", report={"kind": "findings", "manuscript_sha256": s["manuscript_sha256"],
        "summary": "协议夹具：仅登记局部候选，不授予文学覆盖。", "evidence": [a], "findings": report["findings"]})
    assert s["coverage"]["reviewed_chunks"] == 0 and s["coverage"]["audit_units"] == 0
    assert not s["quality"]["review_complete"] and not s["can_finalize"]
    filtered = await call(session, "get_editorial_records", review_id=s["id"], dimension="precision")
    assert filtered["total"] == 1 and filtered["items"][0]["dimension"] == "precision"
    missing = await session.call_tool("submit_editorial_review", {"review_id": s["id"],
        "expected_revision": s["revision"], "request_id": uuid.uuid4().hex, "report": report})
    assert missing.isError
    assert (await call(session, "get_editorial_review", review_id=s["id"]))["revision"] == s["revision"]
    report["quality_assessments"] = assessments(a, has_issue=True)
    await write("submit_editorial_review", report=report)
    fid = s["last_operation"]["result"]["finding_ids"][0]
    after = p["text"] + "潮声从门外传来。"
    await write("submit_editorial_patch", patch={"finding_ids": [fid], "anchor": a, "before": p["text"],
                "after": after, "reason": "协议夹具：添加不改变情节的环境回应。", "evidence": [a],
                "goals": [{"dimension": "precision", "expected_improvement": "让环境回应更具体。"}],
                "preservation": "保留原有行动、人物、时间和支付代价。"})
    pid = s["last_operation"]["result"]["patch_id"]
    apply = {"review_id": s["id"], "expected_revision": s["revision"], "request_id": uuid.uuid4().hex,
             "patch_ids": [pid], "expected_manuscript_sha256": s["manuscript_sha256"]}
    s = await call(session, "apply_editorial_patches", **apply)
    assert await call(session, "apply_editorial_patches", **apply) == s
    assert s["coverage"]["reviewed_paragraphs"] == 0
    assert (await call(session, "locate_editorial_evidence", review_id=s["id"], anchor=a))["location"]["status"] == "stale"
    assert (await call(session, "locate_editorial_evidence", review_id=s["id"], anchor=a,
                       source="baseline"))["location"]["status"] == "text_matches"
    failure = await session.call_tool("run_editorial_checks", {"review_id": s["id"], "expected_revision": 0, "request_id": uuid.uuid4().hex})
    assert failure.isError
    rejected = await http.post(f"/api/editorial-reviews/{s['id']}/finalize", json={
        "name": "过早冻结", "expected_revision": s["revision"], "expected_manuscript_sha256": s["manuscript_sha256"], "request_id": uuid.uuid4().hex})
    assert rejected.status_code == 422 and rejected.json()["detail"]["code"] == "incomplete_review"
    await write("run_editorial_checks")
    context = await call(session, "get_editorial_context", review_id=s["id"], stage="recheck")
    chunk = context["items"][0]
    a = anchor(chunk, chunk["paragraphs"][0])
    assert a["quote"] == after
    await write("submit_editorial_verification", verification={"manuscript_sha256": s["manuscript_sha256"],
        "finding_ids": [fid], "patch_ids": [pid], "outcome": "resolved", "reason": "环境回应已加入，原有行动与事实保持。",
        "evidence": [a], "patch_assessments": [{"patch_id": pid, "dimensions": ["precision"],
            "outcome": "improved", "comparison": "新增潮声带来具体的听觉回应，原有行动仍在。",
            "preservation": "passed", "preservation_reason": "人物行动和记忆代价未改动。"}]})
    await write("submit_editorial_review", report={**report, "manuscript_sha256": s["manuscript_sha256"],
        "chunk_id": chunk["id"], "evidence": [a], "findings": [], "quality_assessments": assessments(a),
        "facts": [{"id": "payment", "statement": "契约需要用记忆交换答案，支付后不能恢复。", "status": "confirmed", "evidence": [a]}]})
    story = {"manuscript_sha256": s["manuscript_sha256"],
             "entities": [
                 {"id": "liang", "name": "梁照", "description": "在码头读到师兄字迹的人物。", "status": "confirmed", "evidence": [a]},
                 {"id": "brother", "name": "师兄", "description": "留下字迹的梁照师兄。", "status": "confirmed", "evidence": [a]}],
             "relations": [{"id": "brothers", "source_id": "liang", "target_id": "brother", "label": "师兄弟",
                            "from_unit_id": chunk["unit_id"], "status": "confirmed",
                            "explanation": "正文明确称其为梁照的师兄。", "evidence": [a]}],
             "knowledge": [{"id": "payment-known", "holder_id": "liang", "fact_id": "payment", "state": "knows",
                            "from_unit_id": chunk["unit_id"], "status": "confirmed",
                            "acquisition": "通过师兄留下的字迹获知契约的支付代价。", "evidence": [a]}],
             "chapter_reviews": [{"unit_id": chunk["unit_id"], "summary": "核对师兄弟身份及梁照获得支付代价信息的来源。",
                                  "entity_ids": ["liang", "brother"], "relation_ids": ["brothers"],
                                  "knowledge_ids": ["payment-known"], "evidence": [a]}]}
    story_request = {"review_id": s["id"], "update": story, "expected_revision": s["revision"], "request_id": uuid.uuid4().hex}
    s = await call(session, "submit_editorial_story", **story_request)
    assert await call(session, "submit_editorial_story", **story_request) == s
    graph = await call(session, "get_editorial_story", review_id=s["id"], at_unit_id=chunk["unit_id"])
    assert graph["items"][0]["label"] == "师兄弟" and len(graph["nodes"]) == 2
    knowledge = await call(session, "get_editorial_story", review_id=s["id"], kind="knowledge", entity_id="liang")
    assert knowledge["facts"][0]["id"] == "payment" and knowledge["items"][0]["state"] == "knows"
    assert s["story_coverage"]["reviewed_units"] == 1
    await write("run_editorial_checks")
    await write("submit_editorial_review", report={"kind": "audit", "manuscript_sha256": s["manuscript_sha256"],
        "unit_revisions": context["unit_revisions"], "chapter_summaries": {chunk["unit_id"]: "追查脚印的行动与记忆代价一致。"},
        "summary": "对照当前稿，新增环境文字未改变选择及代价。", "evidence": [a], "quality_assessments": assessments(a)})
    assert s["can_finalize"] and s["quality"]["ready"] and s["quality"]["review_complete"]
    # Fresh request IDs with identical records must not erase completed coverage.
    await write("submit_editorial_story", update={k: v for k, v in story.items() if k != "chapter_reviews"})
    assert s["can_finalize"] and s["story_coverage"]["reviewed_units"] == 1
    assert all(not ids for ids in s["last_operation"]["result"]["changed_record_ids"].values())
    for kind in ("findings", "patches", "reviews", "scan_runs", "verifications", "events"):
        assert (await call(session, "get_editorial_records", review_id=s["id"], kind=kind))["items"]
    await write("finalize_editorial_review", name="文字精修 · MCP 验证", expected_manuscript_sha256=s["manuscript_sha256"])
    integrity = await call(session, "audit_editorial_integrity", review_id=s["id"])
    assert integrity["integrity_passed"] and not integrity["literary_reread_performed"], integrity
    assert (await call(session, "get_editorial_review", review_id=s["id"]))["revision"] == s["revision"]
    assert s["status"] == "completed" and s["quality_outcome"] == "full_review"
    for fmt in ("epub", "txt", "md", "json", "report", "patches", "zip"):
        export = await call(session, "get_editorial_export_url", edition_id=s["edition_id"], format=fmt)
        response = await http.get(export["url"])
        response.raise_for_status()
        assert hashlib.sha256(response.content).hexdigest() == export["sha256"]
        if fmt == "json":
            assert response.json()["report"]["story"]["relations"]["brothers"]["label"] == "师兄弟"
            assert response.json()["report"]["quality"]["ready"]
            assert response.json()["report"]["patches"][pid]["goals"][0]["dimension"] == "precision"
    new_source = await call(session, "get_editorial_source", project_id=parent_id, edition_id=s["edition_id"])
    next_session = await call(session, "create_editorial_review", project_id=parent_id,
        source_edition_id=s["edition_id"], source_release_sha256=new_source["source_release_sha256"],
        name="从精修版再审", profile={"depth": "focused"}, request_id=uuid.uuid4().hex)
    assert (await call(session, "get_editorial_context", review_id=next_session["id"]))["items"][0]["paragraphs"][0]["text"] == after
    parent = await call(session, "get_adaptation", project_id=parent_id)
    rewrite = await call(session, "create_deep_rewrite", project_id=parent_id, editorial_edition_id=s["edition_id"],
        name="从精修稿接续结构重写", brief={**parent["brief"], "rewrite": {
            "dimensions": ["motivation", "conflict", "plot_structure"], "narrative_strategy": "从人物主动公开证据开始组织故事。",
            "ending_direction": "主角承担新选择的代价。", "avoid": ["不能丢失精修后的事实和来源链。"]}})
    rewrite = await call(session, "save_adaptation_framework", project_id=rewrite["id"], framework=rewrite["framework"],
                         expected_revision=rewrite["revision"], confirm=True)
    baseline = await call(session, "get_adaptation_context", project_id=rewrite["id"], stage="baseline")
    assert baseline["items"][0]["paragraphs"][0]["text"] == after
    assert (await call(session, "get_editorial_review", review_id=s["id"]))["revision"] == s["revision"]
    return s
