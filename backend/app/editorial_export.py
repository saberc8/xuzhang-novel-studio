"""Build and verify all exports before committing an immutable edition."""
import hashlib
import io
import json
import re
import zipfile

from .bookio import build_epub
from .epub import member_path, xml
from .editorial_text import fail

FORMATS = ("epub", "txt", "md", "json", "report", "patches", "zip")


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


def verify_epub(content, manuscript):
    """Check actual spine order and XML text without whitespace normalization."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        opf = xml(archive.read("OEBPS/content.opf"))
        items = {e.get("id"): e.get("href") for e in opf.xpath("//*[local-name()='manifest']/*[local-name()='item']")}
        refs = opf.xpath("//*[local-name()='spine']/*[local-name()='itemref']/@idref")
        nav = xml(archive.read("OEBPS/nav.xhtml"))
        links = nav.xpath("//*[local-name()='nav']//*[local-name()='a']")
        if len(refs) != len(manuscript) or len(links) != len(manuscript):
            fail("export_mismatch", "EPUB 章节或导航数与冻结稿不一致")
        for ref, link, unit in zip(refs, links, manuscript):
            path = member_path("OEBPS/content.opf", items[ref])
            if member_path("OEBPS/nav.xhtml", link.get("href")) != path or "".join(link.itertext()) != unit["title"]:
                fail("export_mismatch", "EPUB 导航与阅读顺序不一致")
            tree = xml(archive.read(path))
            heading = tree.xpath("//*[local-name()='h1']")
            text = ["".join(p.itertext()) for p in tree.xpath("//*[local-name()='body']/*[local-name()='p']")]
            if len(heading) != 1 or "".join(heading[0].itertext()) != unit["title"] or text != [p["text"] for p in unit["paragraphs"]]:
                fail("export_mismatch", "EPUB 标题或正文逐段回读不一致")


def build_exports(edition):
    filename = re.sub(r'[\\/:*?"<>|\r\n]', "_", edition["name"])[:100]
    manuscript, report = edition["manuscript"], edition["report"]
    chapters = [{"title": u["title"], "paragraphs": [p["text"] for p in u["paragraphs"]]} for u in manuscript]
    target = edition.get("language", "und")
    language = "zh-CN" if "中文" in target or "汉语" in target else "en" if "English" in target or "英语" in target else "und"
    epub = build_epub(edition["name"], "文字精修版", chapters, language, identifier=edition["id"], modified=edition["created_at"])
    verify_epub(epub, manuscript)
    artifacts = {"epub": (epub, "application/epub+zip", filename + ".epub"),
                 "json": (json_bytes(edition), "application/json", filename + ".json"),
                 "patches": (json_bytes(report["patches"]), "application/json", filename + "-修订对照.json")}
    for format in ("txt", "md"):
        sections = [("# " if format == "md" else "") + edition["name"]]
        offsets, position = [], len(sections[0]) + 2
        for unit in manuscript:
            heading = ("## " if format == "md" else "") + unit["title"]
            sections.append(heading)
            position += len(heading) + 2
            for p in unit["paragraphs"]:
                sections.append(p["text"])
                offsets.append((position, position + len(p["text"]), p["text"]))
                position += len(p["text"]) + 2
        content = "\n\n".join(sections).encode("utf-8-sig")
        decoded = content.decode("utf-8-sig")
        if any(decoded[start:end] != text for start, end, text in offsets):
            fail("export_mismatch", "文本导出正文回读不一致")
        artifacts[format] = (content, "text/markdown" if format == "md" else "text/plain", filename + "." + format)
    lines = [f"# {edition['name']} · 审稿记录", f"审查深度：{edition['profile']['depth']}；结果：{edition['quality_outcome']}",
             f"候选定稿条件：{'满足' if edition['readiness']['ready'] else '尚未满足'}",
             "服务验证范围、定位与版本；阅读记录不等于文学质量或平台审核保证。",
             "## 覆盖", json.dumps(report["coverage"], ensure_ascii=False, indent=2), "## 保留问题与处理记录"]
    lines.extend(f"- {f['severity']} / {f['status']} / {f['id']}：{f['message']}" for f in report["findings"].values())
    lines.extend(["## 阻碍原因", *edition["readiness"]["reasons"], "## 复核记录"])
    lines.extend(f"- {v['verification']['outcome']}：{v['verification']['reason']}" for v in report["verifications"])
    if report.get("story_coverage"):
        lines.extend(["## 人物、关系与知情覆盖", json.dumps(report["story_coverage"], ensure_ascii=False, indent=2),
                      "逐条证据、关系图数据与更新历史保存在完整 JSON 的 report.story 中。"])
    if report.get("quality"):
        quality = report["quality"]
        lines.extend(["## 去 AI 味与文学性专项", f"审读模式：{quality['mode']}；专项约定满足：{quality['ready']}",
                      "通过表示本轮声明的审读、处置与复核契约完整，具体文学判断仍保留原文依据。"])
        lines.extend(f"- {d['label']}：分块 {d['reviewed_chunks']}；跨章 {d['audit_complete']}；待处理 {d['pending']}；暂缓 {d['deferred']}"
                     for d in quality["dimensions"])
    artifacts["report"] = ("\n\n".join(lines).encode("utf-8"), "text/markdown", filename + "-审稿报告.md")
    manifest = {fmt: {"filename": name, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
                for fmt, (body, _, name) in artifacts.items()}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for body, _, name in artifacts.values():
            archive.writestr(name, body)
        archive.writestr("manifest.json", json_bytes(manifest))
    zipped = output.getvalue()
    with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
        for item in manifest.values():
            if hashlib.sha256(archive.read(item["filename"])).hexdigest() != item["sha256"]:
                fail("export_mismatch", "ZIP 清单哈希不匹配")
    artifacts["zip"] = (zipped, "application/zip", filename + ".zip")
    manifest["zip"] = {"filename": filename + ".zip", "sha256": hashlib.sha256(zipped).hexdigest(), "bytes": len(zipped)}
    return artifacts, manifest
