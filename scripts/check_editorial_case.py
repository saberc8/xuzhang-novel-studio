"""Read-only legacy-bundle verification and scale replay in a temporary DB schema.

The source directory and production database are never modified. Replay assertions
verify text/version mechanics, not the literary correctness of legacy edits.
"""
import argparse
import hashlib
import json
import sys
import tempfile
import time
import uuid
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app.editorial import Editorials
from backend.app.editorial_export import verify_epub
from backend.app.editorial_text import anchor_for, text_hash
from backend.app.rewriting import fingerprint
from backend.app.service import Studio
from backend.app.store import user_scope


def verify_bundle(directory):
    raw = (directory / "original-release.json").read_bytes()
    source = json.loads(raw)
    edits = json.loads((directory / "逐段修订对照.json").read_text())
    revised = json.loads((directory / "长夜归舟-质检精修版.json").read_text())
    metadata = json.loads((directory / "版本与验证记录.json").read_text())
    assert hashlib.sha256(raw).hexdigest() == metadata["source_export_sha256"]
    original = {u["id"]: u for u in source["units"]}
    chapters = {c["id"]: c for c in revised["chapters"]}
    assert list(original) == list(chapters)
    seen = set()
    changed = {}
    for e in edits:
        key = e["chapter_id"], e["paragraph"]
        assert key not in seen
        seen.add(key)
        before = original[key[0]]["draft"]["paragraphs"][key[1] - 1]
        after = chapters[key[0]]["paragraphs"][key[1] - 1]
        assert e["before"] == before and e["after"] == after
        assert text_hash(before) == e["before_sha256"] and text_hash(after) == e["after_sha256"]
        changed[key] = after
    for uid, unit in original.items():
        assert unit["draft"]["title"] == chapters[uid]["title"]
        expected = [changed.get((uid, i), p) for i, p in enumerate(unit["draft"]["paragraphs"], 1)]
        assert expected == chapters[uid]["paragraphs"]
    assert len(edits) == metadata["edited_paragraphs"]
    assert sum(len(c["paragraphs"]) for c in chapters.values()) == metadata["paragraph_count"]
    assert sum(len(p) for c in chapters.values() for p in c["paragraphs"]) == metadata["characters_after"]
    return source, edits, chapters, metadata


def replay(directory, output=None):
    start = time.monotonic()
    source, edits, revised, metadata = verify_bundle(directory)
    print(json.dumps({"stage": "bundle_verified", "chapters": len(revised), "patches": len(edits)}, ensure_ascii=False), flush=True)
    schema = "editorial_case_" + uuid.uuid4().hex
    settings = Settings()
    service = None
    result = None
    try:
        with tempfile.TemporaryDirectory(prefix="editorial-case-") as temp, user_scope(uuid.uuid4().hex):
            studio = Studio(Settings(data_dir=Path(temp), database_url=settings.database_url, database_schema=schema))
            service = Editorials(studio)
            parent_id = source["project_id"]
            studio.store.put("adaptation", {"id": parent_id, "book_id": source["book_id"], "_release": deepcopy(source),
                "brief": source["brief"], "framework": source["framework"], "mode": source.get("mode", "adaptation")})
            s = service.create(parent_id, {"name": "长夜归舟 · 隔离回归夹具", "source_release_sha256": fingerprint(source),
                "profile": {"depth": "scan"}, "request_id": uuid.uuid4().hex})
            def write(method, **payload):
                nonlocal s
                s = getattr(service, method)(s["id"], {"expected_revision": s["revision"], "request_id": uuid.uuid4().hex, **payload})
            write("run_checks")
            groups = defaultdict(list)
            for edit in edits:
                groups[edit["chapter_id"]].append(edit)
            applied_count = 0
            durations = []
            navigation = {"exact": 0, "stale": 0, "baseline": 0, "unchanged_text": 0, "cursor_roundtrips": 0}
            for uid, group in groups.items():
                tick = time.monotonic()
                state = service.store.get("editorial", s["id"])
                unit = next(u for u in state["working"] if u["id"] == uid)
                anchors = [anchor_for(unit, unit["paragraphs"][edit["paragraph"] - 1]) for edit in group]
                # Use the last changed paragraph so navigation must reach beyond
                # the chapter opening in real long chapters.
                old_anchor = anchors[-1]
                located = service.locate(s["id"], {"anchor": old_anchor})
                assert located["location"]["status"] == "exact"
                assert old_anchor["paragraph_id"] in [p["id"] for p in located["items"][0]["paragraphs"]]
                navigation["exact"] += 1
                if located["previous_cursor"]:
                    previous = service.context(s["id"], unit_id=uid, cursor=located["previous_cursor"])
                    assert service.context(s["id"], unit_id=uid, cursor=previous["next_cursor"])["items"] == located["items"]
                    navigation["cursor_roundtrips"] += 1
                assert service.store.get("editorial", s["id"]) == state
                edited_ids = {a["paragraph_id"] for a in anchors}
                untouched = next((anchor_for(unit, p) for p in unit["paragraphs"] if p["id"] not in edited_ids), None)
                context = service.context(s["id"], unit_id=uid)["items"][0]
                first = context["paragraphs"][0]
                read_anchor = anchor_for(unit, unit["paragraphs"][0], first["text"], first["start"])
                # Only a protocol fixture. No inherited literary approval is created.
                report = {"kind": "chunk", "manuscript_sha256": s["manuscript_sha256"], "chunk_id": context["id"],
                    "reviewed_paragraph_ids": list(dict.fromkeys(p["id"] for p in context["paragraphs"])),
                    "categories": s["profile"]["categories"],
                    "summary": "自动回归夹具：按旧补丁验证工程定位，不作文学评价。", "evidence": [read_anchor],
                    "findings": [{"category": "prose", "severity": "suggestion", "suggested_action": "copyedit",
                                  "message": "旧修改回放：" + e["reason"], "evidence": [a]} for e, a in zip(group, anchors)]}
                write("submit_review", report=report)
                fids = s["last_operation"]["result"]["finding_ids"]
                pids = []
                for e, a, fid in zip(group, anchors, fids):
                    write("submit_patch", patch={"finding_ids": [fid], "anchor": a, "before": e["before"],
                        "after": e["after"], "reason": e["reason"], "evidence": [a]})
                    pids.append(s["last_operation"]["result"]["patch_id"])
                write("apply", patch_ids=pids, expected_manuscript_sha256=s["manuscript_sha256"])
                snapshot = service.store.get("editorial", s["id"])
                assert service.locate(s["id"], {"anchor": old_anchor})["location"]["status"] == "stale"
                navigation["stale"] += 1
                baseline = service.locate(s["id"], {"anchor": old_anchor, "source": "baseline"})
                assert baseline["location"]["status"] == "text_matches"
                paragraph = next(p for p in baseline["items"][0]["paragraphs"] if p["id"] == old_anchor["paragraph_id"])
                assert paragraph["text"] == old_anchor["quote"]
                navigation["baseline"] += 1
                if untouched:
                    assert service.locate(s["id"], {"anchor": untouched})["location"]["status"] == "text_matches"
                    navigation["unchanged_text"] += 1
                assert service.store.get("editorial", s["id"]) == snapshot
                applied_count += len(group)
                durations.append(time.monotonic() - tick)
                if len(durations) % 20 == 0:
                    print(json.dumps({"stage": "replay", "chapters": len(durations), "patches": applied_count,
                                      "elapsed_seconds": round(time.monotonic() - start, 2)}), flush=True)
            state = service.store.get("editorial", s["id"])
            for unit in state["working"]:
                assert [p["text"] for p in unit["paragraphs"]] == revised[unit["id"]]["paragraphs"]
            assert fingerprint(service.store.get("adaptation", parent_id)["_release"]) == fingerprint(source)
            # Correctly refuses to freeze automatically replayed, unverified changes.
            assert not s["can_finalize"] and s["coverage"]["verified_patches"] == 0
            from backend.app.editorial_export import build_exports
            sample = {"id": uuid.uuid4().hex, "name": "规模回归导出", "created_at": state["created_at"], "language": "简体中文",
                      "manuscript": state["working"], "profile": {"depth": "scan"}, "quality_outcome": "scan_only",
                      "readiness": {"ready": False, "reasons": ["自动回归，未作文学审读。"]},
                      "report": {"coverage": s["coverage"], "patches": state["patches"], "findings": state["findings"], "verifications": []}}
            files, manifest = build_exports(sample)
            verify_epub(files["epub"][0], state["working"])
            result = {"status": "passed", "chapters": len(revised), "paragraphs": metadata["paragraph_count"],
                "patches": applied_count, "characters_after": metadata["characters_after"], "export_formats": list(manifest),
                "max_chapter_batch_seconds": round(max(durations), 2),
                "source_unchanged": True, "unverified_freeze_blocked": True,
                "source_release_sha256": fingerprint(source), "navigation": navigation,
                "navigation_read_only": True, "literary_judgments_revalidated": False}
    finally:
        if service:
            service.store.close()
        with psycopg.connect(settings.database_url) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        with psycopg.connect(settings.database_url) as conn:
            assert conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,)).fetchone() is None
    result.update(temporary_schema_removed=True, elapsed_seconds=round(time.monotonic() - start, 2))
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, help="Persist the successful result after temporary-schema cleanup.")
    options = parser.parse_args()
    replay(options.directory, options.output)
