"""Read-only, reproducible audit of an editorial snapshot, including frozen work.

Replaying text operations proves provenance, never that an editor understood prose.
No coverage, dispositions, editions or production records are written by this module.
"""
import hashlib
import io
import json
import zipfile
from collections import Counter, defaultdict
from copy import deepcopy

from .editorial_checks import RULESET_VERSION, RUBRIC_VERSION, scan
from .editorial_export import FORMATS, verify_epub
from .editorial_text import chunks, manifest, manuscript_hash, text_hash, validate_anchor
from .rewriting import fingerprint

AUDIT_VERSION = "editorial-integrity-1"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def anchors(value):
    if isinstance(value, dict):
        if {"unit_id", "paragraph_id", "paragraph_sha256", "quote", "start", "end"} <= value.keys():
            yield value
        else:
            for child in value.values():
                yield from anchors(child)
    elif isinstance(value, list):
        for child in value:
            yield from anchors(child)


def audit_snapshot(session, release, source_units, current_summary, edition=None, exports=None, export_manifest=None, export_record_hashes=None):
    """Audit one owned snapshot; callers supply authorized source and export objects."""
    s = session
    checks, gaps, snapshots, snapshot_hashes = [], [], {}, {}
    stats = Counter()

    def check(identifier, operation):
        try:
            detail = operation()
            checks.append({"id": identifier, "status": "passed", "detail": detail})
        except (ValueError, KeyError, TypeError, IndexError, zipfile.BadZipFile) as exc:
            checks.append({"id": identifier, "status": "failed", "detail": str(exc)})

    def identity():
        units = s["working"]
        ids = [u["id"] for u in units]
        scope = s["profile"]["unit_ids"]
        require(bool(ids) and len(ids) == len(set(ids)), "正文为空或章节编号重复")
        require(bool(scope) and scope == [i for i in ids if i in scope], "审稿范围重复、缺失或顺序不符")
        for u in units:
            pids = [p["id"] for p in u["paragraphs"]]
            require(bool(pids) and len(pids) == len(set(pids)), f"{u['id']} 段落为空或编号重复")
            require(all(p["text"].strip() for p in u["paragraphs"]), f"{u['id']} 含空段落")
        require(manuscript_hash(units) == s["manuscript_sha256"], "正文整体指纹不一致")
        require(manifest(units) == s["working_manifest"], "正文逐段清单不一致")
        require(manifest(s["baseline"]) == s["baseline_manifest"], "基线逐段清单不一致")
        return {"units": len(ids), "paragraphs": sum(len(u["paragraphs"]) for u in units)}

    def source():
        require(fingerprint(release) == s["source_release_sha256"], "冻结来源对象指纹不一致")
        normalized = deepcopy(source_units)
        for u in normalized:
            u["revision"] = 1
        require(normalized == s["baseline"], "基线未逐段对应所声明的冻结来源")
        return {"source_edition_id": s["source_edition_id"], "source_release_sha256": s["source_release_sha256"]}

    def validate(value, state):
        for a in anchors(value):
            require(a["start"] >= 0 and a["end"] > a["start"] and len(a["quote"]) == a["end"] - a["start"], "证据码点区间不完整")
            validate_anchor(state, a, working_only=True)
            stats["validated_anchors"] += 1

    def replay():
        state = {"working": deepcopy(s["baseline"]), "baseline": s["baseline"], "profile": s["profile"]}
        snapshots[1] = deepcopy(state)
        snapshot_hashes[1] = manuscript_hash(state["working"])
        groups = defaultdict(list)
        for p in s["patches"].values():
            if p["status"] == "applied":
                groups[p["applied_manuscript_revision"]].append(p)
        require(sorted(groups) == list(range(2, s["manuscript_revision"] + 1)), "补丁批次与正文修订链不连续")
        for revision, group in sorted(groups.items()):
            locations, changes = set(), []
            for p in group:
                location = (p["anchor"]["unit_id"], p["anchor"]["paragraph_id"])
                require(location not in locations, "同一批次重复修改同段")
                locations.add(location)
                validate([p["anchor"], p["evidence"]], state)
                unit, paragraph = validate_anchor(state, p["anchor"], True)
                require(paragraph["text"] == p["before"], f"{p['id']} 原段不能接上补丁链")
                require(text_hash(p["before"]) == p["before_sha256"] and text_hash(p["after"]) == p["after_sha256"], f"{p['id']} 改前改后哈希不一致")
                require(bool(p["after"].strip()) and p["after"] != p["before"] and not any(c in p["after"] for c in "\r\n"), "补丁不再是非空单段替换")
                require(bool(p["finding_ids"]) and set(p["finding_ids"]) <= s["findings"].keys(), "补丁缺少关联问题")
                changes.append((unit, paragraph, p))
            for _, paragraph, p in changes:
                paragraph["text"] = p["after"]
            for unit in state["working"]:
                if any(uid == unit["id"] for uid, _ in locations):
                    unit["revision"] += 1
            snapshots[revision] = deepcopy(state)
            snapshot_hashes[revision] = manuscript_hash(state["working"])
        require(state["working"] == s["working"], "回放结果与当前正文或章节修订不一致")
        return {"applied_patches": sum(map(len, groups.values())), "batches": len(groups), "final_revision": s["manuscript_revision"]}

    def review_evidence():
        count = 0
        block_cache = {}
        for record in s["reviews"]:
            state = snapshots[record["manuscript_revision"]]
            r = record["report"]
            require(r["manuscript_sha256"] == snapshot_hashes[record["manuscript_revision"]], f"审读 {record['id']} 整稿指纹不符")
            validate(r, state)
            if r["kind"] == "chunk":
                rev = record["manuscript_revision"]
                if rev not in block_cache:
                    block_cache[rev] = {b["id"]: b for b in chunks(state)}
                b = block_cache[rev][r["chunk_id"]]
                require(sorted(r["reviewed_paragraph_ids"]) == sorted({p["id"] for p in b["paragraphs"]}), "分块段落覆盖不完整")
                require(sorted(r["categories"]) == sorted(s["profile"]["categories"]), "分块审读类别不完整")
                for a in r["evidence"] + [a for q in r.get("quality_assessments", []) for a in q["evidence"]]:
                    require(a["unit_id"] == b["unit_id"] and any(p["id"] == a["paragraph_id"] and p["start"] <= a["start"] < a["end"] <= p["end"] for p in b["paragraphs"]), "分块证据越界")
            elif r["kind"] == "audit":
                expected = {u["id"]: u["revision"] for u in state["working"] if u["id"] in s["profile"]["unit_ids"]}
                require(r["unit_revisions"] == expected and set(r["chapter_summaries"]) == set(expected) and {a["unit_id"] for a in r["evidence"]} == set(expected), "跨章审查范围不完整")
            if r["kind"] != "findings" and r.get("quality_assessments"):
                dimensions = [a["dimension"] for a in r["quality_assessments"]]
                require(sorted(dimensions) == sorted(s["profile"].get("quality_dimensions", [])), "审读专项覆盖不完整")
            count += 1
        return {"reports": count, "meaning": "验证引文与范围绑定，不重新授予文学审读覆盖"}

    def verifications():
        latest = {}
        for record in s["verifications"]:
            state = snapshots[record["manuscript_revision"]]
            v = record["verification"]
            require(v["manuscript_sha256"] == snapshot_hashes[record["manuscript_revision"]], "复核整稿指纹不符")
            validate(v, state)
            locations = {(a["unit_id"], a["paragraph_id"]) for a in v["evidence"]}
            for fid in v["finding_ids"]:
                require(fid in s["findings"], "复核引用不存在的问题")
                # Agent findings are immutable observations; rule findings may be
                # refreshed by a later scan and cannot be projected into history.
                f = s["findings"][fid]
                if f["origin"] == "agent":
                    require({(a["unit_id"], a["paragraph_id"]) for a in f["evidence"]} <= locations, "跨章问题复核遗漏关联位置")
            for pid in v["patch_ids"]:
                p = s["patches"][pid]
                require(p["applied_manuscript_revision"] <= record["manuscript_revision"], "复核早于补丁应用")
                require((p["anchor"]["unit_id"], p["anchor"]["paragraph_id"]) in locations and set(p["finding_ids"]) <= set(v["finding_ids"]), "补丁复核遗漏当前位置或关联问题")
                latest[pid] = record
        declared = 0
        for p in s["patches"].values():
            if p["status"] != "applied" or p.get("verified_manuscript_revision") != s["manuscript_revision"]:
                continue
            v = latest.get(p["id"])
            require(v is not None and v["manuscript_revision"] == s["manuscript_revision"], "已复核标记缺少当前稿复核记录")
            if s["profile"].get("quality_dimensions") and s["profile"]["depth"] != "scan":
                a = next((a for a in v["verification"]["patch_assessments"] if a["patch_id"] == p["id"]), None)
                require(a and a["outcome"] != "not_improved" and a["preservation"] == "passed", "已复核补丁的改善或保留项未通过")
                require(sorted(a["dimensions"]) == sorted(g["dimension"] for g in p["goals"]), "补丁复核遗漏专项")
            declared += 1
        return {"verification_records": len(s["verifications"]), "current_verified_patches": declared}

    def coverage_claims():
        claimed = (s.get("completion") or {}).get("coverage")
        if claimed is None:
            return {"frozen_coverage": "not_present"}
        records = [r for r in s["reviews"] if r["manuscript_revision"] == s["manuscript_revision"] and r.get("rubric_version") == s["rubric_version"]]
        reviewed = {r["report"]["chunk_id"] for r in records if r["report"]["kind"] == "chunk"}
        audit = any(r["report"]["kind"] == "audit" and r["knowledge_revision"] == s["knowledge_revision"] for r in records)
        blocks, paragraph_blocks = chunks(s), defaultdict(set)
        require(reviewed <= {b["id"] for b in blocks}, "覆盖声明引用不存在的分块")
        for b in blocks:
            for p in b["paragraphs"]:
                paragraph_blocks[(b["unit_id"], p["id"])].add(b["id"])
        last_scan = s["scan_runs"][-1] if s["scan_runs"] else None
        scanned = bool(last_scan and last_scan["manuscript_revision"] == s["manuscript_revision"] and
                       last_scan["knowledge_revision"] == s["knowledge_revision"] and last_scan["ruleset_version"] == s["ruleset_version"])
        if scanned:
            require(last_scan["manuscript_sha256"] == s["manuscript_sha256"] and last_scan["unit_ids"] == s["profile"]["unit_ids"] and last_scan["paragraph_count"] == len(paragraph_blocks), "旧扫描覆盖声明与实际正文不同")
        expected = {"total_units": len(s["working"]), "selected_units": len(s["profile"]["unit_ids"]),
                    "total_chunks": len(blocks), "reviewed_chunks": len(reviewed),
                    "total_paragraphs": len(paragraph_blocks), "scanned_paragraphs": len(paragraph_blocks) if scanned else 0,
                    "reviewed_paragraphs": sum(ids <= reviewed for ids in paragraph_blocks.values()),
                    "audit_units": len(s["profile"]["unit_ids"]) if audit else 0,
                    "applied_patches": sum(p["status"] == "applied" for p in s["patches"].values()),
                    "verified_patches": sum(p["status"] == "applied" and p.get("verified_manuscript_revision") == s["manuscript_revision"] for p in s["patches"].values())}
        for key, value in expected.items():
            require(claimed[key] == value, f"冻结覆盖统计 {key} 与实际记录不同")
        if s["profile"]["depth"] == "full":
            require(claimed["required_chunks"] == len(blocks) and claimed["missing_chunk_ids"] == sorted({b["id"] for b in blocks} - reviewed), "全文必读范围不一致")
        if edition is not None:
            require(edition["report"]["coverage"] == claimed and edition["readiness"] == s["completion"]["readiness"], "冻结版与会话验收快照不同")
        return expected

    def ledger_evidence():
        for f in s["facts"].values():
            validate(f["evidence"], snapshots[f["manuscript_revision"]])
        story = s.get("story", {})
        for kind in ("entities", "relations", "knowledge"):
            for record in story.get(kind, {}).values():
                validate(record, snapshots[record["manuscript_revision"]])
        for r in story.get("reviews", []):
            validate(r["evidence"], snapshots[r["manuscript_revision"]])
        return {"facts": len(s["facts"]), "story_reviews": len(story.get("reviews", []))}

    def frozen_exports():
        require(edition["id"] == s["edition_id"] and edition["review_id"] == s["id"] and
                edition["source_project_id"] == s["source_project_id"] and edition["source_edition_id"] == s["source_edition_id"] and
                edition["edition_state"] == "frozen", "冻结版身份或来源链标识不一致")
        require(edition["manuscript"] == s["working"] and edition["manuscript_sha256"] == s["manuscript_sha256"], "冻结版与会话正文不同")
        require(edition["profile"] == s["profile"] and edition["source_release_sha256"] == s["source_release_sha256"], "冻结约定或来源不同")
        require(set(exports) == set(FORMATS) == set(export_manifest), "导出格式不完整")
        for fmt, body in exports.items():
            meta = export_manifest[fmt]
            require(hashlib.sha256(body).hexdigest() == meta["sha256"] and len(body) == meta["bytes"], f"{fmt} 实际文件与清单不一致")
            require(not export_record_hashes or export_record_hashes[fmt] == meta["sha256"], f"{fmt} 导出记录与总清单哈希不一致")
        require(json.loads(exports["json"]) == edition, "JSON 导出未准确对应冻结对象")
        for key in ("findings", "facts", "constraints", "patches", "reviews", "scan_runs", "verifications", "baseline_manifest", "working_manifest"):
            require(edition["report"][key] == s[key], f"冻结版 {key} 与会话记录不同")
        require(json.loads(exports["patches"]) == edition["report"]["patches"], "修订对照导出不一致")
        for fmt in ("txt", "md"):
            parts = [("# " if fmt == "md" else "") + edition["name"]]
            for unit in edition["manuscript"]:
                parts += [("## " if fmt == "md" else "") + unit["title"], *[p["text"] for p in unit["paragraphs"]]]
            require(exports[fmt].decode("utf-8-sig") == "\n\n".join(parts), f"{fmt} 标题、顺序或正文不一致")
        verify_epub(exports["epub"], edition["manuscript"])
        with zipfile.ZipFile(io.BytesIO(exports["zip"])) as archive:
            inner = {k: v for k, v in export_manifest.items() if k != "zip"}
            names = [v["filename"] for v in inner.values()] + ["manifest.json"]
            require(sorted(archive.namelist()) == sorted(names), "ZIP 文件集合不一致")
            require(json.loads(archive.read("manifest.json")) == inner, "ZIP 内外清单不同")
            for fmt, meta in inner.items():
                require(archive.read(meta["filename"]) == exports[fmt], f"ZIP 内 {fmt} 与单独导出不同")
        return {"formats": list(FORMATS), "epub_spine_and_paragraphs": "passed", "txt_md_exact": "passed"}

    check("text_identity", identity)
    check("source_lineage", source)
    check("patch_replay", replay)
    check("review_evidence", review_evidence)
    check("verification_evidence", verifications)
    check("coverage_claims", coverage_claims)
    if s["facts"] or any(s.get("story", {}).get(k) for k in ("entities", "relations", "knowledge", "reviews")):
        check("ledger_evidence", ledger_evidence)
    else:
        checks.append({"id": "ledger_evidence", "status": "not_applicable", "detail": "未登记事实或故事记录，不能视为已核验通过"})
    if edition is not None:
        check("frozen_exports", frozen_exports)
    else:
        checks.append({"id": "frozen_exports", "status": "not_applicable", "detail": "尚无冻结版"})
    fresh = scan(s)
    rule_counts = Counter(f["rule_id"] for f in fresh["findings"])
    rule_units = {rule: sorted({a["unit_id"] for f in fresh["findings"] if f["rule_id"] == rule for a in f["evidence"]}) for rule in rule_counts}
    story = current_summary["story_coverage"]
    if story["mode"] != "tracked":
        gaps.append({"code": "manual_continuity", "message": "沿用人工连续性模式，不能声称结构化人物、关系与知情已完整复核"})
    if story["missing_unit_ids"]:
        gaps.append({"code": "story_coverage_missing", "message": "逐章故事核对缺失", "unit_ids": story["missing_unit_ids"]})
    if not s["facts"]:
        gaps.append({"code": "facts_unrecorded", "message": "未登记结构化事实；报告中的金额、日期与知情解释不能由程序重算"})
    if not s["constraints"]:
        gaps.append({"code": "constraints_unrecorded", "message": "未登记计算约束；本次扫描不提供金额或日期算式通过结论"})
    if s["ruleset_version"] != RULESET_VERSION:
        gaps.append({"code": "ruleset_changed", "message": "本次已按新规则独立重扫；冻结历史结论保持原样", "stored": s["ruleset_version"], "current": RULESET_VERSION})
    selected = [u for u in s["working"] if u["id"] in s["profile"]["unit_ids"]]
    passed = all(c["status"] != "failed" for c in checks)
    return {"audit_version": AUDIT_VERSION, "review_id": s["id"], "review_revision": s["revision"],
            "edition_id": s["edition_id"], "manuscript_sha256": s["manuscript_sha256"],
            "ruleset_version": RULESET_VERSION, "rubric_version": RUBRIC_VERSION,
            "scope": {"total_units": len(s["working"]), "selected_units": len(selected),
                      "whole_book": len(selected) == len(s["working"]), "chunks": len(chunks(s)),
                      "paragraphs": fresh["paragraph_count"], "characters": fresh["character_count"]},
            "integrity_passed": passed, "checks": checks, "evidence_statistics": dict(stats),
            "fresh_scan": {"ruleset_version": fresh["ruleset_version"], "candidate_count": len(fresh["findings"]),
                           "by_rule": dict(rule_counts), "units_by_rule": rule_units,
                           "constraints": fresh["constraints"], "pattern_scope": fresh["pattern_scope"]},
            "declared_completion": deepcopy(s.get("completion")),
            "current_workflow": {k: current_summary[k] for k in ("coverage", "story_coverage", "quality", "readiness")},
            "structured_records": {"facts": len(s["facts"]), "constraints": len(s["constraints"]),
                                   **{k: story[k]["total"] for k in ("entities", "relations", "knowledge")}},
            "acceptance_gaps": gaps, "literary_reread_performed": False,
            "limitations": ["本工具验证全量数据、证据和版本契约，不判断小说是否好看或证据是否支持文学解释。",
                            "规则候选须结合正文处置；未登记事实或故事记录不等于小说中没有对应事件。",
                            "只读审计不写入新覆盖、不改变问题状态、不替冻结版追加通过结论。"]}
