"""Memoria 工具函数"""

VALID_MEMORY_TYPES = frozenset([
    "preference", "profile", "project", "constraint", "habit",
    "summary", "note", "style_preference", "conversation_habit",
    "humor_preference", "response_length_preference", "topic_interest",
])

TYPE_PRIORITY = {
    "profile": 0.35,
    "style_preference": 0.34,
    "response_length_preference": 0.33,
    "preference": 0.3,
    "constraint": 0.28,
    "conversation_habit": 0.26,
    "project": 0.25,
    "humor_preference": 0.2,
    "topic_interest": 0.2,
    "habit": 0.18,
    "summary": 0.12,
    "note": 0.0,
}

POSITIVE_WORDS = ["喜欢", "偏好", "需要", "使用", "开启", "同意"]
NEGATIVE_WORDS = ["不喜欢", "讨厌", "不要", "不需要", "不用", "关闭", "禁止", "不同意"]


def session_memory_user_id(session_id: str) -> str:
    return f"session:{session_id}"


def relationship_memory_user_id(user_id: str, session_id: str) -> str:
    return f"relationship:{user_id}:{session_id}"


def normalize_memory_type(t: str) -> str:
    return t if t in VALID_MEMORY_TYPES else "note"


def memory_type_priority(t: str) -> float:
    return TYPE_PRIORITY.get(t, 0.0)


def compact_memory_content(content: str, max_chars: int = 120) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "…"


def normalize_content_key(content: str) -> str:
    return "".join(
        ch for ch in content if not ch.isspace() and not (ch.isascii() and not ch.isalnum())
    ).lower()


def memory_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    ascii_buf = []
    for ch in text:
        if ch.isascii() and ch.isalnum():
            ascii_buf.append(ch.lower())
            continue
        if len(ascii_buf) >= 2:
            tokens.add("".join(ascii_buf))
        ascii_buf.clear()
        if not ch.isspace() and not (ch.isascii() and not ch.isalnum()):
            tokens.add(ch)
    if len(ascii_buf) >= 2:
        tokens.add("".join(ascii_buf))
    return tokens


def memory_similarity(a: str, b: str) -> float:
    ta = memory_tokens(a)
    tb = memory_tokens(b)
    if not ta or not tb:
        return 0.0
    overlap = len(ta & tb)
    union = len(ta) + len(tb) - overlap
    return overlap / union if union > 0 else 0.0


def looks_conflicting(a: str, b: str) -> bool:
    a_pos = any(w in a for w in POSITIVE_WORDS)
    b_pos = any(w in b for w in POSITIVE_WORDS)
    a_neg = any(w in a for w in NEGATIVE_WORDS)
    b_neg = any(w in b for w in NEGATIVE_WORDS)
    return (a_pos and b_neg) or (a_neg and b_pos)


def effective_confidence(confidence: float, updated_at: int, now: int, decay_days: int) -> float:
    age_days = max(0, now - updated_at) / 86400.0
    decay = 0.5 ** (age_days / max(1, decay_days))
    return max(0.0, min(1.0, confidence * decay))


def format_memory_list(title: str, memories: list[dict]) -> str:
    if not memories:
        return f"{title}\n暂无记忆。"
    lines = [title]
    for m in memories:
        lines.append(
            f"{m['id']}. [{m['status']}|{m['memory_type']}|{m['confidence']:.2f}] {m['content']}"
        )
    return "\n".join(lines)
