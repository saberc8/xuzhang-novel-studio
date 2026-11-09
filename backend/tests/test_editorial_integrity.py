"""Real frozen fixtures: audits detect damage without changing any workflow state."""
import base64
from copy import deepcopy

import pytest

from backend.app.store import user_scope
from test_editorial import (editorial, workspace, create, write, stored, evidence,
                            read_all, audit, freeze, add_issue, propose)


def completed(service, source):
    s = create(service, source)
    s = write(service, "run_checks", s)
    s, fid = add_issue(service, s)
    s = propose(service, s, fid)
    pid = s["last_operation"]["result"]["patch_id"]
    s = write(service, "apply", s, patch_ids=[pid], expected_manuscript_sha256=s["manuscript_sha256"])
    s = write(service, "run_checks", s)
    s = write(service, "verify", s, verification={"manuscript_sha256": s["manuscript_sha256"],
        "finding_ids": [fid], "patch_ids": [pid], "outcome": "resolved",
        "reason": "对照明确年份后修正跨度，保留动作和视角。", "evidence": [evidence(service, s)]})
    return freeze(service, audit(service, read_all(service, s)))


def test_frozen_audit_replays_exports_and_does_not_grant_quality(editorial):
    service, _, source = editorial
    s = completed(service, source)
    before = deepcopy(stored(service, s))
    edition = deepcopy(service.store.get("editorial_edition", s["edition_id"]))
    result = service.integrity(s["id"])
    assert result["integrity_passed"], result["checks"]
    assert result["scope"] == {"total_units": 2, "selected_units": 2, "whole_book": True,
                               "chunks": 2, "paragraphs": 5,
                               "characters": sum(u["characters"] for u in s["units"])}
    assert result["evidence_statistics"]["validated_anchors"] > 0
    assert not result["literary_reread_performed"]
    assert {g["code"] for g in result["acceptance_gaps"]} >= {"manual_continuity", "facts_unrecorded"}
    assert not result["current_workflow"]["readiness"]["ready"]
    assert service.integrity(s["id"]) == result
    assert stored(service, s) == before
    assert service.store.get("editorial_edition", s["edition_id"]) == edition


@pytest.mark.parametrize("damage,failed_check", [
    ("working_manifest", "text_identity"), ("source_hash", "source_lineage"),
    ("patch_before", "patch_replay"), ("review_quote", "review_evidence"),
    ("coverage", "coverage_claims"), ("export_bytes", "frozen_exports"),
])
def test_audit_finds_independent_integrity_failures(editorial, damage, failed_check):
    service, _, source = editorial
    s = completed(service, source)
    state = stored(service, s)
    if damage == "working_manifest":
        state["working_manifest"][0]["paragraphs"][0]["sha256"] = "0" * 64
    elif damage == "source_hash":
        state["source_release_sha256"] = "0" * 64
    elif damage == "patch_before":
        next(iter(state["patches"].values()))["before_sha256"] = "0" * 64
    elif damage == "review_quote":
        state["reviews"][-1]["report"]["evidence"][0]["quote"] = "伪造的引文"
    elif damage == "coverage":
        state["completion"]["coverage"]["reviewed_paragraphs"] += 1
    else:
        exported = service.store.get("editorial_export", s["edition_id"] + ":txt")
        exported["body"] = base64.b64encode(b"wrong manuscript").decode()
        service.store.put("editorial_export", exported)
    service.store.put("editorial", state)
    result = service.integrity(s["id"])
    assert not result["integrity_passed"]
    assert any(c["id"] == failed_check and c["status"] == "failed" for c in result["checks"]), result["checks"]
    assert stored(service, s) == state


def test_audit_keeps_selected_scope_and_account_boundary(editorial):
    service, _, source = editorial
    s = create(service, source, unit_ids=["u1"])
    before = stored(service, s)
    result = service.integrity(s["id"])
    assert result["integrity_passed"]
    assert result["scope"]["selected_units"] == 1 and not result["scope"]["whole_book"]
    assert result["declared_completion"] is None
    assert any(c["status"] == "not_applicable" for c in result["checks"])
    assert stored(service, s) == before
    with user_scope("2" * 32):
        with pytest.raises(KeyError):
            service.integrity(s["id"])
