"""Bounded textual candidates, never automatic instructions to rewrite prose."""
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from .editorial_text import anchor_for
from .rewriting import fingerprint

PATTERN_RULES = {
    "prose.near_duplicate": "近似长段落候选（忽略标点与空白后比较）",
    "prose.repeated_sentence": "跨段重复出现的完整句子候选",
    "prose.pattern_density": "同章高密度套用句式候选",
    "prose.chapter_template": "不同章节相似的开头或结尾候选",
}
# Frequency is needed: one contrast, explicit emotion, or repeated motif is not an error.
PATTERNS = {
    "contrast": (r"不是[^。！？!?\n]{1,48}[，,]而是", "否定转折句式", "template_repetition"),
    "explanation": (r"(?:这说明|这意味着|他终于明白|她终于明白|他深知|她深知|不以|不把)", "解释或边界说明句式", "redundant_explanation"),
    "stock_closure": (r"(?:一切才刚刚开始|命运的齿轮|人生何尝不是|真正的[^。！？\n]{1,12}不是)", "概括或收束句式", "template_repetition"),
}


def candidates(units):
    findings, sentences, index, previous, pairs = [], defaultdict(list), defaultdict(list), [], []
    stats = {"eligible_paragraphs": 0, "long_paragraphs_skipped": 0, "comparisons": 0,
             "max_normalized_characters": 1200, "max_candidates_per_paragraph": 8,
             "max_postings_per_shingle": 40, "method": "bounded shingle retrieval + sequence similarity; candidates only"}

    def emit(rule, locations, message, dimension="template_repetition", identity=None, spans=None):
        # Keep offsets on original text; normalization is used only for retrieval.
        evidence = []
        for i, (u, p) in enumerate(locations[:20]):
            start, end = spans[i] if spans else (0, len(p["text"]))
            evidence.append(anchor_for(u, p, p["text"][start:min(end, start + 160)], start))
        findings.append({"key": fingerprint([rule, identity or [(u["id"], p["id"]) for u, p in locations]]),
            "rule_id": rule, "category": "prose", "dimension": dimension, "severity": "suggestion",
            "message": message + "；请结合本书文风、引用和有意回环核对，不自动删改。",
            "evidence": evidence, "suggested_action": "review", "occurrences": len(locations)})

    for u in units:
        density = defaultdict(list)
        for pi, p in enumerate(u["paragraphs"]):
            text = p["text"]
            for key, (pattern, _, _) in PATTERNS.items():
                match = re.search(pattern, text)
                if match:
                    density[key].append((u, p, match.span()))
            # Bound comparison work; exact duplicate checks still inspect every paragraph.
            normalized = re.sub(r"[\W_]+", "", text).casefold()
            if len(normalized) > 1200:
                stats["long_paragraphs_skipped"] += 1
            paragraph_sentences = {}
            for match in re.finditer(r"[^。！？!?\n]+", text):
                key = re.sub(r"[\W_]+", "", match[0]).casefold()
                paragraph_sentences.setdefault(key, match.span())
            for key, span in sorted(paragraph_sentences.items()):
                if 12 <= len(key) <= 240:
                    sentences[key].append((u, p, span))
            if not 30 <= len(normalized) <= 1200:
                continue
            stats["eligible_paragraphs"] += 1
            # Fixed lexical shingles make the result reproducible across processes.
            grams = sorted({normalized[i:i + 4] for i in range(len(normalized) - 3)})
            keys = grams[::max(1, len(grams) // 16)][:16]
            scores = Counter(j for key in keys for j in index[key])
            for j, hits in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:8]:
                other, ou, op, oi = previous[j]
                if hits < 2 or op["text"] == text or min(len(other), len(normalized)) / max(len(other), len(normalized)) < .75:
                    continue
                stats["comparisons"] += 1
                matcher = SequenceMatcher(None, other, normalized, autojunk=False)
                if matcher.quick_ratio() >= .84 and matcher.ratio() >= .84:
                    edge = "opening" if pi == oi == 0 else "closing" if pi == len(u["paragraphs"]) - 1 and oi == len(ou["paragraphs"]) - 1 else None
                    pairs.append((j, len(previous), bool(edge and ou["id"] != u["id"])))
            for key in keys:
                index[key].append(len(previous))
                if len(index[key]) > 40:
                    del index[key][0]
            previous.append((normalized, u, p, pi))
        for key, matches in density.items():
            if len(matches) >= 3 and len(matches) * 1000 / max(1, sum(len(p["text"]) for p in u["paragraphs"])) >= 1:
                _, label, dimension = PATTERNS[key]
                emit("prose.pattern_density", [(u, p) for u, p, _ in matches], f"本章有 {len(matches)} 段使用{label}",
                     dimension, [u["id"], key], [span for _, _, span in matches])
    # Merge similar pairs into bounded evidence groups rather than quadratic findings.
    parents = list(range(len(previous)))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    for a, b, _ in pairs:
        parents[root(b)] = root(a)
    groups = defaultdict(set)
    edge_groups = set()
    for a, b, edge in pairs:
        group = root(a)
        groups[group].update((a, b))
        if edge:
            edge_groups.add(group)
    for group, ids in groups.items():
        locations = [(previous[i][1], previous[i][2]) for i in sorted(ids)]
        rule = "prose.chapter_template" if group in edge_groups else "prose.near_duplicate"
        emit(rule, locations, f"发现 {len(locations)} 处近似表达" + ("，涉及不同章节的首尾" if group in edge_groups else ""))
    for sentence, matches in sentences.items():
        if len(matches) >= 3:
            emit("prose.repeated_sentence", [(u, p) for u, p, _ in matches],
                 f"句子「{sentence[:60]}」在 {len(matches)} 段中重复出现", identity=sentence,
                 spans=[span for _, _, span in matches])
    return findings, stats
