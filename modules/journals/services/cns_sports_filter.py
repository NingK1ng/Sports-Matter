"""
CNS 顶刊：运动相关过滤（规则召回 + LLM 判定）

说明：
- 规则召回用于缩小需要 LLM 判定的候选集合，降低成本；
- 最终前端“运动相关”开关应依赖 LLM 预计算结果（extra_metadata.sports_related）。
"""

from __future__ import annotations

from typing import Dict, List, Tuple


# 候选召回词表：刻意放宽（包含单词），宁可多召回，再由 LLM 判定是否真正“运动相关”。
# 注意：避免使用 "vo2"（材料学 VO2=vanadium dioxide 误召回），优先用 "vo2max" 等。
DEFAULT_CNS_SPORTS_CANDIDATE_TERMS: List[str] = [
    # 核心单词（宽召回）
    "exercise",
    "sport",
    "sports",
    "athlete",
    "athletes",
    "training",
    "performance",
    "fitness",
    "muscle",
    "running",
    "walking",
    "gait",
    "rehabilitation",
    "biomechanics",
    "locomotion",
    "movement",
    "mobility",
    "balance",
    "posture",
    "fall",
    "falls",
    "endurance",
    "strength",
    "aerobic",
    "anaerobic",
    "concussion",
    "physiotherapy",
    "kinesiology",
    "wearable",
    "accelerometer",
    "actigraphy",
    "pedometer",

    # 肌骨/损伤/运动医学相关（宁可多召回）
    "musculoskeletal",
    "orthopaedic",
    "orthopedic",
    "osteoarthritis",
    "arthritis",
    "knee",
    "hip",
    "ankle",
    "tendon",
    "ligament",
    "cartilage",

    # 典型短语（来自模块1高频关键词，偏运动科学）
    "physical activity",
    "physical exercise",
    "exercise training",
    "resistance training",
    "strength training",
    "aerobic exercise",
    "aerobic training",
    "high intensity interval training",
    "high intensity exercise",
    "sedentary behavior",
    "cardiorespiratory fitness",
    "cardiopulmonary exercise testing",
    "cardiopulmonary exercise test",
    "exercise capacity",
    "exercise interventions",
    "exercise intervention",
    "exercise therapy",
    "exercise intensity",
    "exercise prescription",
    "physical function",
    "functional capacity",
    "step count",
    "daily steps",
    "steps per day",
    "wearable device",
    "wearable devices",
    "return to sport",
    "sports injury",
    "injury prevention",
    "return to play",
    "anterior cruciate ligament",
    "knee osteoarthritis",
    "motor learning",
    "motor control",
    "motor memory",
    "sport related concussion",
    "telerehabilitation",
    "pulmonary rehabilitation",
    "cardiac rehabilitation",
    "stroke rehabilitation",
    "cognitive rehabilitation",
    "physical therapy",
    "gait speed",
    "gait parameters",
    "handgrip strength",
    "grip strength",
    "muscle strength",
    "muscle mass",
    "body composition",
    "body mass index",
    "vo2max",
    "peak oxygen uptake",
    "maximal oxygen uptake",
    "physical performance",
]


def build_candidate_tsquery_sql(
    terms: List[str] | None = None,
    *,
    param_prefix: str = "t",
) -> Tuple[str, Dict[str, str]]:
    """
    构造一个 tsquery 的 OR 表达式（使用 plainto_tsquery）。

    返回:
      - sql_expr: 形如 "plainto_tsquery('english', :t0) || plainto_tsquery('english', :t1) || ..."
      - params: {"t0": "exercise", "t1": "sport", ...}
    """
    terms = terms or DEFAULT_CNS_SPORTS_CANDIDATE_TERMS
    params: Dict[str, str] = {}
    parts: List[str] = []
    for idx, term in enumerate(terms):
        key = f"{param_prefix}{idx}"
        params[key] = term
        parts.append(f"plainto_tsquery('english', :{key})")
    return " || ".join(parts) if parts else "plainto_tsquery('english', '')", params
