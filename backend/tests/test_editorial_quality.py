"""Quality is a verifiable workflow contract, not a claim of literary judgment."""
import json
import uuid
from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.app.editorial_dimensions import DIMENSIONS
from backend.app.editorial_models import EditorialProfile
from backend.app.editorial_patterns import candidates
from backend.app.editorial_text import EditorialError, anchor_for
from test_editorial import (editorial, workspace, create, stored, evidence, report_for,
                            write, read_all, audit, freeze)


def raw(service, method, s, **body):
    return getattr(service, method)(s["id"], {"expected_revision": s["revision"],
        "request_id": uuid.uuid4().hex, **body})


def assessment(dimension, a, **values):
    return {"dimension": dimension, "outcome": "passed", "rationale": "协议样本：已对照该处上下文及约定。",
            "evidence": [a], **values}


def report(service, s, findings=None, block=None):
    r = report_for(service, s, block)
    r["findings"] = findings or []
    r["quality_assessments"] = [assessment(d, r["evidence"][0],
        outcome="issues" if any(f.get("dimension") == d for f in r["findings"]) else "passed",
        finding_indexes=[i for i, f in enumerate(r["findings"]) if f.get("dimension") == d])
        for d in s["profile"]["quality_dimensions"]]
    return r


def finding(service, s, severity="warning", paragraph=1, dimension="precision"):
    return {"category": DIMENSIONS[dimension]["category"], "dimension": dimension, "severity": severity,
            "message": "协议样本：用词需要对照具体动作核实。", "suggested_action": "copyedit",
            "evidence": [evidence(service, s, paragraph=paragraph)]}


def with_issue(service, source, severity="warning", **profile):
    s = create(service, source, unit_ids=["u1"], blocking_severities=[], **profile)
    s = raw(service, "run_checks", s)
    s = raw(service, "submit_review", s, report=report(service, s, [finding(service, s, severity)]))
    return s, s["last_operation"]["result"]["finding_ids"][0]


def patch(service, s, fid):
    a = stored(service, s)["findings"][fid]["evidence"][0]
    return {"finding_ids": [fid], "anchor": a, "before": a["quote"], "after": a["quote"].replace("翻到旧页", "翻到巡查簿旧页"),
            "reason": "协议样本：明确所指的簿册。", "evidence": [a],
            "goals": [{"dimension": "precision", "expected_improvement": "让旧页的指代更具体。"}],
            "preservation": "保留原有年份、人物行动和叙述视角。"}


def verification(service, s, fid, pid=None, **values):
    return {"manuscript_sha256": s["manuscript_sha256"], "finding_ids": [fid],
            "patch_ids": [pid] if pid else [], "outcome": "resolved", "reason": "协议样本：对照改前改后并核对上下文。",
            "evidence": [evidence(service, s)], "patch_assessments": ([{
                "patch_id": pid, "dimensions": ["precision"], "outcome": "improved",
                "comparison": "旧页现明确为巡查簿的旧页，指代更具体。", "preservation": "passed",
                "preservation_reason": "年份、行动、人物与视角保持。"}] if pid else []), **values}


def assert_rejected(service, method, s, code, **body):
    before = stored(service, s)
    with pytest.raises(EditorialError) as error:
        raw(service, method, s, **body)
    assert error.value.detail["code"] == code
    assert stored(service, s) == before


def test_profile_defaults_and_selection_requirements():
    assert EditorialProfile().quality_dimensions == list(DIMENSIONS)
    assert EditorialProfile(depth="scan", quality_dimensions=[]).quality_dimensions == []
    for values in ({"quality_dimensions": []}, {"quality_dimensions": ["rhythm", "rhythm"]},
                   {"quality_dimensions": ["dialogue_voice"], "categories": ["prose"]}):
        with pytest.raises(ValidationError):
            EditorialProfile(**values)


def observations(service, s, findings=None):
    return {"kind": "findings", "manuscript_sha256": s["manuscript_sha256"],
            "summary": "仅登记有证据的局部问题，不声明分块文学审读完成。",
            "evidence": [evidence(service, s)], "findings": findings or [finding(service, s)]}


def test_observation_registers_findings_without_granting_literary_coverage(editorial):
    service, _, source = editorial
    s = create(service, source, depth="full")
    before = s["coverage"]
    s = raw(service, "submit_review", s, report=observations(service, s))
    assert len(s["last_operation"]["result"]["finding_ids"]) == 1
    assert s["coverage"] == before
    assert not s["quality"]["review_complete"] and not s["can_finalize"]
    assert all(not d["reviewed_chunks"] and not d["audit_complete"] for d in s["quality"]["dimensions"])
    assert service.records(s["id"], "reviews")["items"][0]["report"]["kind"] == "findings"


def test_observation_does_not_supersede_an_existing_chunk_or_audit(editorial):
    service, _, source = editorial
    s = create(service, source, unit_ids=["u1"], depth="full", continuity_mode="manual")
    r = report(service, s)
    s = raw(service, "submit_review", s, report=r)
    s = raw(service, "submit_review", s, report={"kind": "audit", "manuscript_sha256": s["manuscript_sha256"],
        "unit_revisions": {"u1": 1}, "chapter_summaries": {"u1": "核对1922巡查与1926回忆。"},
        "summary": "核对本章的年份与指代。", "evidence": [evidence(service, s)],
        "quality_assessments": [assessment("precision", evidence(service, s))]})
    cov = s["coverage"]
    s = raw(service, "submit_review", s, report=observations(service, s))
    assert s["coverage"] == cov
    assert s["quality"]["dimensions"][0]["audit_complete"]
    history = service.records(s["id"], "reviews")["items"]
    assert not history[0]["current"]
    assert {r["report"]["kind"] for r in history if r["current"]} == {"chunk", "audit"}


@pytest.mark.parametrize("bad", ["stale", "dimension", "evidence"])
def test_observation_rejects_invalid_evidence_and_dimensions_atomically(editorial, bad):
    service, _, source = editorial
    s = create(service, source)
    r = observations(service, s)
    if bad == "stale": r["manuscript_sha256"] = "0" * 64
    elif bad == "dimension": r["findings"][0]["dimension"] = "rhythm"
    else: r["findings"][0]["evidence"][0]["quote"] = "不在原文中的引文"
    before = stored(service, s)
    with pytest.raises(EditorialError):
        raw(service, "submit_review", s, report=r)
    assert stored(service, s) == before


@pytest.mark.parametrize("bad,code", [
    ("missing", "quality_coverage_missing"), ("duplicate", "quality_coverage_missing"),
    ("issues_without_findings", "quality_findings_required"), ("wrong_index", "quality_finding_missing"),
    ("outside_chunk", "quality_evidence_outside_chunk"), ("unowned", "quality_finding_unacknowledged"),
    ("missing_dimension", "quality_dimension_missing"), ("category_mismatch", "quality_dimension_mismatch"),
])
def test_reports_reject_incomplete_or_unrelated_quality_atomically(editorial, bad, code):
    service, _, source = editorial
    s = create(service, source)
    r = report(service, s)
    a = r["quality_assessments"][0]
    if bad == "missing": r.pop("quality_assessments")
    elif bad == "duplicate": r["quality_assessments"].append(deepcopy(a))
    elif bad == "issues_without_findings": a["outcome"] = "issues"
    elif bad == "wrong_index": a.update(outcome="issues", finding_indexes=[0])
    elif bad == "outside_chunk": a["evidence"] = [evidence(service, s, unit=1, paragraph=0)]
    else:
        f = finding(service, s)
        r["findings"] = [f]
        if bad == "missing_dimension": f.pop("dimension")
        elif bad == "category_mismatch": f["category"] = "dialogue"
    assert_rejected(service, "submit_review", s, code, report=r)


def test_no_evidence_no_rationale_and_bad_dimension_rejected_by_schema(editorial):
    service, _, source = editorial
    s = create(service, source)
    for field, value in (("evidence", []), ("rationale", " "), ("dimension", "invented")):
        r = report(service, s)
        r["quality_assessments"][0][field] = value
        before = stored(service, s)
        with pytest.raises(ValidationError):
            raw(service, "submit_review", s, report=r)
        assert stored(service, s) == before


def test_linked_findings_must_be_current_same_dimension_and_in_chunk(editorial):
    service, _, source = editorial
    s, fid = with_issue(service, source, quality_dimensions=["precision", "rhythm"])
    r = report(service, s)
    r["quality_assessments"][1].update(outcome="issues", finding_ids=[fid])
    assert_rejected(service, "submit_review", s, "quality_dimension_mismatch", report=r)
    s = raw(service, "verify", s, verification=verification(service, s, fid, outcome="dismissed"))
    r = report(service, s)
    r["quality_assessments"][0].update(outcome="issues", finding_ids=[fid])
    assert_rejected(service, "submit_review", s, "quality_finding_missing", report=r)
    # A fresh issue judgment reopens its exact previously dismissed record.
    s = raw(service, "submit_review", s, report=report(service, s, [finding(service, s)]))
    assert s["last_operation"]["result"]["finding_ids"] == [fid]
    assert stored(service, s)["findings"][fid]["status"] == "open"


@pytest.mark.parametrize("severity", ["warning", "suggestion"])
def test_all_specialized_severities_block_acceptance_even_without_severity_blockers(editorial, severity):
    service, _, source = editorial
    s, fid = with_issue(service, source, severity)
    s = audit(service, read_all(service, s))
    assert s["quality"]["review_complete"] and s["quality"]["pending"] == 1
    assert not s["can_finalize"] and not s["quality"]["ready"] and not s["readiness"]["ready"]
    assert_rejected(service, "finalize", s, "incomplete_review", name="不可通过", expected_manuscript_sha256=s["manuscript_sha256"])
    assert_rejected(service, "verify", s, "quality_change_missing", verification=verification(service, s, fid))
    s = raw(service, "verify", s, verification=verification(service, s, fid, outcome="dismissed"))
    assert s["quality"]["ready"] and s["can_finalize"]


def test_deferred_specialized_issues_can_be_saved_but_never_pass(editorial):
    service, _, source = editorial
    s, fid = with_issue(service, source)
    s = audit(service, read_all(service, s))
    s = raw(service, "verify", s, verification=verification(service, s, fid, outcome="deferred"))
    assert s["can_finalize"] and not s["quality"]["ready"] and s["quality"]["deferred"] == 1
    s = freeze(service, s)
    assert not s["readiness"]["ready"] and not s["quality"]["ready"]
    exported = json.loads(service.export(s["edition_id"], "json")[0])
    assert exported["report"]["quality"] == s["quality"]
    assert "专项验收尚未通过" in service.export(s["edition_id"], "report")[0].decode()


@pytest.mark.parametrize("bad,code", [("no_goals", "quality_goals_missing"), ("wrong_goal", "quality_goals_missing"),
                                      ("duplicate_goals", "quality_goals_missing"), ("no_preservation", "quality_preservation_missing")])
def test_patch_contract_requires_matching_goals_and_preservation(editorial, bad, code):
    service, _, source = editorial
    s, fid = with_issue(service, source)
    p = patch(service, s, fid)
    if bad == "no_goals": p.pop("goals")
    elif bad == "wrong_goal": p["goals"][0]["dimension"] = "rhythm"
    elif bad == "duplicate_goals": p["goals"] *= 2
    else: p.pop("preservation")
    assert_rejected(service, "submit_patch", s, code, patch=p)


@pytest.mark.parametrize("bad,code", [("missing", "quality_verification_missing"), ("dimensions", "quality_verification_missing"),
                                      ("not_improved", "quality_regression"), ("failed_preservation", "quality_regression")])
def test_patch_verification_rejects_unreviewed_or_harmful_changes(editorial, bad, code):
    service, _, source = editorial
    s, fid = with_issue(service, source)
    s = raw(service, "submit_patch", s, patch=patch(service, s, fid))
    pid = s["last_operation"]["result"]["patch_id"]
    s = raw(service, "apply", s, patch_ids=[pid], expected_manuscript_sha256=s["manuscript_sha256"])
    s = raw(service, "run_checks", s)
    v = verification(service, s, fid, pid)
    if bad == "missing": v.pop("patch_assessments")
    elif bad == "dimensions": v["patch_assessments"][0]["dimensions"] = []
    elif bad == "not_improved": v["patch_assessments"][0]["outcome"] = "not_improved"
    else: v["patch_assessments"][0]["preservation"] = "failed"
    assert_rejected(service, "verify", s, code, verification=v)
    if bad in {"not_improved", "failed_preservation"}:
        v["outcome"] = "open"
        s = raw(service, "verify", s, verification=v)
        assert s["coverage"]["verified_patches"] == 0
        assert not s["quality"]["ready"] and not s["can_finalize"]


def test_full_quality_lifecycle_idempotency_invalidation_and_frozen_report(editorial):
    service, _, source = editorial
    s, fid = with_issue(service, source, quality_dimensions=list(DIMENSIONS), continuity_mode="tracked")
    s = raw(service, "submit_patch", s, patch=patch(service, s, fid))
    pid = s["last_operation"]["result"]["patch_id"]
    s = raw(service, "apply", s, patch_ids=[pid], expected_manuscript_sha256=s["manuscript_sha256"])
    assert not s["quality"]["review_complete"] and s["coverage"]["reviewed_paragraphs"] == 0
    assert all(not r["current"] for r in service.records(s["id"], "reviews")["items"])
    s = raw(service, "run_checks", s)
    s = raw(service, "verify", s, verification=verification(service, s, fid, pid))
    assert not s["quality"]["ready"]  # Patches alone do not constitute reading coverage.
    s = read_all(service, s)
    s = write(service, "submit_story", s, update={"manuscript_sha256": s["manuscript_sha256"],
        "chapter_reviews": [{"unit_id": "u1", "summary": "协议夹具：逐章核对，无额外账本记录。",
                             "evidence": [evidence(service, s)]}]})
    s = audit(service, s)
    assert s["quality"]["ready"] and s["readiness"]["ready"] and s["can_finalize"]
    # Repeating an identical intent must not duplicate records or reopen issues.
    request = {"expected_revision": s["revision"], "request_id": uuid.uuid4().hex, "report": report(service, s)}
    next_s = service.submit_review(s["id"], request)
    assert service.submit_review(s["id"], request) == next_s
    s = freeze(service, next_s)
    exported = json.loads(service.export(s["edition_id"], "json")[0])
    assert exported["report"]["quality"]["ready"] and len(exported["report"]["quality"]["dimensions"]) == 8
    assert exported["report"]["patches"][pid]["quality_assessment"]["preservation"] == "passed"
    assert service.get(s["id"])["quality"] == s["quality"]


def test_legacy_reports_stay_usable_without_claiming_specialized_acceptance(editorial):
    service, _, source = editorial
    s = create(service, source, unit_ids=["u1"])
    state = stored(service, s)
    state["profile"].pop("quality_dimensions")
    service.store.put("editorial", state)
    s = service.get(s["id"])
    s = raw(service, "run_checks", s)
    s = raw(service, "submit_review", s, report=report_for(service, s))
    s = audit(service, s)
    assert s["can_finalize"] and not s["quality"]["ready"] and s["quality"]["mode"] == "legacy"
    s = freeze(service, s)
    assert service.get(s["id"])["quality"]["mode"] == "legacy"


def test_findings_filters_cursor_binding_and_report_history(editorial):
    service, _, source = editorial
    s = create(service, source)
    fs = [finding(service, s, paragraph=i % 3) | {"message": f"检索词 样本 {i}"} for i in range(25)]
    s = raw(service, "submit_review", s, report=report(service, s, fs))
    first = service.records(s["id"], limit=20, unit_id="u1", category="prose", status="open", query="检索词")
    assert first["total"] == 25 and first["offset"] == 0
    last = service.records(s["id"], cursor=first["next_cursor"], limit=20, unit_id="u1", category="prose", status="open", query="检索词")
    assert last["offset"] == 20 and len(last["items"]) == 5
    with pytest.raises(EditorialError):
        service.records(s["id"], cursor=first["next_cursor"], category="prose", query="不同条件")
    assert not service.records(s["id"], unit_id="u2")["items"]
    s = raw(service, "submit_review", s, report=report(service, s))
    reviews = service.records(s["id"], "reviews")["items"]
    assert reviews[0]["current"] and not reviews[1]["current"]


def test_findings_dimension_filter_paginates_and_binds_cursor(editorial):
    service, _, source = editorial
    s = create(service, source, quality_dimensions=["precision", "rhythm"])
    fs = [finding(service, s, dimension="precision") | {"message": f"指代 样本 {i}"} for i in range(21)]
    fs.append(finding(service, s, dimension="rhythm"))
    s = raw(service, "submit_review", s, report=report(service, s, fs))
    first = service.records(s["id"], dimension="precision", limit=20)
    last = service.records(s["id"], dimension="precision", cursor=first["next_cursor"], limit=20)
    assert first["total"] == last["total"] == 21
    assert len(first["items"]) == 20 and len(last["items"]) == 1
    assert len({f["id"] for f in first["items"] + last["items"]}) == 21
    assert service.records(s["id"], dimension="rhythm")["total"] == 1
    assert service.records(s["id"], dimension="precision", category="dialogue")["total"] == 0
    for kwargs in ({"dimension": "rhythm", "cursor": first["next_cursor"]},
                   {"kind": "patches", "dimension": "precision"}, {"dimension": "unknown"}):
        with pytest.raises(EditorialError):
            service.records(s["id"], **kwargs)


def test_same_chapter_batch_changes_revision_once_and_stale_sibling_is_rejected(editorial):
    service, _, source = editorial
    s = create(service, source, unit_ids=["u1"])
    s = raw(service, "submit_review", s, report=report(service, s,
        [finding(service, s, paragraph=i) for i in range(3)]))
    ids = s["last_operation"]["result"]["finding_ids"]
    patches = []
    for fid in ids:
        p = patch(service, s, fid)
        p["after"] = p["before"] + "门外传来雨声。"
        s = raw(service, "submit_patch", s, patch=p)
        patches.append(s["last_operation"]["result"]["patch_id"])
    before = stored(service, s)
    s = raw(service, "apply", s, patch_ids=patches[:2], expected_manuscript_sha256=s["manuscript_sha256"])
    after = stored(service, s)
    assert after["working"][0]["revision"] == before["working"][0]["revision"] + 1
    assert all(after["patches"][pid]["status"] == "applied" for pid in patches[:2])
    assert s["coverage"]["applied_patches"] == 2 and s["coverage"]["verified_patches"] == 0
    assert not s["quality"]["ready"]
    with pytest.raises(EditorialError, match="过期"):
        raw(service, "apply", s, patch_ids=patches[2:], expected_manuscript_sha256=s["manuscript_sha256"])
    assert stored(service, s) == after


def unit(texts, identifier="u1"):
    return {"id": identifier, "title": identifier, "revision": 1,
            "paragraphs": [{"id": f"p{i}", "text": t} for i, t in enumerate(texts)]}


def test_pattern_positive_candidates_have_real_unicode_anchors_and_deterministic_results():
    base = "𠮷先生翻到旧巡查簿的末页，把灯移到窗边，对照纸上的签名和日期，直到走廊里的脚步声远去。"
    units = [unit([base, "中间记录。", base.replace("窗边", "门边")]),
             unit([base.replace("窗边", "桌边"), "收起账簿。"], "u2")]
    result, stats = candidates(units)
    assert "prose.chapter_template" in {f["rule_id"] for f in result}
    assert candidates(units) == (result, stats)
    for f in result:
        assert f["severity"] == "suggestion" and "不自动删改" in f["message"]
        for a in f["evidence"]:
            u = next(u for u in units if u["id"] == a["unit_id"])
            p = next(p for p in u["paragraphs"] if p["id"] == a["paragraph_id"])
            assert a == anchor_for(u, p, p["text"][:160])
    interior, _ = candidates([unit(["开场。", base, base.replace("窗边", "门边"), "结束。"])])
    assert "prose.near_duplicate" in {f["rule_id"] for f in interior}


def test_sentence_and_density_candidates_need_recurrence_not_single_usage():
    sentence = "𠮷先生把封口朝上，等门外那人先开口"
    repeated, _ = candidates([unit([f"{i}。{sentence}。" for i in range(3)])])
    assert any(f["rule_id"] == "prose.repeated_sentence" and f["occurrences"] == 3 for f in repeated)
    density, _ = candidates([unit([f"不是第{i}声雨响，而是门外有人。" for i in range(3)])])
    assert any(f["rule_id"] == "prose.pattern_density" for f in density)
    # Multiple punctuation variants in ONE paragraph must not count as three locations.
    clean, _ = candidates([unit([sentence + "。" + sentence.replace("，", "、") + "！" + sentence.replace("，", " ") + "？",
                                "不是大雨，而是水管漏了。", "她说：‘这说明门还没有关。’"])])
    assert clean == []


def test_scan_evidence_points_to_the_match_even_after_long_prefixes():
    repeated = "𠮷先生把封口朝上，等门外那人先开口"
    units = [unit([f"{i}" + "背景" * 100 + "。不是雨声，而是脚步。" + repeated + "。" for i in range(3)])]
    findings, _ = candidates(units)
    density = next(f for f in findings if f["rule_id"] == "prose.pattern_density")
    sentence = next(f for f in findings if f["rule_id"] == "prose.repeated_sentence" and "𠮷" in f["message"])
    for f in (density, sentence):
        for a in f["evidence"]:
            text = next(p["text"] for p in units[0]["paragraphs"] if p["id"] == a["paragraph_id"])
            assert a["start"] > 160 and text[a["start"]:a["end"]] == a["quote"]
    assert sentence["evidence"][0]["quote"] == repeated


def test_pattern_retrieval_has_explicit_work_bounds():
    base = "𠮷先生把登记簿摊在木桌上，核对姓名和住址，随后收起印章，窗外有人敲了三下门。"
    texts = [base + str(i) for i in range(200)] + ["长" * 1300]
    _, stats = candidates([unit(texts)])
    assert stats["eligible_paragraphs"] == 200 and stats["long_paragraphs_skipped"] == 1
    assert 0 < stats["comparisons"] <= 8 * 200
    assert stats["max_postings_per_shingle"] == 40 and stats["max_normalized_characters"] == 1200
