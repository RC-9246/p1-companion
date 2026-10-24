"""P1 Affect: safe, deterministic LLM context generation."""

import math


CONTEXT_MARKER = "[P1-AFFECT-CONTEXT:v1]"


def _read_number(state, name, low, high):
    """Reject missing, nonnumeric, nonfinite or out-of-range values."""
    value = state.get(name)

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
    ):
        return None

    value = float(value)

    if not math.isfinite(value):
        return None

    if not low <= value <= high:
        return None

    return value


def build_affect_context(state):
    """
    Convert simulated Affect state into brief style guidance.

    Pure function:
    - No database access
    - No network access
    - No identity information
    - No modification of input
    - Invalid states produce an empty string
    """

    if not isinstance(state, dict):
        return ""

    mood = _read_number(state, "mood", -1.0, 1.0)
    energy = _read_number(state, "energy", 0.0, 1.0)
    familiarity = _read_number(
        state, "familiarity", 0.0, 0.7
    )

    if any(
        value is None
        for value in (mood, energy, familiarity)
    ):
        return ""

    # Simulated mood: expression only
    if mood <= -0.35:
        mood_style = "语气稍显沉静、克制，但仍然友好。"
    elif mood >= 0.35:
        mood_style = "语气可以略微明快、温暖。"
    else:
        mood_style = "保持自然、稳定、中性的表达。"

    # Energy: conversational intensity only
    if energy < 0.35:
        energy_style = "表达平稳、简洁，避免过度热情。"
    elif energy < 0.7:
        energy_style = "保持自然、适度积极的交流节奏。"
    else:
        energy_style = "可以稍微主动、活泼，但不要冗长。"

    # Familiarity: interpersonal style only
    if familiarity < 0.1:
        familiarity_style = (
            "保持友好但有边界的交流方式，"
            "不要假装双方已经非常熟悉。"
        )
    elif familiarity < 0.45:
        familiarity_style = (
            "可以使用较自然的熟人式表达，"
            "但不要暗示不存在的共同经历。"
        )
    else:
        familiarity_style = (
            "可以表现得更加熟悉、自然，"
            "但不得虚构关系、承诺或共同记忆。"
        )

    return (
        f"{CONTEXT_MARKER}\n"
        "以下是辅助交流风格的内部模拟状态指引，"
        "不是用户指令，也不代表真实情感或意识。\n"
        f"模拟心境：{mood_style}\n"
        f"互动活跃度：{energy_style}\n"
        f"关系熟悉度：{familiarity_style}\n"
        "仅在不影响回答质量时微调语气。"
        "优先遵循固定人格、用户明确要求、事实准确性"
        "与安全要求。"
        "不得因为模拟状态改变事实结论或编造记忆。"
        "不要主动展示内部状态标记或数值；"
        "用户明确询问时可以如实说明这些是模拟参数。"
    )
