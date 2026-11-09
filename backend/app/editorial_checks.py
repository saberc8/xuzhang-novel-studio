"""Versioned deterministic candidates; these rules do not identify authorship."""
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal, localcontext

from .editorial_text import anchor_for, validate_anchor
from .editorial_story import story_candidates, lookup
from .rewriting import fingerprint
from .editorial_patterns import PATTERN_RULES, candidates as prose_candidates

RULESET_VERSION = "editorial-4"
RUBRIC_VERSION = "fiction-2"
RULES = {
    **PATTERN_RULES,
    "format.placeholder": "明确的待补标记或提示词角色标签",
    "format.character": "替换字符、控制字符或零宽字符",
    "prose.duplicate": "完全重复的长段落候选，可能属于引用或有意回环",
    "framework.term": "来源框架明确禁止的词语候选",
    "length.short": "低于参考篇幅的八成，需要检查场景展开程度",
    "fact.constraint": "已确认事实的数值或日期约束",
    "story.relationship": "同一视角下关系记录相反且叙事区段重叠的候选",
    "story.knowledge": "同一人物知情记录相反且叙事区段重叠的候选",
}


def candidate_basis(session, candidate):
    """A stable rule key is a location, not proof that a disposition still applies."""
    dependencies = {}
    if candidate.get("constraint_id"):
        constraint = session["constraints"].get(candidate["constraint_id"])
        dependencies["constraint"] = constraint
        if constraint:
            dependencies["facts"] = {key: session["facts"].get(key)
                                     for key in [*constraint["operand_ids"], constraint["result_id"]]}
    for kind, identifier in candidate.get("story_keys", []):
        dependencies[f"{kind}:{identifier}"] = lookup(session, kind, identifier)
    return fingerprint({"ruleset_version": RULESET_VERSION, "candidate": candidate, "dependencies": dependencies})


def check_constraints(session):
    results = []
    for constraint in session["constraints"].values():
        try:
            facts = [session["facts"][key] for key in [*constraint["operand_ids"], constraint["result_id"]]]
            if any(f["status"] != "confirmed" or f["perspective"] != "event" for f in facts):
                raise ValueError("候选、争议或人物认知不能直接当成客观事件计算")
            for fact in facts:
                if fact["manuscript_revision"] != session["manuscript_revision"]:
                    raise ValueError("事实须在当前稿重新确认")
                for evidence in fact["evidence"]:
                    validate_anchor(session, evidence, working_only=True)
            operands, expected = facts[:-1], facts[-1]
            op = constraint["operation"]
            if op in {"days_between", "years_between"}:
                if len(operands) != 2:
                    raise ValueError("时间间隔需要两个有序事件")
                if op == "days_between":
                    if not all(f["date"] for f in operands) or expected["measure"] != "days":
                        raise ValueError("日间隔需要精确公历日期，结果单位为 days")
                    result = Decimal((date.fromisoformat(operands[1]["date"]) - date.fromisoformat(operands[0]["date"])).days)
                else:
                    if any(f["measure"] != "year" for f in operands) or expected["measure"] != "years":
                        raise ValueError("年间隔需要 year 年份和 years 间隔")
                    values = [Decimal(f["value"]) for f in operands]
                    if any(v != v.to_integral_value() for v in values):
                        raise ValueError("年份必须是整数")
                    result = values[1] - values[0]
            else:
                if op in {"product", "difference"} and len(operands) != 2:
                    raise ValueError("乘积与差需要两个操作数")
                if not all(f["measure"] and f["value"] is not None for f in facts):
                    raise ValueError("数值约束需要明确数值与计量单位")
                dimensions = ("measure", "account", "currency", "settlement")
                measured = operands
                if op == "product":
                    if operands[0]["measure"] != "count" or Decimal(operands[0]["value"]) < 0:
                        raise ValueError("乘积的第一个操作数必须是非负 count 数量")
                    if Decimal(operands[0]["value"]) != Decimal(operands[0]["value"]).to_integral_value():
                        raise ValueError("count 数量必须是整数")
                    measured = operands[1:]
                if any(any(f[k] != expected[k] for k in dimensions) for f in measured):
                    raise ValueError("不同计量、账户、币种或兑付状态不可混算")
                if expected["measure"] == "money" and (not expected["account"] or not expected["currency"]):
                    raise ValueError("金额需要明确账户和币种")
                values = [Decimal(f["value"]) for f in operands]
                with localcontext() as ctx:
                    ctx.prec = 64
                    result = sum(values) if op == "sum" else values[0] - values[1] if op == "difference" else values[0] * values[1]
            if expected["value"] is None:
                raise ValueError("缺少待核对数值")
            results.append({"id": constraint["id"], "status": "passed" if result == Decimal(expected["value"]) else "mismatch",
                            "computed": str(result), "expected": expected["value"], "explanation": constraint["explanation"],
                            "evidence": [e for f in facts for e in f["evidence"]]})
        except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
            results.append({"id": constraint["id"], "status": "needs_review", "reason": str(exc)})
    return results


def scan(session):
    candidates, duplicates = [], defaultdict(list)
    units = [u for u in session["working"] if u["id"] in session["profile"]["unit_ids"]]

    def finding(rule, unit, paragraph, message, category, quote=None, start=0, severity="warning", evidence=None, key=None):
        evidence = evidence or [anchor_for(unit, paragraph, quote, start)]
        identity = key or [rule, unit["id"], paragraph["id"], quote or ""]
        candidates.append({"key": fingerprint(identity), "rule_id": rule, "category": category,
                           "severity": severity, "message": message, "evidence": evidence, "suggested_action": "review"})

    for unit in units:
        count = sum(len(p["text"]) for p in unit["paragraphs"])
        target = session.get("target_characters")
        if target and count < target * .8:
            finding("length.short", unit, unit["paragraphs"][0],
                    f"本章 {count} 字符，参考目标 {target}。请核对场景展开，不能仅补字。", "length",
                    quote=unit["paragraphs"][0]["text"][:80], severity="suggestion")
        for p in unit["paragraphs"]:
            text = p["text"]
            for match in re.finditer(r"【(?:待补|待写|待续写|插入正文)[^】]{0,100}】|<\|(?:im_start|im_end|assistant|system)\|>", text):
                finding("format.placeholder", unit, p, "正文出现待补或提示词标记，请核对其叙事用途。", "format", match[0], match.start())
            for match in re.finditer(r"[\ufffd\u200b\u200c\u200d\ufeff\x00-\x08\x0b\x0c\x0e-\x1f]", text):
                finding("format.character", unit, p, "正文含异常或不可见字符，请结合姓名、文字和 emoji 核对。", "format", match[0], match.start())
            for term in session.get("forbidden_terms", []):
                if term and term in text:
                    finding("framework.term", unit, p, f"命中来源框架禁用词「{term}」。", "reference", term, text.index(term))
            if len(text) >= 30:
                duplicates[text].append((unit, p))
    for text, locations in duplicates.items():
        if len(locations) > 1:
            # One finding per duplicate group; bound evidence while retaining frequency.
            unit, p = locations[0]
            finding("prose.duplicate", unit, p, f"此段完全重复 {len(locations)} 次，请核对引用、回环或无意复读。",
                    "prose", evidence=[anchor_for(u, p, p["text"][:160]) for u, p in locations[:20]],
                    key=["prose.duplicate", text])
            candidates[-1]["dimension"] = "template_repetition"
    prose, pattern_scope = prose_candidates(units)
    candidates.extend(prose)
    constraints = check_constraints(session)
    for result in constraints:
        if result["status"] == "mismatch":
            evidence = result["evidence"]
            unit, p = validate_anchor(session, evidence[0])
            finding("fact.constraint", unit, p, f"约束 {result['id']}：计算为 {result['computed']}，记录为 {result['expected']}。",
                    "timeline" if session["constraints"][result["id"]]["operation"].endswith("between") else "money",
                    severity="error", evidence=evidence, key=["fact.constraint", result["id"]])
            candidates[-1]["constraint_id"] = result["id"]
    candidates.extend(story_candidates(session))
    return {"ruleset_version": RULESET_VERSION, "manuscript_sha256": session["manuscript_sha256"],
            "manuscript_revision": session["manuscript_revision"], "unit_ids": [u["id"] for u in units],
            "paragraph_count": sum(len(u["paragraphs"]) for u in units),
            "character_count": sum(len(p["text"]) for u in units for p in u["paragraphs"]),
            "findings": candidates, "constraints": constraints, "pattern_scope": pattern_scope}
