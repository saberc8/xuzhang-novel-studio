"""Shared, versioned prose rubric. Decisions are made by the reading agent."""
from typing import Literal

QualityDimension = Literal["template_repetition", "redundant_explanation", "precision", "rhythm",
                           "imagery", "dialogue_voice", "subtext", "narrative_restraint"]

DIMENSIONS = {
    "template_repetition": {"label": "模板与重复", "group": "deslop", "category": "prose",
        "instruction": "核对近似段落、套用句式、重复结论和章首章末结构；说明回环、引用或口头禅是否有叙事功能。"},
    "redundant_explanation": {"label": "重复解释", "group": "deslop", "category": "prose",
        "instruction": "检查动作、对白之后的情绪解释、抽象总结和说明书式旁白是否带来新信息；保留必要交代。"},
    "precision": {"label": "用词与具体性", "group": "literary", "category": "prose",
        "instruction": "检查动词、感官细节和名词是否准确具体，抽象情绪是否有可见依据；不为具体而虚构事实。"},
    "rhythm": {"label": "句段节奏", "group": "literary", "category": "prose",
        "instruction": "结合场景速度检查句长、停顿和段落推进，避免机械齐整或无功能的碎句；不采用统一长短句配额。"},
    "imagery": {"label": "意象与修辞", "group": "literary", "category": "prose",
        "instruction": "判断意象是否具体、一致且服务人物或场景，是否重复堆砌、混用比喻；平实叙述不必强加修辞。"},
    "dialogue_voice": {"label": "人物声音", "group": "literary", "category": "dialogue",
        "instruction": "结合人物身份、关系和当下目标比较词汇、句长及回避方式，检查角色是否共用同一种说理声音。"},
    "subtext": {"label": "对白潜台词", "group": "literary", "category": "dialogue",
        "instruction": "检查人物所说、所求与未说之处，是否借行动或反应传达关系；必要的直接表达可以保留。"},
    "narrative_restraint": {"label": "叙述分寸", "group": "literary", "category": "prose",
        "instruction": "检查旁白代替读者判断、机械升华和强行总结；保留叙述者风格、视角边界和信息揭示顺序。"},
}
