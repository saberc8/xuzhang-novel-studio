"""Enforce declared prose-review work, without pretending to judge literary merit."""
from .editorial_dimensions import DIMENSIONS
from .editorial_text import fail, validate_anchor


def enabled(session):
    return session["profile"]["depth"] != "scan" and bool(session["profile"].get("quality_dimensions"))


def validate_report(session, report, block):
    if not enabled(session):
        return
    expected = set(session["profile"]["quality_dimensions"])
    for f in report["findings"]:
        if f["category"] in {"prose", "dialogue"} and f["dimension"] not in expected:
            fail("quality_dimension_missing", "行文与对白问题须归入本轮约定的专项维度")
        if f["dimension"] and (f["dimension"] not in expected or DIMENSIONS[f["dimension"]]["category"] != f["category"]):
            fail("quality_dimension_mismatch", "问题的专项维度与类别或约定不一致")
    if report["kind"] == "findings":
        return
    assessments = report["quality_assessments"]
    if len(assessments) != len(expected) or {a["dimension"] for a in assessments} != expected:
        fail("quality_coverage_missing", "须逐项提交全部约定专项的判断、理由与当前证据", required=sorted(expected))
    for a in assessments:
        for evidence in a["evidence"]:
            validate_anchor(session, evidence, working_only=True)
            if block and (evidence["unit_id"] != block["unit_id"] or not any(
                p["id"] == evidence["paragraph_id"] and p["start"] <= evidence["start"] < evidence["end"] <= p["end"]
                for p in block["paragraphs"])):
                fail("quality_evidence_outside_chunk", "专项审读证据须来自当前分块显示的范围")
        indexes, ids = a["finding_indexes"], a["finding_ids"]
        if len(indexes) != len(set(indexes)) or len(ids) != len(set(ids)):
            fail("duplicate_id", "专项关联的问题不可重复")
        if (a["outcome"] == "issues") != bool(indexes or ids):
            fail("quality_findings_required", "发现问题须关联问题；通过或不适用不得关联未解决问题")
        if any(i < 0 or i >= len(report["findings"]) for i in indexes):
            fail("quality_finding_missing", "专项问题索引超出本报告 findings 范围")
        linked = [report["findings"][i] for i in indexes]
        for identifier in ids:
            f = session["findings"].get(identifier)
            if not f or f["status"] in {"resolved", "dismissed"}:
                fail("quality_finding_missing", "专项须引用已登记且尚未解决的问题")
            for evidence in f["evidence"]:
                validate_anchor(session, evidence, working_only=True)
            linked.append(f)
        if any(f.get("dimension") != a["dimension"] for f in linked):
            fail("quality_dimension_mismatch", "专项判断须关联相同维度的问题")
        if block and any(not any(e["unit_id"] == block["unit_id"] and any(
            p["id"] == e["paragraph_id"] and e["start"] < p["end"] and p["start"] < e["end"]
            for p in block["paragraphs"]) for e in f["evidence"]) for f in linked):
            fail("quality_finding_outside_chunk", "专项判断关联的问题须涉及当前分块")
    for i, f in enumerate(report["findings"]):
        if f["dimension"] and not any(i in a["finding_indexes"] for a in assessments):
            fail("quality_finding_unacknowledged", "本报告的专项问题须由对应维度的判断认领")


def validate_patch(session, patch):
    if not enabled(session):
        return
    expected = {session["findings"][i].get("dimension") for i in patch["finding_ids"]} - {None}
    dimensions = [g["dimension"] for g in patch["goals"]]
    if len(dimensions) != len(set(dimensions)) or set(dimensions) != expected:
        fail("quality_goals_missing", "修改目标须逐项对应关联问题的专项维度", required=sorted(expected))
    if not patch["preservation"]:
        fail("quality_preservation_missing", "须说明如何保留本轮文风、事实与保留项")


def validate_verification(session, verification):
    if not enabled(session):
        return
    assessments = verification["patch_assessments"]
    ids = [a["patch_id"] for a in assessments]
    if len(ids) != len(set(ids)) or set(ids) != set(verification["patch_ids"]):
        fail("quality_verification_missing", "须对每处待复核补丁提交前后比较、目标结论与保留项检查")
    for a in assessments:
        p = session["patches"].get(a["patch_id"])
        if not p:
            fail("patch_state", "待复核补丁不存在")
        expected = {g["dimension"] for g in p.get("goals", [])}
        if len(a["dimensions"]) != len(set(a["dimensions"])) or set(a["dimensions"]) != expected:
            fail("quality_verification_missing", "修改后复核须覆盖该补丁全部改善目标")
        if (a["outcome"] == "not_improved" or a["preservation"] == "failed") and verification["outcome"] not in {"open", "deferred"}:
            fail("quality_regression", "未改善或损伤保留项的修改须保持待处理或明确暂缓")


def quality_status(session, cov, reviews):
    mode = "scan" if session["profile"]["depth"] == "scan" else "specialized" if enabled(session) else "legacy"
    if mode != "specialized":
        return {"mode": mode, "review_complete": False, "ready": False, "dimensions": [], "pending": 0, "deferred": 0}
    latest = {}
    audit = None
    for r in reviews:
        report = r["report"]
        if report["kind"] == "chunk":
            latest[report["chunk_id"]] = report
        elif report["kind"] == "audit" and r["knowledge_revision"] == session["knowledge_revision"]:
            audit = report
    results = []
    findings = list(session["findings"].values())
    for dimension in session["profile"]["quality_dimensions"]:
        active = [f for f in findings if f.get("dimension") == dimension and f["status"] not in {"resolved", "dismissed"}]
        results.append({"id": dimension, **DIMENSIONS[dimension],
            "reviewed_chunks": sum(any(a["dimension"] == dimension for a in r.get("quality_assessments", [])) for r in latest.values()),
            "audit_complete": bool(audit and any(a["dimension"] == dimension for a in audit.get("quality_assessments", []))),
            "pending": sum(f["status"] != "deferred" for f in active), "deferred": sum(f["status"] == "deferred" for f in active)})
    complete = not cov["missing_chunk_ids"] and all(d["audit_complete"] and d["reviewed_chunks"] == len(latest) for d in results)
    pending, deferred = sum(d["pending"] for d in results), sum(d["deferred"] for d in results)
    verified = (cov["applied_patches"] == cov["verified_patches"]
                and not any(p["status"] == "proposed" for p in session["patches"].values())
                and cov["scanned_paragraphs"] == cov["total_paragraphs"])
    return {"mode": mode, "review_complete": complete, "ready": complete and verified and not pending and not deferred,
            "dimensions": results, "pending": pending, "deferred": deferred}
