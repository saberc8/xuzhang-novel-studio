"""Evidence navigation on late, split, changed and out-of-scope paragraphs."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from conftest import sign_in

from backend.app.editorial_text import EditorialError, anchor_for, encode_cursor
from backend.app.rewriting import fingerprint
from backend.app.main import create_app
from test_editorial import editorial, workspace, create, stored, write, report_for


def long_session(service, source):
    parent = service.store.get("adaptation", source["project_id"])
    # A private source fixture, not a user's novel.
    parent["_release"]["units"][0]["draft"]["paragraphs"] = [
        *[f"第{i + 1}段。人物核对了信封上的日期。" for i in range(55)],
        "桥" * 5998 + "𠮷先生交出铜钥匙。" + "潮" * 6993,
        "末段确认了下一章的约定。",
    ]
    service.store.put("adaptation", parent)
    return create(service, service.source(source["project_id"]))


def test_late_evidence_jumps_to_its_chunk_with_bidirectional_cursors(editorial):
    service, _, source = editorial
    s = long_session(service, source)
    snapshot = stored(service, s)
    unit = snapshot["working"][0]
    a = anchor_for(unit, unit["paragraphs"][50])
    result = service.locate(s["id"], {"anchor": a})
    assert result["location"]["status"] == "exact"
    assert result["offset"] == 2 and len(result["items"]) == 1
    assert a["paragraph_id"] in [p["id"] for p in result["items"][0]["paragraphs"]]
    previous = service.context(s["id"], unit_id=a["unit_id"], cursor=result["previous_cursor"])
    roundtrip = service.context(s["id"], unit_id=a["unit_id"], cursor=previous["next_cursor"])
    assert roundtrip["items"] == result["items"]
    assert result["next_cursor"]
    assert stored(service, s) == snapshot  # Location reads do not grant coverage or change records.


def test_cross_fragment_unicode_evidence_is_bounded_and_keeps_continuation(editorial):
    service, _, source = editorial
    s = long_session(service, source)
    unit = stored(service, s)["working"][0]
    a = anchor_for(unit, unit["paragraphs"][55], "𠮷先生交出铜钥匙。", 5998)
    first = service.locate(s["id"], {"anchor": a})
    second = service.context(s["id"], unit_id=a["unit_id"], cursor=first["next_cursor"])
    assert first["location"]["status"] == "exact"
    assert first["items"][0]["paragraphs"][0]["text"][-2:] == "𠮷先"
    assert second["items"][0]["paragraphs"][0]["text"].startswith("生交出铜钥匙。")
    for response in (first, second):
        block = response["items"][0]
        assert sum(len(p["text"]) for p in block["paragraphs"]) <= 6000
        assert len(block["paragraphs"]) <= 24
    assert service.context(s["id"], unit_id=a["unit_id"], cursor=second["previous_cursor"])["items"] == first["items"]


def test_stale_evidence_locates_shortened_paragraph_without_reanchoring(editorial):
    service, _, source = editorial
    s = long_session(service, source)
    unit = stored(service, s)["working"][0]
    paragraph = unit["paragraphs"][55]
    a = anchor_for(unit, paragraph, paragraph["text"][12500:12510], 12500)
    old = service.locate(s["id"], {"anchor": a})
    report = report_for(service, s, old["items"][0])
    report["findings"] = [{"category": "prose", "severity": "suggestion", "message": "协议夹具：缩短长段验证旧证据定位。",
                           "evidence": [a], "suggested_action": "copyedit"}]
    s = write(service, "submit_review", s, report=report)
    fid = s["last_operation"]["result"]["finding_ids"][0]
    full = anchor_for(unit, paragraph)
    s = write(service, "submit_patch", s, patch={"finding_ids": [fid], "anchor": full, "before": full["quote"],
              "after": "段落已经缩短。", "reason": "隔离测试：验证旧坐标越界时仍能查看同段。", "evidence": [a]})
    s = write(service, "apply", s, patch_ids=[s["last_operation"]["result"]["patch_id"]],
              expected_manuscript_sha256=s["manuscript_sha256"])
    before = stored(service, s)
    current = service.locate(s["id"], {"anchor": a})
    assert current["location"]["status"] == "stale"
    assert current["location"]["located_start"] == len("段落已经缩短。") - 1
    assert current["location"]["start"] == 12500  # Preserve the original coordinate.
    baseline = service.locate(s["id"], {"anchor": a, "source": "baseline"})
    assert baseline["location"]["status"] == "text_matches"
    assert baseline["items"] == old["items"]
    with pytest.raises(EditorialError) as error:
        service.context(s["id"], unit_id=a["unit_id"], cursor=old["previous_cursor"])
    assert error.value.detail["code"] == "cursor_stale"
    assert stored(service, s) == before


def test_same_text_on_new_chapter_revision_does_not_revalidate_old_anchor(editorial):
    service, _, source = editorial
    s = long_session(service, source)
    unit = stored(service, s)["working"][0]
    a = anchor_for(unit, unit["paragraphs"][50])
    service.store.mutate("editorial", s["id"], lambda record: record["working"][0].update(revision=2))
    assert service.locate(s["id"], {"anchor": a})["location"]["status"] == "text_matches"


def test_location_http_schema_scope_and_invalid_anchors(editorial, tmp_path):
    service, _, source = editorial
    s = long_session(service, source)
    unit = stored(service, s)["working"][0]
    a = anchor_for(unit, unit["paragraphs"][50])
    snapshot = stored(service, s)
    with TestClient(create_app(tmp_path)) as client:
        sign_in(client)
        url = f"/api/editorial-reviews/{s['id']}/context/locate"
        assert client.post(url, json={"anchor": a}).json()["location"]["status"] == "exact"
        for override, code in [({"paragraph_id": "missing"}, "evidence_missing"),
                               ({"unit_id": "unselected"}, "outside_scope"),
                               ({"end": a["end"] + 1}, "evidence_mismatch")]:
            response = client.post(url, json={"anchor": {**a, **override}})
            assert response.status_code == 422 and response.json()["detail"]["code"] == code
        assert client.post(url, json={"anchor": a, "source": "unknown"}).status_code == 422
    assert stored(service, s) == snapshot


def test_graph_projection_copies_only_the_page_and_hashes_each_dependency_once(monkeypatch):
    from backend.app import editorial_story as graph
    from test_editorial_story import fixture
    s, _, _ = fixture()
    relation = s["story"]["relations"]["brothers"]
    for i in range(500):
        s["story"]["relations"][f"r{i:03}"] = {**deepcopy(relation), "id": f"r{i:03}"}
    calls = {"copies": 0, "hashes": 0}
    copy, digest = graph.deepcopy, graph.fingerprint

    def counted_copy(value):
        calls["copies"] += 1
        return copy(value)

    def counted_digest(value):
        calls["hashes"] += 1
        return digest(value)

    monkeypatch.setattr(graph, "deepcopy", counted_copy)
    monkeypatch.setattr(graph, "fingerprint", counted_digest)
    result = graph.view_story(s, limit=6)
    assert result["total"] == 501 and len(result["items"]) == 6
    assert calls["copies"] < 20 and calls["hashes"] < 10
    result["nodes"][0]["name"] = "修改响应不能改变账本"
    result["items"][0]["evidence"][0]["quote"] = "独立拷贝"
    assert s["story"]["entities"]["shen"]["name"] == "沈砚"
    assert s["story"]["relations"]["brothers"]["evidence"][0]["quote"] != "独立拷贝"


def test_findings_prioritize_actionable_errors_over_book_scale_scan_noise(editorial):
    service, _, source = editorial
    s = create(service, source)
    state = stored(service, s)
    anchors = [anchor_for(u, u["paragraphs"][0]) for u in state["working"]]

    def finding(identifier, severity, status="open", origin="agent", chapter=0):
        return {"id": identifier, "severity": severity, "status": status, "origin": origin,
                "message": identifier, "category": "prose", "evidence": [anchors[chapter]],
                "suggested_action": "review", "created_manuscript_revision": 1}

    # Persist noise under earlier keys, as JSONB does regardless of insertion.
    records = [finding(f"a{i:03}", "suggestion", origin="rule") for i in range(109)] + [
        finding("z-late-error", "error", chapter=1),
        finding("z-early-error", "error"),
        finding("z-recheck", "warning", status="needs_recheck"),
        finding("z-editor-suggestion", "suggestion"),
        finding("a-deferred", "error", status="deferred"),
        finding("a-resolved", "error", status="resolved"),
    ]
    service.store.mutate("editorial", s["id"], lambda x: x.update(findings={f["id"]: f for f in records}))
    snapshot = stored(service, s)
    first = service.records(s["id"], limit=4)
    assert [f["id"] for f in first["items"]] == [
        "z-early-error", "z-late-error", "z-recheck", "z-editor-suggestion"]
    ids = [f["id"] for f in first["items"]]
    cursor = first["next_cursor"]
    while cursor:
        page = service.records(s["id"], cursor=cursor, limit=4)
        ids.extend(f["id"] for f in page["items"])
        cursor = page["next_cursor"]
    assert len(ids) == len(set(ids)) == len(records)
    assert ids[-2:] == ["a-deferred", "a-resolved"]
    assert stored(service, s) == snapshot
    assert service.records(s["id"], limit=4) == first

    # A deployment changes ordering but must never reinterpret an old offset.
    legacy = encode_cursor(fingerprint([s["id"], "findings", s["revision"]]), 4)
    with pytest.raises(EditorialError) as error:
        service.records(s["id"], cursor=legacy, limit=4)
    assert error.value.detail["code"] == "cursor_stale"
    s = write(service, "run_checks", s)
    with pytest.raises(EditorialError) as error:
        service.records(s["id"], cursor=first["next_cursor"], limit=4)
    assert error.value.detail["code"] == "cursor_stale"
