"""Repeatable in-memory graph projection benchmark; no database or model calls."""
import argparse
import json
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.editorial_models import Fact, StoryEntity, StoryKnowledge, StoryRelation
from backend.app.editorial_story import view_story
from backend.app.editorial_text import anchor_for
from backend.app.rewriting import fingerprint


def fixture():
    unit = {"id": "u1", "title": "基准章", "revision": 1,
            "paragraphs": [{"id": "p1", "text": "基准夹具用于测试分页、证据和依赖，不代表真实小说。" * 40}]}
    anchor = anchor_for(unit, unit["paragraphs"][0])
    entities = {}
    for i in range(1000):
        entity = StoryEntity(id=f"person-{i:04}", name=f"人物{i:04}", description="性能夹具。",
                             status="confirmed", evidence=[anchor]).model_dump()
        entities[entity["id"]] = {**entity, "manuscript_revision": 1, "updated_at": "fixture", "dependencies": {}}
    fact = {**Fact(id="secret", statement="性能夹具中的秘密。", status="confirmed", evidence=[anchor]).model_dump(),
            "manuscript_revision": 1}
    digests = {f"entities:{i}": fingerprint(e) for i, e in entities.items()} | {"facts:secret": fingerprint(fact)}
    relations, knowledge = {}, {}
    for i in range(5000):
        r = StoryRelation(id=f"relation-{i:05}", source_id=f"person-{i % 1000:04}",
                          target_id=f"person-{(i + 1) % 1000:04}", label="认识", explanation="分页性能夹具。",
                          from_unit_id="u1", status="confirmed", evidence=[anchor]).model_dump()
        deps = [f"entities:{r['source_id']}", f"entities:{r['target_id']}"]
        relations[r["id"]] = {**r, "manuscript_revision": 1, "updated_at": "fixture",
                              "dependencies": {k: digests[k] for k in deps}}
    for i in range(2000):
        k = StoryKnowledge(id=f"knowledge-{i:05}", holder_id=f"person-{i % 1000:04}", fact_id="secret",
                           state="knows", acquisition="分页性能夹具。", from_unit_id="u1",
                           status="confirmed", evidence=[anchor]).model_dump()
        deps = [f"entities:{k['holder_id']}", "facts:secret"]
        knowledge[k["id"]] = {**k, "manuscript_revision": 1, "updated_at": "fixture",
                              "dependencies": {key: digests[key] for key in deps}}
    return {"id": "benchmark", "revision": 1, "manuscript_revision": 1, "knowledge_revision": 1,
            "profile": {"unit_ids": ["u1"], "continuity_mode": "tracked"}, "working": [unit], "facts": {"secret": fact},
            "story": {"entities": entities, "relations": relations, "knowledge": knowledge, "reviews": [], "changes": []}}


def benchmark(repeats):
    session = fixture()
    results = {}
    for kind in ("entities", "relations", "knowledge"):
        durations = []
        for _ in range(repeats):
            start = time.perf_counter()
            result = view_story(session, kind, limit=6)
            durations.append(time.perf_counter() - start)
        tracemalloc.start()
        view_story(session, kind, limit=6)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        results[kind] = {"median_ms": round(statistics.median(durations) * 1000, 2),
                         "peak_kib": round(peak / 1024, 1), "returned_items": len(result["items"]),
                         "total": result["total"], "response_bytes": len(json.dumps(result, ensure_ascii=False).encode())}
    return {"scope": "in-memory projection only; excludes PostgreSQL load and HTTP serialization",
            "repeats": repeats, "records": {"entities": 1000, "relations": 5000, "knowledge": 2000}, "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 30:
        parser.error("--repeats must be 1–30")
    result = benchmark(args.repeats)
    content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content)
    print(content)
