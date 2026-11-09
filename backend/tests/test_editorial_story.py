"""Adversarial story-memory cases, plus the real transactional editorial flow."""
import json
import uuid
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from conftest import sign_in
from pydantic import ValidationError

from backend.app.editorial_models import Fact, StoryUpdate, EditorialProfile
from backend.app.editorial_story import update_story, view_story, story_candidates, story_coverage
from backend.app.editorial_text import EditorialError, anchor_for, manuscript_hash
from backend.app.main import create_app
from test_editorial import (editorial, workspace, create, write, stored, evidence, report_for,
                            read_all, audit, freeze, add_issue, propose)


def fixture():
    texts = [
        "沈砚与周宁是师兄弟。码头有一道暗门。周宁此时还不知道这件事。",
        "沈砚把暗门的位置告诉了周宁。周宁这才知道码头的秘密。",
        "周宁承认自己曾用陈舟这个名字。另一位同名的周宁走进屋里。",
    ]
    units = [{"id": f"u{i + 1}", "title": f"第{i + 1}章", "revision": 1,
              "paragraphs": [{"id": "p1", "text": text}]} for i, text in enumerate(texts)]
    s = {"id": "test", "revision": 0, "manuscript_revision": 1, "knowledge_revision": 0,
         "manuscript_sha256": manuscript_hash(units), "working": units, "facts": {},
         "profile": {"unit_ids": ["u1", "u2", "u3"], "continuity_mode": "tracked"}}
    anchors = [anchor_for(u, u["paragraphs"][0]) for u in units]
    s["facts"]["door"] = {**Fact(id="door", statement="码头有一道暗门。", status="confirmed",
                                evidence=[anchors[0]]).model_dump(), "manuscript_revision": 1}
    entities = [
        {"id": "shen", "name": "沈砚", "description": "告诉周宁暗门位置的人物。", "status": "confirmed", "evidence": [anchors[0]]},
        {"id": "zhou", "name": "周宁", "description": "沈砚的师兄弟。", "status": "confirmed", "evidence": [anchors[0]],
         "aliases": [{"name": "陈舟", "evidence": [anchors[2]]}]},
        {"id": "other", "name": "周宁", "description": "第三章出现的另一个同名人物。", "status": "confirmed", "evidence": [anchors[2]]},
    ]
    relations = [{"id": "brothers", "source_id": "shen", "target_id": "zhou", "label": "师兄弟",
                  "explanation": "第一章明确交代。", "from_unit_id": "u1", "status": "confirmed", "evidence": [anchors[0]]}]
    knowledge = [
        {"id": "unaware", "holder_id": "zhou", "fact_id": "door", "state": "unaware", "acquisition": "第一章明确写明尚不知情。",
         "from_unit_id": "u1", "through_unit_id": "u1", "status": "confirmed", "evidence": [anchors[0]]},
        {"id": "knows", "holder_id": "zhou", "fact_id": "door", "state": "knows", "acquisition": "第二章由沈砚告知。",
         "from_unit_id": "u2", "status": "confirmed", "evidence": [anchors[1]]},
    ]
    payload = {"manuscript_sha256": s["manuscript_sha256"], "entities": entities, "relations": relations, "knowledge": knowledge}
    update_story(s, StoryUpdate.model_validate(payload).model_dump(), "now")
    return s, anchors, payload


def change(s, **payload):
    update_story(s, StoryUpdate.model_validate({"manuscript_sha256": s["manuscript_sha256"], **payload}).model_dump(), "later")
    s["revision"] += 1


def test_names_aliases_and_later_evidence_do_not_leak_into_earlier_graph():
    s, _, _ = fixture()
    all_people = view_story(s, "entities")
    assert len(all_people["items"]) == 3  # Same name is not a merge key.
    early = view_story(s, "entities", at_unit_id="u1")
    assert {n["id"] for n in early["items"]} == {"shen", "zhou"}
    assert "陈舟" not in json.dumps(early, ensure_ascii=False)
    assert view_story(s, "entities", at_unit_id="u1", query="陈舟")["total"] == 0
    assert view_story(s, "entities", query="陈舟")["items"][0]["id"] == "zhou"
    assert view_story(s, "knowledge", at_unit_id="u1")["items"][0]["state"] == "unaware"
    assert view_story(s, "knowledge", at_unit_id="u2")["items"][0]["state"] == "knows"
    assert not story_candidates(s)


def test_truth_belief_and_readers_are_distinct_and_overlap_is_only_a_candidate():
    s, anchors, payload = fixture()
    denied = {**payload["relations"][0], "id": "denial", "polarity": "denied", "perspective": "belief", "observer_id": "zhou"}
    change(s, relations=[denied])
    assert not story_candidates(s)
    # Opposing records within one perspective need review, never an automatic error.
    change(s, relations=[{**denied, "perspective": "event", "observer_id": None}])
    candidate = story_candidates(s)[0]
    assert candidate["severity"] == "warning" and candidate["category"] == "relationship"
    # Evidence introduced in chapter 3 is unavailable when reading chapter 1.
    change(s, relations=[{**denied, "evidence": [anchors[2]]}])
    assert view_story(s, "relations", at_unit_id="u1")["total"] == 1
    bad = {**payload["knowledge"][0], "through_unit_id": "u3"}
    change(s, knowledge=[bad])
    assert any(c["category"] == "knowledge" for c in story_candidates(s))


def test_entity_fact_updates_and_manuscript_edits_invalidate_dependencies():
    s, _, payload = fixture()
    change(s, entities=[{**payload["entities"][0], "description": "更新身份解释，关系须重新确认。"}])
    assert not view_story(s)["items"][0]["current"]
    change(s, relations=payload["relations"])
    assert view_story(s)["items"][0]["current"]
    s["facts"]["door"]["status"] = "disputed"
    assert all(not k["current"] for k in view_story(s, "knowledge")["items"])
    assert story_coverage(s)["knowledge"]["confirmed"] == 0
    s["manuscript_revision"] += 1
    assert story_coverage(s)["entities"]["stale"] == 3
    assert not story_candidates(s)


def test_chapter_coverage_requires_known_dependencies_and_is_invalidated():
    s, anchors, payload = fixture()
    review = {"unit_id": "u1", "summary": "核对师兄弟关系以及周宁尚不知情的状态。", "evidence": [anchors[0]]}
    with pytest.raises(EditorialError, match="遗漏"):
        change(s, chapter_reviews=[review])
    review.update(entity_ids=["shen", "zhou"], relation_ids=["brothers"], knowledge_ids=["unaware"])
    change(s, chapter_reviews=[review])
    assert story_coverage(s)["reviewed_units"] == 1
    change(s, entities=[{**payload["entities"][0], "description": "补充身份说明。"}])
    assert story_coverage(s)["reviewed_units"] == 0
    with pytest.raises(EditorialError, match="待更新"):
        change(s, chapter_reviews=[review])


def test_unchanged_upserts_preserve_dependencies_and_chapter_coverage():
    s, anchors, payload = fixture()
    change(s, chapter_reviews=[{
        "unit_id": "u1", "summary": "核对已登记的师兄弟关系和未知暗门的状态。",
        "entity_ids": ["shen", "zhou"], "relation_ids": ["brothers"], "knowledge_ids": ["unaware"],
        "evidence": [anchors[0]],
    }])
    before = deepcopy(s)
    # Resuming an agent can submit the same content using a fresh request ID.
    change(s, entities=payload["entities"])
    assert s["knowledge_revision"] == before["knowledge_revision"]
    assert s["story"]["entities"] == before["story"]["entities"]
    assert view_story(s)["items"][0]["current"]
    change(s, relations=payload["relations"], knowledge=payload["knowledge"])
    assert s["knowledge_revision"] == before["knowledge_revision"]
    assert story_coverage(s)["reviewed_units"] == 1
    assert len(s["story"]["changes"]) == len(before["story"]["changes"]) + 2


def test_same_relation_payload_after_dependency_change_is_a_real_update():
    s, _, payload = fixture()
    change(s, entities=[{**payload["entities"][0], "description": "身份说明有实质变化。"}])
    revision = s["knowledge_revision"]
    assert not view_story(s)["items"][0]["current"]
    change(s, relations=payload["relations"])
    assert s["knowledge_revision"] == revision + 1
    assert view_story(s)["items"][0]["current"]


def test_graph_pages_are_bounded_cursor_bound_and_read_only():
    s, _, payload = fixture()
    before = deepcopy(s)
    first = view_story(s, "entities", limit=1)
    second = view_story(s, "entities", limit=1, cursor=first["next_cursor"])
    assert len(first["nodes"]) == len(second["nodes"]) == 1
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert s == before
    change(s, entities=[{**payload["entities"][0], "description": "新记录。"}])
    with pytest.raises(EditorialError):
        view_story(s, "entities", limit=1, cursor=first["next_cursor"])
    with pytest.raises(EditorialError):
        view_story(s, "entities", at_unit_id="missing")


@pytest.mark.parametrize("field,value", [("observer_id", None), ("perspective", "event")])
def test_belief_always_has_an_explicit_character_observer(field, value):
    s, _, payload = fixture()
    relation = {**payload["relations"][0], "perspective": "belief", "observer_id": "zhou", field: value}
    with pytest.raises(ValidationError):
        StoryUpdate.model_validate({"manuscript_sha256": s["manuscript_sha256"], "relations": [relation]})


def test_default_and_legacy_profiles_have_explicit_continuity_modes():
    assert EditorialProfile().continuity_mode == "tracked"
    s, _, _ = fixture()
    del s["profile"]["continuity_mode"]
    assert story_coverage(s)["mode"] == "manual"


def test_withdrawals_keep_history_and_chapter_ranges_reject_invalid_bounds():
    s, _, payload = fixture()
    with pytest.raises(EditorialError, match="末章"):
        change(s, relations=[{**payload["relations"][0], "from_unit_id": "u3", "through_unit_id": "u1"}])
    with pytest.raises(EditorialError, match="所选章节"):
        change(s, relations=[{**payload["relations"][0], "through_unit_id": "outside"}])
    change(s, entities=[{**payload["entities"][0], "status": "withdrawn", "description": "撤回先前身份判断，保留证据。"}],
           relations=[{**payload["relations"][0], "status": "withdrawn", "explanation": "身份被撤回，同时撤回此关系。"}])
    assert s["story"]["entities"]["shen"]["status"] == "withdrawn"
    assert story_coverage(s)["relations"]["total"] == 0
    assert len(s["story"]["changes"]) == 2
    assert not story_candidates(s)


def service_payload(service, s):
    a = evidence(service, s)
    unit_id = s["units"][0]["id"]
    return {"manuscript_sha256": s["manuscript_sha256"],
            "entities": [{"id": "reader", "name": "𠮷先生", "description": "翻阅旧巡查记录的人物。", "status": "confirmed", "evidence": [a]},
                         {"id": "record", "kind": "item", "name": "巡查记录", "description": "记载1922年巡查的记录。", "status": "confirmed", "evidence": [a]}],
            "relations": [{"id": "reads", "source_id": "reader", "target_id": "record", "label": "翻阅",
                           "explanation": "正文明确写出翻到旧页。", "status": "confirmed", "from_unit_id": unit_id, "evidence": [a]}]}


def service_reviews(service, s):
    units = stored(service, s)["working"]
    return [{"unit_id": u["id"], "summary": "核对人物和物件的身份；沿用已登记的翻阅关系，未推断新增知情。",
             "entity_ids": ["reader", "record"], "relation_ids": ["reads"], "evidence": [anchor_for(u, u["paragraphs"][0])]}
            for u in units]


def test_transaction_retry_stale_graph_and_atomic_failures(editorial):
    service, _, source = editorial
    s = create(service, source, continuity_mode="tracked")
    payload = service_payload(service, s)
    req = {"expected_revision": s["revision"], "request_id": "story-retry", "update": payload}
    s = service.submit_story(s["id"], req)
    assert service.submit_story(s["id"], req) == s
    assert service.story(s["id"])["items"][0]["current"]
    before = stored(service, s)
    bad = deepcopy(payload)
    bad["entities"][0]["description"] = "本次应全部回滚。"
    bad["relations"][0]["target_id"] = "does-not-exist"
    with pytest.raises(EditorialError):
        write(service, "submit_story", s, update=bad)
    assert stored(service, s) == before
    s, fid = add_issue(service, s)
    s = propose(service, s, fid)
    pid = s["last_operation"]["result"]["patch_id"]
    s = write(service, "apply", s, patch_ids=[pid], expected_manuscript_sha256=s["manuscript_sha256"])
    assert not service.story(s["id"])["items"][0]["current"]
    assert s["story_coverage"]["entities"]["stale"] == 2
    with pytest.raises(EditorialError):
        write(service, "submit_story", s, update=payload)


def test_tracked_finalization_exports_and_http_contract(editorial, tmp_path):
    service, _, source = editorial
    s = create(service, source, continuity_mode="tracked")
    s = write(service, "run_checks", s)
    s = read_all(service, s)
    with pytest.raises(EditorialError, match="人物"):
        audit(service, s)
    s = write(service, "submit_story", s, update=service_payload(service, s))
    s = write(service, "submit_story", s, update={"manuscript_sha256": s["manuscript_sha256"],
                                                "chapter_reviews": service_reviews(service, s)})
    assert s["story_coverage"]["reviewed_units"] == 2
    # Knowledge changes invalidate scans and audits; chapter acknowledgements do not.
    assert not s["can_finalize"]
    s = write(service, "run_checks", s)
    s = audit(service, s)
    s = freeze(service, s)
    exported = json.loads(service.export(s["edition_id"], "json")[0])
    assert exported["report"]["story"]["entities"]["reader"]["name"] == "𠮷先生"
    assert len(exported["report"]["story"]["changes"]) == 2
    assert exported["report"]["story_coverage"]["reviewed_units"] == 2
    with pytest.raises(EditorialError, match="冻结"):
        write(service, "submit_story", s, update=service_payload(service, s))
    app = create_app(tmp_path)
    with TestClient(app) as client:
        sign_in(client)
        response = client.get(f"/api/editorial-reviews/{s['id']}/story?kind=relations&limit=1")
        assert response.status_code == 200 and response.json()["total"] == 1
        assert client.get(f"/api/editorial-reviews/{s['id']}/story?kind=unknown").status_code == 422
        assert client.get("/api/adaptation-guide?section=editorial_story").json()["schema"]["additionalProperties"] is False


def test_unconfirmed_story_candidates_cannot_silently_resolve(editorial):
    service, _, source = editorial
    s = create(service, source, depth="scan")
    payload = service_payload(service, s)
    payload["relations"].append({**payload["relations"][0], "id": "denied", "polarity": "denied"})
    s = write(service, "submit_story", s, update=payload)
    s = write(service, "run_checks", s)
    f = next(f for f in stored(service, s)["findings"].values() if f.get("rule_id") == "story.relationship")
    payload["relations"][1]["status"] = "candidate"
    s = write(service, "submit_story", s, update=payload)
    s = write(service, "run_checks", s)
    assert stored(service, s)["findings"][f["id"]]["status"] == "needs_recheck"
    with pytest.raises(EditorialError, match="尚未"):
        write(service, "verify", s, verification={"manuscript_sha256": s["manuscript_sha256"], "finding_ids": [f["id"]],
              "outcome": "resolved", "reason": "候选消失不能作为解决依据。", "evidence": [evidence(service, s)]})


def test_resumed_identical_knowledge_writes_keep_completed_review_valid(editorial):
    service, _, source = editorial
    s = create(service, source, continuity_mode="tracked")
    a = evidence(service, s)
    facts = [{"id": "year", "statement": "现在是1926年。", "status": "confirmed",
              "value": "1926", "measure": "year", "evidence": [a]}]
    report = {**report_for(service, s), "facts": facts}
    s = write(service, "submit_review", s, report=report)
    payload = service_payload(service, s)
    payload["knowledge"] = [{
        "id": "year-known", "holder_id": "reader", "fact_id": "year", "state": "knows",
        "acquisition": "核对书中当前年份。", "status": "confirmed", "from_unit_id": a["unit_id"], "evidence": [a],
    }]
    s = write(service, "submit_story", s, update=payload)
    reviews = [{**r, "knowledge_ids": ["year-known"]} for r in service_reviews(service, s)]
    s = write(service, "submit_story", s, update={"manuscript_sha256": s["manuscript_sha256"], "chapter_reviews": reviews})
    s = read_all(service, s)
    s = write(service, "run_checks", s)
    s = audit(service, s)
    assert s["can_finalize"]
    before = stored(service, s)
    s = write(service, "submit_review", s, report=report)
    s = write(service, "submit_story", s, update=payload)
    assert stored(service, s)["knowledge_revision"] == before["knowledge_revision"]
    assert s["can_finalize"] and s["story_coverage"]["reviewed_units"] == 2
    assert service.story(s["id"], "knowledge")["items"][0]["confirmed"]
    # A changed fact must still invalidate scan/audit, chapter coverage and knowledge.
    report["facts"][0]["status"] = "disputed"
    s = write(service, "submit_review", s, report=report)
    assert not s["can_finalize"] and s["story_coverage"]["reviewed_units"] == 0
    assert not service.story(s["id"], "knowledge")["items"][0]["current"]


def test_identical_constraint_is_stable_but_changed_interpretation_invalidates(editorial):
    service, _, source = editorial
    s = create(service, source)
    a = evidence(service, s)
    facts = [{"id": key, "statement": description, "status": "confirmed", "value": value,
              "measure": measure, "evidence": [a]}
             for key, description, value, measure in [
                 ("old", "巡查记录年份。", "1922", "year"),
                 ("now", "当前年份。", "1926", "year"),
                 ("gap", "文中写成两年前。", "2", "years")]]
    constraint = {"id": "gap-check", "operation": "years_between", "operand_ids": ["old", "now"],
                  "result_id": "gap", "explanation": "核对明确年份的跨度。"}
    report = {**report_for(service, s), "facts": facts, "constraints": [constraint]}
    s = write(service, "submit_review", s, report=report)
    s = write(service, "run_checks", s)
    revision = stored(service, s)["knowledge_revision"]
    s = write(service, "submit_review", s, report=report)
    assert stored(service, s)["knowledge_revision"] == revision
    assert s["coverage"]["scanned_paragraphs"] == s["coverage"]["total_paragraphs"]
    report["constraints"][0]["explanation"] = "补充说明：需要结合约数与日期复核年份跨度。"
    s = write(service, "submit_review", s, report=report)
    assert stored(service, s)["knowledge_revision"] == revision + 1
    assert s["coverage"]["scanned_paragraphs"] == 0
