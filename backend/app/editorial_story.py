"""Evidence-backed story memory; graph views are projections of these records.

Chapter ranges describe narrative applicability, not physical simultaneity.
No name-based identity merge, transitive relationship or omniscience inference.
"""
from collections import defaultdict
from copy import deepcopy

from .editorial_text import fail, page, validate_anchor
from .rewriting import fingerprint

KINDS = ("entities", "relations", "knowledge")


def ledger(session):
    return session.get("story", {**{kind: {} for kind in KINDS}, "reviews": [], "changes": []})


def order(session):
    return {u["id"]: i for i, u in enumerate(session["working"])}


def references(kind, record):
    if kind == "relations":
        return [("entities", key) for key in
                dict.fromkeys([record["source_id"], record["target_id"], *([record["observer_id"]] if record["observer_id"] else [])])]
    if kind == "knowledge":
        return [("entities", record["holder_id"]), ("facts", record["fact_id"])]
    return []


def lookup(session, kind, identifier):
    return (session["facts"] if kind == "facts" else ledger(session)[kind]).get(identifier)


def is_current(session, kind, record, digests=None):
    if record.get("manuscript_revision") != session["manuscript_revision"]:
        return False
    for dep_kind, identifier in references(kind, record):
        dep = lookup(session, dep_kind, identifier)
        if not dep or dep.get("manuscript_revision") != session["manuscript_revision"]:
            return False
        key = f"{dep_kind}:{identifier}"
        # Cache only within one read of a session, never across mutations.
        if digests is not None and key not in digests:
            digests[key] = fingerprint(dep)
        digest = digests[key] if digests is not None else fingerprint(dep)
        if record.get("dependencies", {}).get(key) != digest:
            return False
    return True


def is_confirmed(session, kind, record, digests=None):
    return (record["status"] == "confirmed" and is_current(session, kind, record, digests)
            and all(lookup(session, k, i)["status"] == "confirmed" for k, i in references(kind, record)))


def applicable(record, index, positions):
    start = positions[record["from_unit_id"]]
    end = positions[record["through_unit_id"]] if record["through_unit_id"] else len(positions) - 1
    return start <= index <= end


def story_coverage(session, digests=None):
    data = ledger(session)
    digests = {} if digests is None else digests
    reviewed = {r["unit_id"] for r in data["reviews"]
                if r["manuscript_revision"] == session["manuscript_revision"]
                and r["knowledge_revision"] == session["knowledge_revision"]}
    scope = session["profile"]["unit_ids"]
    counts = {}
    for kind in KINDS:
        active = [r for r in data[kind].values() if r["status"] != "withdrawn"]
        counts[kind] = {"total": len(active),
                        "confirmed": sum(is_confirmed(session, kind, r, digests) for r in active),
                        "stale": sum(not is_current(session, kind, r, digests) for r in active)}
    return {"mode": session["profile"].get("continuity_mode", "manual"),
            "reviewed_units": len(reviewed & set(scope)), "total_units": len(scope),
            "missing_unit_ids": [i for i in scope if i not in reviewed], **counts}


def required_records(session, unit_id):
    data, positions = ledger(session), order(session)
    expected = {kind: set() for kind in KINDS}
    for entity in data["entities"].values():
        evidence = entity["evidence"] + [a for alias in entity["aliases"] for a in alias["evidence"]]
        if entity["status"] != "withdrawn" and any(a["unit_id"] == unit_id for a in evidence):
            expected["entities"].add(entity["id"])
    for kind in ("relations", "knowledge"):
        for record in data[kind].values():
            if record["status"] != "withdrawn" and applicable(record, positions[unit_id], positions):
                expected[kind].add(record["id"])
                expected["entities"].update(i for k, i in references(kind, record) if k == "entities")
    return expected


def update_story(session, update, timestamp):
    data = session.setdefault("story", {**{kind: {} for kind in KINDS}, "reviews": [], "changes": []})
    positions, scope = order(session), set(session["profile"]["unit_ids"])
    changed_ids = {kind: [] for kind in KINDS}
    for kind in KINDS:
        ids = [r["id"] for r in update[kind]]
        if len(ids) != len(set(ids)):
            fail("duplicate_id", "同批故事记录编号不可重复")
        for record in update[kind]:
            for anchor in record["evidence"]:
                validate_anchor(session, anchor, working_only=True)
            if kind == "entities":
                previous = data[kind].get(record["id"])
                if previous and previous["kind"] != record["kind"]:
                    fail("entity_kind_changed", "实体编号的类型不能改变；请另建实体并注明旧记录撤回原因")
                names = [a["name"] for a in record["aliases"]]
                if len(names) != len(set(names)):
                    fail("duplicate_alias", "同一实体的别名不可重复")
                for alias in record["aliases"]:
                    for anchor in alias["evidence"]:
                        validate_anchor(session, anchor, working_only=True)
            else:
                start, end = record["from_unit_id"], record["through_unit_id"]
                if start not in scope or (end is not None and end not in scope):
                    fail("outside_scope", "关系与知情区段必须在所选章节内")
                if end is not None and positions[start] > positions[end]:
                    fail("story_range", "关系与知情区段的末章不能早于起章；倒叙时间请写入 story_time")
            deps = {}
            for dep_kind, identifier in references(kind, record):
                dep = lookup(session, dep_kind, identifier)
                if not dep:
                    fail("story_reference_missing", f"引用的 {dep_kind} 记录不存在：{identifier}")
                if record["status"] != "withdrawn" and (dep["status"] == "withdrawn" or dep.get("manuscript_revision") != session["manuscript_revision"]):
                    fail("story_dependency_stale", "引用的实体或事实已撤回或属于旧稿，请先复核")
                if ((kind == "knowledge" and dep_kind == "entities")
                        or (kind == "relations" and identifier == record["observer_id"])):
                    if dep["kind"] != "character":
                        fail("story_observer_kind", "知情主体与认知视角必须是人物实体")
                deps[f"{dep_kind}:{identifier}"] = fingerprint(dep)
            next_record = {**deepcopy(record), "dependencies": deps, "manuscript_revision": session["manuscript_revision"]}
            previous = data[kind].get(record["id"])
            # Preserve timestamps/fingerprints on exact upserts, including a
            # resumed agent using a fresh request ID. New dependencies or a new
            # manuscript still constitute a real change.
            if previous is None or {k: v for k, v in previous.items() if k != "updated_at"} != next_record:
                data[kind][record["id"]] = {**next_record, "updated_at": timestamp}
                changed_ids[kind].append(record["id"])
    if any(changed_ids.values()):
        session["knowledge_revision"] += 1
    ids = [r["unit_id"] for r in update["chapter_reviews"]]
    if len(ids) != len(set(ids)):
        fail("duplicate_id", "同批逐章核对不可重复")
    for review in update["chapter_reviews"]:
        if review["unit_id"] not in scope:
            fail("outside_scope", "逐章故事核对超出审稿范围")
        if {a["unit_id"] for a in review["evidence"]} != {review["unit_id"]}:
            fail("story_review_evidence", "逐章故事核对需引用本章证据")
        for anchor in review["evidence"]:
            validate_anchor(session, anchor, working_only=True)
        expected = required_records(session, review["unit_id"])
        for kind, field in (("entities", "entity_ids"), ("relations", "relation_ids"), ("knowledge", "knowledge_ids")):
            selected = review[field]
            if len(selected) != len(set(selected)) or not expected[kind] <= set(selected):
                fail("story_review_incomplete", "逐章核对遗漏已登记的适用记录，或重复指定记录", required={k: sorted(v) for k, v in expected.items()})
            for identifier in selected:
                record = data[kind].get(identifier)
                if not record or record["status"] == "withdrawn" or not is_current(session, kind, record):
                    fail("story_review_stale", "逐章核对引用了不存在、撤回或待更新的故事记录")
        data["reviews"].append({**deepcopy(review), "manuscript_revision": session["manuscript_revision"],
                                "knowledge_revision": session["knowledge_revision"], "at": timestamp})
    data["changes"].append({"update": deepcopy(update), "manuscript_revision": session["manuscript_revision"],
                            "knowledge_revision": session["knowledge_revision"], "at": timestamp})
    return {kind: [r["id"] for r in update[kind]] for kind in KINDS} | {
        "reviewed_unit_ids": ids, "changed_record_ids": changed_ids}


def view_story(session, kind="relations", entity_id=None, at_unit_id=None, query=None, cursor=None, limit=20):
    if kind not in (*KINDS, "reviews") or not 1 <= limit <= 50 or (query and len(query) > 120):
        fail("invalid_story_query", "故事记录类型、查询或分页大小不合法")
    data, positions, digests = ledger(session), order(session), {}
    if at_unit_id and at_unit_id not in session["profile"]["unit_ids"]:
        fail("outside_scope", "查询章节超出审稿范围")
    if entity_id and entity_id not in data["entities"]:
        fail("story_reference_missing", "人物或实体编号不存在")
    cutoff = positions[at_unit_id] if at_unit_id else None

    def available(record):
        return cutoff is None or all(positions[a["unit_id"]] <= cutoff for a in record["evidence"])

    def visible_entity(entity):
        return {**deepcopy(entity), "aliases": deepcopy([a for a in entity["aliases"] if available(a)]),
                "current": is_current(session, "entities", entity, digests),
                "confirmed": is_confirmed(session, "entities", entity, digests)}

    visible = {i: e for i, e in data["entities"].items() if available(e)}
    search = (query or "").strip().casefold()
    matches = {i for i, e in visible.items()
               if not search or search in (e["name"] + " " + " ".join(a["name"] for a in e["aliases"] if available(a))).casefold()}
    items = []
    for record in (data[kind].values() if kind != "reviews" else data["reviews"]):
        if not available(record):
            continue
        if kind == "entities":
            involved = {record["id"]}
        elif kind == "reviews":
            if at_unit_id and record["unit_id"] != at_unit_id:
                continue
            involved = set(record["entity_ids"])
        else:
            involved = {i for k, i in references(kind, record) if k == "entities"}
            if not involved <= visible.keys() or (cutoff is not None and not applicable(record, cutoff, positions)):
                continue
            if kind == "knowledge" and not available(session["facts"][record["fact_id"]]):
                continue
        if (entity_id and entity_id not in involved) or (search and not involved & matches):
            continue
        items.append(record)
    if kind != "reviews":
        items.sort(key=lambda r: r["id"])
    binding = fingerprint([session["id"], session["revision"], kind, entity_id, at_unit_id, query])
    result = page(items, cursor, limit, binding)
    # Filter and page references first. Copy and decorate only the returned page.
    if kind == "reviews":
        result["items"] = [{**deepcopy(r), "current": r["manuscript_revision"] == session["manuscript_revision"]
                           and r["knowledge_revision"] == session["knowledge_revision"]} for r in result["items"]]
    elif kind == "entities":
        result["items"] = [visible_entity(r) for r in result["items"]]
    else:
        result["items"] = [{**deepcopy(r), "current": is_current(session, kind, r, digests),
                            "confirmed": is_confirmed(session, kind, r, digests)} for r in result["items"]]
    node_ids, fact_ids = set(), set()
    for item in result["items"]:
        if kind == "entities":
            node_ids.add(item["id"])
        elif kind == "reviews":
            node_ids.update(item["entity_ids"])
        else:
            for dep_kind, identifier in references(kind, item):
                (node_ids if dep_kind == "entities" else fact_ids).add(identifier)
    # A page exposes only its dependencies; never ship the full-book graph.
    result.update(nodes=[visible_entity(visible[i]) for i in sorted(node_ids) if i in visible],
                  facts=[deepcopy(session["facts"][i]) for i in sorted(fact_ids)],
                  revision=session["revision"], manuscript_revision=session["manuscript_revision"],
                  coverage=story_coverage(session, digests), at_unit_id=at_unit_id,
                  interpretation="章节区段用于叙事定位；倒叙、同章先后与不可靠叙述仍需语境复核。")
    if kind == "reviews" and at_unit_id:
        result["required_record_ids"] = {k: sorted(v) for k, v in required_records(session, at_unit_id).items()}
    return result


def unresolved_dependencies(session, keys):
    return any(not (record := lookup(session, k, i)) or not is_confirmed(session, k, record) for k, i in keys)


def story_candidates(session):
    """Conservative warning candidates; overlap never proves a story error."""
    data, positions, digests = ledger(session), order(session), {}
    candidates = []

    def add(rule, category, message, kind, records):
        candidates.append({"key": fingerprint([rule, sorted(r["id"] for r in records)]),
                           "rule_id": rule, "category": category, "severity": "warning",
                           "message": message, "evidence": [a for r in records for a in r["evidence"]][:20],
                           "suggested_action": "review", "story_keys": [[kind, r["id"]] for r in records]})

    def overlaps(a, b):
        end_a = positions[a["through_unit_id"]] if a["through_unit_id"] else len(positions) - 1
        end_b = positions[b["through_unit_id"]] if b["through_unit_id"] else len(positions) - 1
        return max(positions[a["from_unit_id"]], positions[b["from_unit_id"]]) <= min(end_a, end_b)

    for kind in ("relations", "knowledge"):
        groups = defaultdict(list)
        for record in data[kind].values():
            if not is_confirmed(session, kind, record, digests):
                continue
            key = ((record["source_id"], record["target_id"], record["label"], record["perspective"], record["observer_id"])
                   if kind == "relations" else (record["holder_id"], record["fact_id"]))
            groups[key].append(record)
        for records in groups.values():
            for i, a in enumerate(records):
                for b in records[i + 1:]:
                    opposed = (a["polarity"] != b["polarity"] if kind == "relations"
                               else {a["state"], b["state"]} == {"knows", "unaware"})
                    if opposed and overlaps(a, b):
                        add("story.relationship" if kind == "relations" else "story.knowledge",
                            "relationship" if kind == "relations" else "knowledge",
                            f"故事记录 {a['id']} 与 {b['id']} 的适用章节重叠且表述相反；请核对具体场景、时间和认知变化。",
                            kind, [a, b])
    return candidates
