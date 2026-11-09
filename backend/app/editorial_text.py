"""Text identity, source adapters, and bounded pagination shared by editorial flows."""
import base64
import hashlib
import json
from copy import deepcopy

from .rewriting import fingerprint, release_book

DIGEST_ALGORITHM = "sha256-json-ensure_ascii_false-sort_keys-v1"


class EditorialError(ValueError):
    def __init__(self, code, message, status=422, **detail):
        super().__init__(message)
        self.status = status
        self.detail = {"code": code, "message": message, **detail}


def fail(code, message, status=422, **detail):
    raise EditorialError(code, message, status, **detail)


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_source(store, project_id, edition_id=None):
    """Return the exact frozen object and normalized text, retaining original lineage."""
    project = store.get("adaptation", project_id)
    if not project.get("_release"):
        fail("source_not_frozen", "请先保存来源项目的独立版本")
    release = project["_release"]
    if edition_id:
        edition = store.get("editorial_edition", edition_id)
        if edition["source_project_id"] != project_id:
            fail("source_mismatch", "精修版本不属于指定来源项目")
        return project, edition, deepcopy(edition["manuscript"])
    chapters = release_book(project)["chapters"]
    return project, release, [{"id": c["id"], "title": c["title"], "revision": 1,
                              "paragraphs": c["paragraphs"]} for c in chapters]


def manifest(units):
    return [{"unit_id": u["id"], "title": u["title"], "revision": u["revision"],
             "paragraphs": [{"id": p["id"], "sha256": text_hash(p["text"]), "characters": len(p["text"])}
                            for p in u["paragraphs"]]} for u in units]


def manuscript_hash(units):
    # Version counters are separate from content identity, including after an undo.
    return fingerprint([{k: u[k] for k in ("id", "title", "paragraphs")} for u in units])


def anchor_for(unit, paragraph, quote=None, start=0, source="working"):
    quote = paragraph["text"] if quote is None else quote
    return {"source": source, "unit_id": unit["id"], "paragraph_id": paragraph["id"],
            "unit_revision": unit["revision"], "paragraph_sha256": text_hash(paragraph["text"]),
            "quote": quote, "start": start, "end": start + len(quote), "offset_unit": "unicode_code_point"}


def validate_anchor(session, anchor, working_only=False):
    if working_only and anchor["source"] != "working":
        fail("evidence_source", "本次操作需要当前工作稿证据")
    units = session[anchor["source"]]
    unit = next((u for u in units if u["id"] == anchor["unit_id"]), None)
    paragraph = next((p for p in unit["paragraphs"] if p["id"] == anchor["paragraph_id"]), None) if unit else None
    if not paragraph:
        fail("evidence_missing", "证据章节或段落不存在")
    if unit["id"] not in session["profile"]["unit_ids"]:
        fail("outside_scope", "证据不在本次约定的审稿范围内")
    if unit["revision"] != anchor["unit_revision"] or text_hash(paragraph["text"]) != anchor["paragraph_sha256"]:
        fail("evidence_stale", "证据修订或段落哈希过期，请重读当前正文", 409)
    if paragraph["text"][anchor["start"]:anchor["end"]] != anchor["quote"] or anchor["end"] > len(paragraph["text"]):
        fail("evidence_mismatch", "引用与 Unicode 码点坐标不匹配")
    return unit, paragraph


def locate_anchor(session, anchor, source):
    """Locate by stable paragraph ID, never guess a replacement for old evidence."""
    if anchor["end"] <= anchor["start"] or len(anchor["quote"]) != anchor["end"] - anchor["start"]:
        fail("evidence_mismatch", "引用与 Unicode 码点坐标不匹配")
    if anchor["unit_id"] not in session["profile"]["unit_ids"]:
        fail("outside_scope", "证据不在本次约定的审稿范围内")
    unit = next((u for u in session[source] if u["id"] == anchor["unit_id"]), None)
    paragraph = next((p for p in unit["paragraphs"] if p["id"] == anchor["paragraph_id"]), None) if unit else None
    if not paragraph:
        fail("evidence_missing", "所选版本中不存在这处证据段落")
    matches = (text_hash(paragraph["text"]) == anchor["paragraph_sha256"]
               and paragraph["text"][anchor["start"]:anchor["end"]] == anchor["quote"])
    status = ("exact" if source == anchor["source"] and unit["revision"] == anchor["unit_revision"]
              else "text_matches") if matches else "stale"
    return {"status": status, "unit_id": unit["id"], "paragraph_id": paragraph["id"],
            "start": anchor["start"], "end": anchor["end"],
            "located_start": min(anchor["start"], len(paragraph["text"]) - 1)}


def chunks(session, source="working"):
    """At most 6,000 code points / 24 fragments per chunk, including long paragraphs."""
    result = []
    for unit in session[source]:
        if unit["id"] not in session["profile"]["unit_ids"]:
            continue
        group, size = [], 0

        def flush():
            nonlocal group, size
            if group:
                result.append({"id": f"chunk{len(result) + 1:05d}", "unit_id": unit["id"],
                               "title": unit["title"], "unit_revision": unit["revision"], "paragraphs": group})
                group, size = [], 0

        for paragraph in unit["paragraphs"]:
            # Empty paragraphs are rejected on create; edits also preserve nonempty paragraphs.
            for offset in range(0, len(paragraph["text"]), 6000):
                text = paragraph["text"][offset:offset + 6000]
                if size + len(text) > 6000 or len(group) >= 24:
                    flush()
                group.append({"id": paragraph["id"], "text": text, "start": offset, "end": offset + len(text),
                              "paragraph_sha256": text_hash(paragraph["text"])})
                size += len(text)
        flush()
    return result


def encode_cursor(binding, offset):
    return base64.urlsafe_b64encode(json.dumps([binding, offset]).encode()).decode().rstrip("=")


def decode_cursor(cursor, binding):
    if not cursor:
        return 0
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if not isinstance(value, list) or len(value) != 2 or type(value[1]) is not int or value[1] < 0:
            raise ValueError
    except (ValueError, TypeError):
        fail("invalid_cursor", "分页游标无效")
    if value[0] != binding:
        fail("cursor_stale", "正文或分页条件已变化，请从第一页重新读取", 409)
    return value[1]


def page(items, cursor, limit, binding):
    offset = decode_cursor(cursor, binding)
    if offset > len(items):
        fail("invalid_cursor", "分页位置超出当前范围")
    end = min(offset + limit, len(items))
    return {"items": items[offset:end], "total": len(items), "offset": offset,
            "previous_cursor": encode_cursor(binding, max(0, offset - limit)) if offset else None,
            "next_cursor": encode_cursor(binding, end) if end < len(items) else None}
