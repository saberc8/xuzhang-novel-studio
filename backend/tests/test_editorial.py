"""Editorial invariants use PostgreSQL and real frozen source fixtures."""
import hashlib
import io
import json
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from conftest import sign_in
from pydantic import ValidationError

from backend.app.editorial import Editorials
from backend.app.editorial_checks import check_constraints
from backend.app.editorial_export import verify_epub
from backend.app.editorial_models import Fact, Constraint
from backend.app.editorial_text import EditorialError, anchor_for, manuscript_hash, text_hash
from backend.app.main import create_app
from backend.app.rewriting import fingerprint
from test_adaptation import workspace, create_project, analyze_all, make_plan, draft_for, review_all
from test_rewriting import rewrite_request


@pytest.fixture
def editorial(workspace):
    studio, _, adaptations = workspace
    project = analyze_all(adaptations, create_project(workspace))
    project = adaptations.save_plan(project["id"], make_plan(), project["revision"])
    for i, unit in enumerate(project["units"]):
        draft = draft_for(adaptations, project, unit["id"])
        draft["paragraphs"] = ([draft["paragraphs"][0],
                                "巡查记在1922年。如今是1926年，𠮷先生翻到旧页，指着两年前的记录。",
                                "保管款是五张各一万一千元的票，共五万五千元。三张各一万元的饭票尚未兑付。"]
                               if i == 0 else [draft["paragraphs"][0] + "他先核对账簿，才做决定。", "【待补场景】"])
        project = adaptations.submit_draft(project["id"], unit["id"], draft, project["revision"])
    project = review_all(adaptations, project)
    adaptations.finalize(project["id"], project["name"], project["revision"])
    service = Editorials(studio)
    source = service.source(project["id"])
    return service, adaptations, source


def create(service, source, depth="full", **profile):
    return service.create(source["project_id"], {
        "name": "文字质检", "source_release_sha256": source["source_release_sha256"],
        # Preserve the original workflow regression; tracked continuity has its
        # own integration suite with explicit entity and knowledge assertions.
        "profile": {"depth": depth, "continuity_mode": "manual", "quality_dimensions": ["precision"], **profile}, "request_id": uuid.uuid4().hex})


def write(service, method, summary, **body):
    # Supply valid quality declarations for the existing workflow fixtures.
    # Adversarial quality-contract tests call service methods directly.
    body = deepcopy(body)
    dimensions = summary["profile"].get("quality_dimensions", [])
    if summary["profile"]["depth"] != "scan" and dimensions:
        if method == "submit_review":
            report = body["report"]
            for f in report.get("findings", []):
                if f["category"] in {"prose", "dialogue"}:
                    f.setdefault("dimension", "dialogue_voice" if f["category"] == "dialogue" else dimensions[0])
            report.setdefault("quality_assessments", [{"dimension": d,
                "outcome": "issues" if any(f.get("dimension") == d for f in report.get("findings", [])) else "passed",
                "rationale": "协议夹具：核对约定维度及引文，用于验证流程，不作为文学评测。",
                "evidence": report["evidence"][:1],
                "finding_indexes": [i for i, f in enumerate(report.get("findings", [])) if f.get("dimension") == d]}
                for d in dimensions])
        if method == "submit_patch":
            p = body["patch"]
            state = stored(service, summary)
            selected = {state["findings"].get(fid, {}).get("dimension") for fid in p["finding_ids"]} - {None}
            p.setdefault("goals", [{"dimension": d, "expected_improvement": "协议夹具：验证关联目标。"} for d in sorted(selected)])
            p.setdefault("preservation", "协议夹具：保留人物、事件与原有表达约定。")
        if method == "verify":
            v = body["verification"]
            state = stored(service, summary)
            v.setdefault("patch_assessments", [{"patch_id": pid,
                "dimensions": [g["dimension"] for g in state["patches"].get(pid, {}).get("goals", [])],
                "outcome": "improved", "comparison": "协议夹具：已对照修改前后正文。",
                "preservation": "passed", "preservation_reason": "协议夹具：核对事实与文风约定。"} for pid in v.get("patch_ids", [])])
    return getattr(service, method)(summary["id"], {"expected_revision": summary["revision"],
                                                  "request_id": uuid.uuid4().hex, **body})


def stored(service, summary):
    return service.store.get("editorial", summary["id"])


def evidence(service, summary, unit=0, paragraph=1, quote=None):
    u = stored(service, summary)["working"][unit]
    p = u["paragraphs"][paragraph]
    return anchor_for(u, p, quote, p["text"].index(quote) if quote else 0)


def report_for(service, summary, block=None):
    c = block or service.context(summary["id"])["items"][0]
    p = c["paragraphs"][0]
    anchor = {"source": "working", "unit_id": c["unit_id"], "paragraph_id": p["id"],
              "unit_revision": c["unit_revision"], "paragraph_sha256": p["paragraph_sha256"],
              "quote": p["text"], "start": p["start"], "end": p["end"], "offset_unit": "unicode_code_point"}
    return {"kind": "chunk", "manuscript_sha256": summary["manuscript_sha256"], "chunk_id": c["id"],
            "reviewed_paragraph_ids": list(dict.fromkeys(p["id"] for p in c["paragraphs"])),
            "categories": summary["profile"]["categories"], "summary": "核对了账簿、行动与时间证据，区分叙述和人物理解。",
            "evidence": [anchor]}


def add_issue(service, summary, **finding):
    f = {"category": "timeline", "severity": "error", "message": "1922 至 1926 相隔四年，指代旧巡查的两年前不符。",
         "evidence": [evidence(service, summary, quote="两年前")], "suggested_action": "copyedit", **finding}
    report = {**report_for(service, summary), "findings": [f]}
    summary = write(service, "submit_review", summary, report=report)
    fid = summary["last_operation"]["result"]["finding_ids"][0]
    return summary, fid


def propose(service, summary, fid, after=None, **extra):
    anchor = evidence(service, summary)
    return write(service, "submit_patch", summary, patch={
        "finding_ids": [fid], "anchor": anchor, "before": anchor["quote"],
        "after": after or anchor["quote"].replace("两年前", "四年前"),
        "reason": "依据同段明确年份修复跨度，保留人物与事件。",
        "evidence": [anchor], **extra})


def read_all(service, summary):
    cursor = None
    while True:
        context = service.context(summary["id"], cursor=cursor, limit=3)
        for block in context["items"]:
            summary = write(service, "submit_review", summary, report=report_for(service, summary, block))
        cursor = context["next_cursor"]
        if not cursor:
            return summary


def audit(service, summary):
    units = [u for u in stored(service, summary)["working"] if u["id"] in summary["profile"]["unit_ids"]]
    return write(service, "submit_review", summary, report={
        "kind": "audit", "manuscript_sha256": summary["manuscript_sha256"],
        "unit_revisions": {u["id"]: u["revision"] for u in units},
        "chapter_summaries": {u["id"]: "核对当前章行动后果与前后文知情边界。" for u in units},
        "summary": "核对选定范围全部章节的时间、因果和知情关系。",
        "evidence": [anchor_for(u, u["paragraphs"][0]) for u in units]})


def freeze(service, summary):
    return write(service, "finalize", summary, name="已复核精修版", expected_manuscript_sha256=summary["manuscript_sha256"])


def test_full_lifecycle_invalidation_exports_and_lineage(editorial):
    service, adaptations, source = editorial
    original = adaptations.export(source["project_id"], "json")[0]
    s = create(service, source)
    s = write(service, "run_checks", s)
    s, fid = add_issue(service, s)
    s = read_all(service, s)
    s = audit(service, s)
    assert s["coverage"]["reviewed_paragraphs"] == 5
    s = propose(service, s, fid)
    pid = service.records(s["id"], "patches")["items"][0]["id"]
    s = write(service, "apply", s, patch_ids=[pid], expected_manuscript_sha256=s["manuscript_sha256"])
    assert s["manuscript_revision"] == 2 and s["coverage"]["reviewed_paragraphs"] == 0
    assert stored(service, s)["findings"][fid]["status"] == "needs_recheck"
    with pytest.raises(EditorialError, match="尚未完成"):
        freeze(service, s)
    s = write(service, "run_checks", s)
    s = write(service, "verify", s, verification={"manuscript_sha256": s["manuscript_sha256"], "finding_ids": [fid],
              "patch_ids": [pid], "outcome": "resolved", "reason": "当前文字改为四年前，年份与相邻行动一致。",
              "evidence": [evidence(service, s)]})
    s = audit(service, read_all(service, s))
    assert s["can_finalize"]
    s = freeze(service, s)
    assert s["status"] == "completed"
    for fmt in ("epub", "txt", "md", "json", "report", "patches", "zip"):
        body, _, _ = service.export(s["edition_id"], fmt)
        assert hashlib.sha256(body).hexdigest() == service.edition(s["edition_id"])["export_manifest"][fmt]["sha256"]
        assert service.export(s["edition_id"], fmt)[0] == body
    edition = service.store.get("editorial_edition", s["edition_id"])
    assert json.loads(service.export(s["edition_id"], "json")[0]) == edition
    assert fingerprint(edition) == service.source(source["project_id"], s["edition_id"])["source_release_sha256"]
    verify_epub(service.export(s["edition_id"], "epub")[0], edition["manuscript"])
    with zipfile.ZipFile(io.BytesIO(service.export(s["edition_id"], "zip")[0])) as archive:
        for item in json.loads(archive.read("manifest.json")).values():
            assert hashlib.sha256(archive.read(item["filename"])).hexdigest() == item["sha256"]
    assert adaptations.export(source["project_id"], "json")[0] == original
    with pytest.raises(EditorialError, match="已冻结"):
        write(service, "run_checks", s)
    new_source = service.source(source["project_id"], s["edition_id"])
    next_review = service.create(source["project_id"], {"name": "再审", "source_edition_id": s["edition_id"],
                    "source_release_sha256": new_source["source_release_sha256"], "request_id": uuid.uuid4().hex})
    assert "四年前" in evidence(service, next_review)["quote"]
    rewritten = adaptations.create_rewrite(source["project_id"], {**rewrite_request(), "editorial_edition_id": s["edition_id"]})
    assert "四年前" in adaptations.reference_book(adaptations.store.get("adaptation", rewritten["id"]))["chapters"][0]["paragraphs"][1]["text"]
    assert rewritten["parent_editorial_edition_id"] == s["edition_id"]


def test_idempotency_concurrent_create_and_optimistic_writes(editorial):
    service, _, source = editorial
    req = {"name": "并发创建", "source_release_sha256": source["source_release_sha256"], "request_id": "same-key"}
    with ThreadPoolExecutor(2) as pool:
        results = [f.result() for f in [pool.submit(copy_context().run, service.create, source["project_id"], req) for _ in range(2)]]
    assert results[0] == results[1]
    assert len(service.list(source["project_id"])) == 1
    with pytest.raises(EditorialError) as error:
        service.create(source["project_id"], {**req, "name": "另一个请求"})
    assert error.value.detail["code"] == "idempotency_conflict"
    s = results[0]
    scan_req = {"expected_revision": s["revision"], "request_id": "scan-key"}
    s = service.run_checks(s["id"], scan_req)
    assert service.run_checks(s["id"], scan_req) == s
    before = deepcopy(stored(service, s))
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(copy_context().run, service.run_checks, s["id"], {"expected_revision": s["revision"], "request_id": f"parallel-{i}"}) for i in range(2)]
        values, conflicts = [], []
        for f in futures:
            try:
                values.append(f.result())
            except EditorialError as exc:
                conflicts.append(exc.detail["code"])
    assert len(values) == 1 and conflicts == ["revision_conflict"]
    assert len(stored(service, s)["scan_runs"]) == len(before["scan_runs"]) + 1
    assert Editorials(service.studio).get(s["id"])["revision"] == s["revision"] + 1


@pytest.mark.parametrize("alter,code", [
    ({"quote": "不在正文"}, "evidence_mismatch"), ({"start": 99999}, "evidence_mismatch"),
    ({"end": 99999}, "evidence_mismatch"), ({"paragraph_id": "missing"}, "evidence_missing"),
    ({"paragraph_sha256": "0" * 64}, "evidence_stale"), ({"unit_revision": 999}, "evidence_stale"),
    ({"source": "baseline"}, "evidence_source"),
])
def test_reject_bad_evidence_without_write(editorial, alter, code):
    service, _, source = editorial
    s = create(service, source)
    r = report_for(service, s)
    r["evidence"][0].update(alter)
    with pytest.raises(EditorialError) as error:
        write(service, "submit_review", s, report=r)
    assert error.value.detail["code"] == code
    assert service.get(s["id"])["revision"] == 0


def test_overlap_and_stale_patch_roll_back_whole_batch(editorial):
    service, _, source = editorial
    s = create(service, source)
    s, fid = add_issue(service, s)
    s = propose(service, s, fid)
    s = propose(service, s, fid, after=evidence(service, s)["quote"].replace("两年前", "四年以前"))
    ids = [p["id"] for p in service.records(s["id"], "patches")["items"]]
    before = stored(service, s)
    with pytest.raises(EditorialError, match="同一段"):
        write(service, "apply", s, patch_ids=ids, expected_manuscript_sha256=s["manuscript_sha256"])
    assert stored(service, s) == before
    s = write(service, "apply", s, patch_ids=ids[:1], expected_manuscript_sha256=s["manuscript_sha256"])
    before = stored(service, s)
    with pytest.raises(EditorialError, match="过期"):
        write(service, "apply", s, patch_ids=ids[1:], expected_manuscript_sha256=s["manuscript_sha256"])
    assert stored(service, s) == before


def test_unicode_quotes_repeated_offsets_and_undo(editorial):
    service, _, source = editorial
    s = create(service, source)
    original_hash = s["manuscript_sha256"]
    s, fid = add_issue(service, s)
    # Astral 𠮷 occupies two UTF-16 units but one Python code point.
    a = evidence(service, s, quote="两年前")
    assert a["start"] != len(evidence(service, s)["quote"][:a["start"]].encode("utf-16-le")) // 2
    s = propose(service, s, fid)
    pid = next(iter(stored(service, s)["patches"]))
    s = write(service, "apply", s, patch_ids=[pid], expected_manuscript_sha256=s["manuscript_sha256"])
    old = stored(service, s)["patches"][pid]
    s = propose(service, s, fid, after=old["before"], reverses_patch_id=pid)
    reverse = s["last_operation"]["result"]["patch_id"]
    s = write(service, "apply", s, patch_ids=[reverse], expected_manuscript_sha256=s["manuscript_sha256"])
    assert s["manuscript_sha256"] == original_hash and s["manuscript_revision"] == 3
    assert len(stored(service, s)["patches"]) == 2


def test_cursor_binding_scope_and_read_only(editorial):
    service, _, source = editorial
    s = create(service, source)
    context = service.context(s["id"])
    cursor = context["next_cursor"]
    assert cursor and service.context(s["id"], cursor=cursor)["items"][0]["unit_id"] == "u2"
    s, fid = add_issue(service, s)
    # Finding/review writes do not invalidate manuscript cursors.
    service.context(s["id"], cursor=cursor)
    with pytest.raises(EditorialError, match="分页条件"):
        service.context(s["id"], source="baseline", cursor=cursor)
    s = propose(service, s, fid)
    pid = next(iter(stored(service, s)["patches"]))
    s = write(service, "apply", s, patch_ids=[pid], expected_manuscript_sha256=s["manuscript_sha256"])
    with pytest.raises(EditorialError, match="分页条件"):
        service.context(s["id"], cursor=cursor)
    scoped = create(service, source, allowed_changes="review_only", unit_ids=["u1"])
    scoped, fid = add_issue(service, scoped)
    with pytest.raises(EditorialError, match="仅审阅"):
        propose(service, scoped, fid)
    with pytest.raises(EditorialError, match="范围"):
        service.context(scoped["id"], unit_id="u2")
    assert scoped["coverage"]["selected_units"] == 1


def test_export_failure_is_atomic_and_retry_safe(editorial, monkeypatch):
    service, _, source = editorial
    s = write(service, "run_checks", create(service, source, depth="scan"))
    before = stored(service, s)
    from backend.app import editorial as module
    real_build = module.build_exports
    def broken(_):
        raise ValueError("模拟导出失败")
    monkeypatch.setattr(module, "build_exports", broken)
    with pytest.raises(ValueError, match="模拟"):
        freeze(service, s)
    assert stored(service, s) == before
    assert not service.store.list("editorial_edition") and not service.store.list("editorial_export")
    monkeypatch.setattr(module, "build_exports", real_build)
    frozen = freeze(service, s)
    assert frozen["quality_outcome"] == "scan_only" and not frozen["readiness"]["ready"]


def test_structural_issue_cannot_be_polished_away(editorial):
    service, _, source = editorial
    s = create(service, source)
    s, fid = add_issue(service, s, category="structure", message="中毒警告后迁居迟缓，需要重设行动因果。",
                       suggested_action="structural_revision")
    with pytest.raises(EditorialError, match="结构问题"):
        propose(service, s, fid)
    with pytest.raises(EditorialError, match="结构遗留"):
        write(service, "verify", s, verification={"manuscript_sha256": s["manuscript_sha256"], "finding_ids": [fid],
              "outcome": "resolved", "reason": "只改语言不足以解决行动因果。", "evidence": [evidence(service, s)]})
    s = write(service, "verify", s, verification={"manuscript_sha256": s["manuscript_sha256"], "finding_ids": [fid],
              "outcome": "deferred", "reason": "保留待深度重写解决。", "evidence": [evidence(service, s)]})
    s = write(service, "run_checks", s)
    s = audit(service, read_all(service, s))
    s = freeze(service, s)
    assert s["quality_outcome"] == "needs_structural_revision" and not s["readiness"]["ready"]


def test_long_paragraph_coverage_is_not_inferred_from_one_fragment(editorial):
    service, _, source = editorial
    # A separate test source fixture with a long paragraph, never touching a user project.
    parent = service.store.get("adaptation", source["project_id"])
    parent["_release"]["units"][0]["draft"]["paragraphs"] = ["长段证据" * 4000]
    service.store.put("adaptation", parent)
    source = service.source(source["project_id"])
    s = create(service, source)
    c = service.context(s["id"])["items"][0]
    assert len(c["paragraphs"][0]["text"]) == 6000
    s = write(service, "submit_review", s, report=report_for(service, s, c))
    assert s["coverage"]["reviewed_paragraphs"] == 0
    with pytest.raises(EditorialError, match="必读分块"):
        audit(service, s)
    s = read_all(service, s)
    assert s["coverage"]["reviewed_paragraphs"] == s["coverage"]["total_paragraphs"]


def facts_session():
    text = "1922年巡查，1926年归来，相隔两年。五月二十一日至七月十三日，五张一万一千元的票是五万五千元；三张一万元饭票未兑付。"
    u = {"id": "u1", "revision": 1, "paragraphs": [{"id": "p1", "text": text}]}
    a = anchor_for(u, u["paragraphs"][0])
    s = {"working": [u], "profile": {"unit_ids": ["u1"]}, "manuscript_revision": 1, "facts": {}, "constraints": {}}
    def add(identifier, value=None, **fields):
        s["facts"][identifier] = {**Fact(id=identifier, statement="经所引正文解释的事实。", status="confirmed",
                                       value=value, evidence=[a], **fields).model_dump(), "manuscript_revision": 1}
    add("start", "1922", measure="year")
    add("end", "1926", measure="year")
    add("span", "2", measure="years")
    add("count", "5", measure="count")
    for key, value in [("price", "11000"), ("total", "55000"), ("other", "10000")]:
        add(key, value, measure="money", account="保管款" if key != "other" else "个人票据", currency="元",
            settlement="custody" if key != "other" else "unredeemed")
    return s, add


@pytest.mark.parametrize("operation,operands,result,expected", [
    ("years_between", ["start", "end"], "span", "mismatch"),
    ("product", ["count", "price"], "total", "passed"),
    ("sum", ["price", "other"], "total", "needs_review"),
    ("difference", ["total", "other"], "price", "needs_review"),
])
def test_known_time_and_money_constraints(operation, operands, result, expected):
    s, _ = facts_session()
    s["constraints"]["test"] = Constraint(id="test", operation=operation, operand_ids=operands, result_id=result,
                                         explanation="长夜归舟的明确年份与账户分类回归。").model_dump()
    checked = check_constraints(s)[0]
    assert checked["status"] == expected
    if operation == "years_between":
        assert checked["computed"] == "4"


def test_exact_date_approximation_and_belief_are_not_confused():
    s, add = facts_session()
    add("day1", date="1926-05-21")
    add("day2", date="1926-07-13")
    add("days", "53", measure="days")
    s["constraints"]["dates"] = Constraint(id="dates", operation="days_between", operand_ids=["day1", "day2"],
                                          result_id="days", explanation="核对精确公历日间隔。").model_dump()
    assert check_constraints(s)[0]["computed"] == "53"
    s["facts"]["day1"]["perspective"] = "belief"
    assert check_constraints(s)[0]["status"] == "needs_review"
    s["facts"]["day1"]["perspective"] = "event"
    s["facts"]["day1"]["date"] = "1926-02-30"
    assert check_constraints(s)[0]["status"] == "needs_review"


def test_api_errors_are_structured_and_schemas_forbid_extra_fields(editorial, tmp_path):
    service, _, source = editorial
    app = create_app(tmp_path)
    with TestClient(app) as client:
        sign_in(client)
        response = client.post(f"/api/adaptations/{source['project_id']}/editorial-reviews",
                               json={"name": "API", "source_release_sha256": "0" * 64, "request_id": "test"})
        assert response.status_code == 409 and response.json()["detail"]["code"] == "source_changed"
        response = client.get("/api/adaptation-guide?section=editorial_patch")
        assert response.json()["schema"]["additionalProperties"] is False
        s = create(service, source, depth="scan")
        response = client.post(f"/api/editorial-reviews/{s['id']}/checks",
                               json={"expected_revision": 123, "request_id": "check"})
        assert response.status_code == 409 and response.json()["detail"]["current_revision"] == 0
        response = client.post(f"/api/editorial-reviews/{s['id']}/checks",
                               json={"expected_revision": 0, "request_id": "check", "passed": True})
        assert response.status_code == 422


def test_focused_and_full_have_distinct_required_coverage(editorial):
    service, _, source = editorial
    parent = service.store.get("adaptation", source["project_id"])
    parent["_release"]["units"][0]["draft"]["paragraphs"] = [f"第{i}段。" + "场景行动和具体后果。" * 100 for i in range(12)]
    service.store.put("adaptation", parent)
    source = service.source(source["project_id"])
    focused = create(service, source, depth="focused", unit_ids=["u1"])
    full = create(service, source, depth="full", unit_ids=["u1"])
    focused = write(service, "run_checks", focused)
    # Repetition is intentional in this pagination fixture; acknowledge the new candidates.
    for f in stored(service, focused)["findings"].values():
        if f.get("dimension"):
            focused = write(service, "verify", focused, verification={"manuscript_sha256": focused["manuscript_sha256"],
                "finding_ids": [f["id"]], "outcome": "dismissed", "reason": "分页夹具中的有意重复，保留测试输入。", "evidence": f["evidence"]})
    assert focused["coverage"]["required_chunks"] == 2
    assert full["coverage"]["required_chunks"] > 2
    blocks = service.context(focused["id"], limit=3)["items"]
    assert len(blocks) == 3
    for block in (blocks[0], blocks[-1]):
        focused = write(service, "submit_review", focused, report=report_for(service, focused, block))
    focused = audit(service, focused)
    assert focused["can_finalize"]
    assert focused["coverage"]["reviewed_paragraphs"] < focused["coverage"]["total_paragraphs"]
    saved = freeze(service, focused)
    assert saved["quality_outcome"] == "focused_review"
    assert not full["can_finalize"]


def test_scan_does_not_ban_dialogue_patterns_or_unbalanced_cross_paragraph_quotes(editorial):
    service, _, source = editorial
    parent = service.store.get("adaptation", source["project_id"])
    parent["_release"]["units"][0]["draft"]["paragraphs"] = ["“不是这个意思。", "我明天还会来。”他说。", "——这句是人物有意反驳。"]
    service.store.put("adaptation", parent)
    s = create(service, service.source(source["project_id"]), depth="scan", unit_ids=["u1"])
    s = write(service, "run_checks", s)
    assert all(f["rule_id"] == "length.short" for f in stored(service, s)["findings"].values())


def test_rule_cannot_resolve_while_hit_and_discard_is_explicit(editorial):
    service, _, source = editorial
    s = write(service, "run_checks", create(service, source))
    finding = next(f for f in stored(service, s)["findings"].values() if f.get("rule_id") == "format.placeholder")
    current = evidence(service, s, unit=1, paragraph=1)
    with pytest.raises(EditorialError, match="规则仍命中"):
        write(service, "verify", s, verification={"manuscript_sha256": s["manuscript_sha256"],
            "finding_ids": [finding["id"]], "outcome": "resolved", "reason": "仍在当前文本，不能直接通过。", "evidence": [current]})
    s, fid = add_issue(service, s)
    s = propose(service, s, fid)
    pid = s["last_operation"]["result"]["patch_id"]
    with pytest.raises(EditorialError, match="仍有关联候选"):
        write(service, "verify", s, verification={"manuscript_sha256": s["manuscript_sha256"], "finding_ids": [fid],
            "outcome": "deferred", "reason": "等待查对年代资料。", "evidence": [evidence(service, s)]})
    s = write(service, "verify", s, verification={"manuscript_sha256": s["manuscript_sha256"], "finding_ids": [fid],
        "discard_patch_ids": [pid], "outcome": "deferred", "reason": "先查对年代资料，暂时放弃这份候选。",
        "evidence": [evidence(service, s)]})
    assert stored(service, s)["patches"][pid]["status"] == "discarded"
    assert stored(service, s)["findings"][fid]["status"] == "deferred"


def test_constraint_lost_confirmation_is_not_silently_resolved(editorial):
    service, _, source = editorial
    s = create(service, source)
    a = evidence(service, s)
    facts = [Fact(id=key, statement="同段年代事实。", status="confirmed", measure=measure, value=value, evidence=[a]).model_dump()
             for key, value, measure in [("start", "1922", "year"), ("end", "1926", "year"), ("span", "2", "years")]]
    constraints = [Constraint(id="years", operation="years_between", operand_ids=["start", "end"],
                             result_id="span", explanation="年份跨度校验。").model_dump()]
    s = write(service, "submit_review", s, report={**report_for(service, s), "facts": facts, "constraints": constraints})
    s = write(service, "run_checks", s)
    f = next(f for f in stored(service, s)["findings"].values() if f.get("constraint_id") == "years")
    facts[0]["status"] = "candidate"
    s = write(service, "submit_review", s, report={**report_for(service, s), "facts": facts})
    s = write(service, "run_checks", s)
    assert stored(service, s)["findings"][f["id"]]["status"] == "needs_recheck"
    with pytest.raises(EditorialError, match="约束尚未通过"):
        write(service, "verify", s, verification={"manuscript_sha256": s["manuscript_sha256"],
            "finding_ids": [f["id"]], "outcome": "resolved", "reason": "事实未确认不能作通过结论。", "evidence": [a]})
    assert any("需要复核" in r for r in s["readiness"]["reasons"])


@pytest.mark.parametrize("change", ["value", "interpretation", "confirmation"])
def test_dismissed_constraint_requires_recheck_when_its_basis_changes(editorial, change):
    service, _, source = editorial
    s = create(service, source)
    a = evidence(service, s)
    facts = [Fact(id=key, statement="同段年代事实。", status="confirmed", measure=measure,
                  value=value, evidence=[a]).model_dump()
             for key, value, measure in [("start", "1922", "year"), ("end", "1926", "year"), ("span", "2", "years")]]
    constraint = Constraint(id="years", operation="years_between", operand_ids=["start", "end"],
                            result_id="span", explanation="年份跨度校验。").model_dump()
    s = write(service, "submit_review", s, report={**report_for(service, s), "facts": facts, "constraints": [constraint]})
    s = write(service, "run_checks", s)
    f = next(f for f in stored(service, s)["findings"].values() if f.get("constraint_id") == "years")
    s = write(service, "verify", s, verification={"manuscript_sha256": s["manuscript_sha256"],
        "finding_ids": [f["id"]], "outcome": "dismissed", "reason": "夹具：保留本次解释，验证后续失效。", "evidence": [a]})
    s = write(service, "run_checks", s)
    assert stored(service, s)["findings"][f["id"]]["status"] == "dismissed"
    if change == "value":
        facts[2]["value"] = "3"
    elif change == "interpretation":
        facts[2]["statement"] = "编辑重新解释了该时间跨度；算式和引文不变。"
    else:
        facts[0]["status"] = "candidate"
    s = write(service, "submit_review", s, report={**report_for(service, s), "facts": facts})
    s = write(service, "run_checks", s)
    assert stored(service, s)["findings"][f["id"]]["status"] == "needs_recheck"
    assert not s["can_finalize"]


def test_rule_versions_invalidate_work_but_never_relabel_frozen_edition(editorial, monkeypatch):
    service, _, source = editorial
    active = write(service, "run_checks", create(service, source))
    active = audit(service, read_all(service, active))
    frozen = freeze(service, active)
    next_source = service.source(source["project_id"], frozen["edition_id"])
    active = service.create(source["project_id"], {"name": "新版规则再审", "source_edition_id": frozen["edition_id"],
        "source_release_sha256": next_source["source_release_sha256"], "profile": {"depth": "full", "continuity_mode": "manual"}, "request_id": uuid.uuid4().hex})
    active = write(service, "run_checks", active)
    active = audit(service, read_all(service, active))
    from backend.app import editorial as module
    monkeypatch.setattr(module, "RUBRIC_VERSION", "fiction-next")
    assert service.get(active["id"])["coverage"]["reviewed_paragraphs"] == 0
    assert service.get(frozen["id"])["coverage"] == frozen["coverage"]
    assert service.get(frozen["id"])["quality_outcome"] == frozen["quality_outcome"]


def test_wrong_project_edition_source_tamper_and_export_corruption(editorial):
    service, adaptations, source = editorial
    s = freeze(service, write(service, "run_checks", create(service, source, depth="scan")))
    parent = service.store.get("adaptation", source["project_id"])
    other = deepcopy(parent)
    other["id"] = uuid.uuid4().hex
    service.store.put("adaptation", other)
    with pytest.raises(EditorialError, match="不属于"):
        service.source(other["id"], s["edition_id"])
    with pytest.raises(ValueError, match="不属于"):
        adaptations.create_rewrite(other["id"], {**rewrite_request(), "editorial_edition_id": s["edition_id"]})
    active = create(service, source)
    parent["_release"]["name"] += "被改动"
    service.store.put("adaptation", parent)
    with pytest.raises(EditorialError, match="指纹"):
        write(service, "run_checks", active)
    export = service.store.get("editorial_export", s["edition_id"] + ":txt")
    export["body"] = "eA=="
    service.store.put("editorial_export", export)
    with pytest.raises(EditorialError, match="清单不一致"):
        service.export(s["edition_id"], "txt")


def test_bad_patch_model_and_batch_manifest_cannot_change_text(editorial):
    service, _, source = editorial
    s = create(service, source)
    s, fid = add_issue(service, s)
    before = stored(service, s)
    for after in ("   ", evidence(service, s)["quote"] + "\n另一段"):
        with pytest.raises(EditorialError, match="单段"):
            propose(service, s, fid, after=after)
    assert stored(service, s) == before
    s = propose(service, s, fid)
    pid = s["last_operation"]["result"]["patch_id"]
    for ids, sha, code in [([pid, pid], s["manuscript_sha256"], "duplicate_patch"), ([pid], "0" * 64, "manuscript_stale")]:
        with pytest.raises(EditorialError) as error:
            write(service, "apply", s, patch_ids=ids, expected_manuscript_sha256=sha)
        assert error.value.detail["code"] == code
    assert stored(service, s)["manuscript_revision"] == 1
