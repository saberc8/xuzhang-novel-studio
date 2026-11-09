"""Light adaptation policy shared by the MCP guide and project handoffs.

These are editorial instructions, not a keyword-based suitability classifier.
Only scope, ordering and explicit review fields are enforced by the service.
"""

LIGHT_INSTRUCTIONS = [
    "轻度改编默认同时包含人物姓名与地点命名。保留人物身份、亲属关系、时代、能力规则、剧情主线、章节顺序与事件结果；不擅自扩写或重构。用户明确限定的范围优先。",
    "先盘点人物全名、别名、昵称和称谓，以及国家、区域、省市、山川、街道、住所、学校、酒店、宗门驻地。公司、组织与地点分列；相关机构词根和命名解释需联动核对。",
    "人物写入 framework.characters；地点及关联机构的新旧名称写入 framework.setting_mappings，rationale 说明实体、上下级/相邻关系、别名、语境条件和保留例外。framework.locations 仅列主要场景，不替代完整对照表。",
    "先给出可审阅的命名方案。用户要求先确认时，方案明确标为待确认，确认前不替换正文；已有明确授权和已确认映射不重复询问。歧义项标注待核，不按同名或字形相似自动合并。保存确认后的框架再锁定执行。",
    "姓名与地名均按实体和上下文替换，不全局替换单字。保留成语、普通景物词、姓氏称呼和未命名空间；同名不同人、地点与人名同形、国名与王子称号分别判断。先统一有证据的异写，再应用新名。",
    "地点更名保持国家/区域/省/市/场所层级、隶属、距离、方位和往返路线；学校、港口、广场、酒店及所属机构随地名联动。公司由人名取字时，同时修正招牌、简称和解释性对白，避免新姓名与旧词根矛盾。",
    "内容删减范围遵循用户约定的读者与限制。约定少儿阅读时，审读成人色情、性侵暗示、露骨回忆、羞辱排泄和血腥描写，包括章题与后文回指；普通恋爱、怀孕与家庭责任按语境判断，不能仅凭关键词删除。",
    "删减后核对原因—行动—结果，以及时间、空间、主语、人物关系与能力晋升。异常短章、突然坠落/获救、药效消失或境界跳升须回查原文；优先保留适宜的既有承接，必要的最小中性过渡须记录新增事实并核对后章，不恢复不适宜内容。",
    "按原目录一章对应一章，不合并、拆分、重排或静默删章。每章 change_notes 记录改名、地点联动、删减与必要承接修补；不为固定目标字数填充正文。",
    "逐章读完当前稿件，除原有七项审查外，显式提交 locations 和 content_suitability。causality/continuity 必须覆盖删减后的承接；适读检查仅针对已约定范围，不作年龄分级保证。未通过项登记对应 error 并修订复核。",
    "交付前复核实际导出正文、章节目录、映射残留及有意保留的例外，保留原作与旧版。全量程序扫描、重点语义审读、全书文学复读分别报告；关键词零命中、字数或 EPUB 结构通过均不能充当全书质量通过。",
]


def is_light(project: dict) -> bool:
    return project.get("mode", "adaptation") == "adaptation" and project.get("brief", {}).get("preset") == "light"


def check_light_scope(brief: dict, chapter_ids: list[str]) -> None:
    if brief["preset"] == "light" and brief["target_units"] != len(chapter_ids):
        raise ValueError("轻度改编保留原章：target_units 须等于所选章节数，不合并或删章")


def check_light_plan(project: dict, plan: dict) -> None:
    if plan["omitted_chapters"] or [u["source_chapter_ids"] for u in plan["units"]] != [[c] for c in project["chapter_ids"]]:
        raise ValueError("轻度改编目录须按原顺序一章对应一章，不合并、拆分、重排或删章")


def light_guide() -> dict:
    return {
        "preset": "light",
        "creation": 'create_adaptation(mode="adaptation", brief.preset="light")；明确选择原章，target_units 等于所选章节数，支持 1–4000 章。仍使用现有框架、分析、方案、写作、审查与冻结工具。',
        "default_scope": ["人物姓名、别名与称谓", "地点名称及关联场所", "由改名牵连的机构名称与取名解释"],
        "optional_scope": "内容删减和中性承接修补按用户的读者与内容约定执行。用户明确只改某一类名称时，按该限定，不扩大范围。",
        "workflow": LIGHT_INSTRUCTIONS,
        "mapping_fields": {"characters": "framework.characters", "locations_and_related_groups": "framework.setting_mappings；机构与地点分别说明", "main_settings": "framework.locations；仅列主要场景"},
        "review_checks": {"locations": "名称、别名、隶属、方位、距离、路线与关联场所一致", "content_suitability": "遵守已约定的内容删减范围，检查章题及回指；未约定删减时说明适用边界", "causality_and_continuity": "沿用 causality/continuity，检查删减前因、执行步骤、结果、晋升与转场"},
        "enforcement": "后端校验章节数与一对一目录，并要求当前稿件完整分块覆盖及两项显式审查。命名是否合理、删减是否完整、叙事是否连贯仍由 Agent 按正文证据判断；没有自动净化或语义质量保证。",
        "schemas": ["brief", "framework", "analysis", "plan", "write", "review"],
    }
