"""Memoria 持续追踪系统"""

from __future__ import annotations

import json
import time

import aiosqlite

FOLLOW_UP_SUPPRESS_SECS = 3600


def build_follow_up_tracking_prompt(max_turns: int = 3) -> str:
    return (
        "[隐式持续追踪判定]\n"
        "每次最终回复的最后一行，必须输出一个内部控制标记：\n"
        f'[[FOLLOW_UP:{{"track":true,"turns":1,"reason":"一句很短的原因"}}]]\n'
        f'或：[[FOLLOW_UP:{{"track":false,"turns":0,"reason":"已结束"}}]]\n'
        f"标记里的 JSON 必须合法，track 只能是 true 或 false，"
        f"turns 是 0 到 {max_turns} 的整数。\n"
        "如果你提出了问题、需要等待用户补充、正在连续排查问题、"
        "或下一句话明显需要接着处理，则 track=true，turns 取 1 到 "
        f"{max_turns}。\n"
        "如果当前回复已经结束话题，或只是普通闲聊回应，则 track=false，turns=0。\n"
        "这个标记不是给用户看的，不要解释它，不要把它放进正文。"
    )


def parse_follow_up_decision_strict(text: str, max_turns: int) -> tuple[str, dict]:
    marker = "[[FOLLOW_UP:"
    start = text.rfind(marker)
    if start < 0:
        return text, {"track": False, "turns": 0, "reason": "missing_control_marker"}
    rest = text[start + len(marker):]
    end_rel = rest.find("]]")
    if end_rel < 0:
        return text, {"track": False, "turns": 0, "reason": "malformed_control_marker"}
    raw = rest[:end_rel].strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return text, {"track": False, "turns": 0, "reason": "invalid_control_json"}
    track = bool(parsed.get("track", False))
    turns = min(int(parsed.get("turns", 0)), max_turns)
    reason = str(parsed.get("reason", ""))[:80]
    cleaned = text[:start].rstrip() + rest[end_rel + 2:].lstrip()
    return cleaned.strip(), {
        "track": track and turns > 0,
        "turns": turns if track else 0,
        "reason": reason,
    }


def strip_follow_up_marker_lossy(text: str) -> str:
    marker = "[[FOLLOW_UP:"
    start = text.rfind(marker)
    if start < 0:
        return text.strip()
    rest = text[start + len(marker):]
    end_rel = rest.find("]]")
    tail = rest[end_rel + 2:] if end_rel >= 0 else ""
    return (text[:start].rstrip() + tail.lstrip()).strip()


def extract_follow_up_decision(text: str, max_turns: int) -> tuple[str, dict]:
    try:
        return parse_follow_up_decision_strict(text, max_turns)
    except Exception:
        return strip_follow_up_marker_lossy(text), {"track": False, "turns": 0, "reason": "error"}


async def store_follow_up_decision(
    db_path: str, session_id: str, user_id: str, decision: dict,
) -> None:
    now = int(time.time())
    async with aiosqlite.connect(db_path) as db:
        if decision.get("track") and decision.get("turns", 0) > 0:
            await db.execute(
                "INSERT INTO memoria_follow_up"
                " (session_id, user_id, remaining_turns, reason, updated_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(session_id, user_id) DO UPDATE SET"
                " remaining_turns=excluded.remaining_turns,"
                " reason=excluded.reason, updated_at=excluded.updated_at",
                (session_id, user_id, decision["turns"],
                 decision.get("reason", ""), now),
            )
        else:
            await db.execute(
                "DELETE FROM memoria_follow_up"
                " WHERE session_id=? AND user_id=?",
                (session_id, user_id),
            )
        await db.commit()


async def consume_follow_up_tracking(
    db_path: str, session_id: str, user_id: str,
) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        rows = await db.execute_fetchall(
            "SELECT remaining_turns, reason FROM memoria_follow_up"
            " WHERE session_id=? AND user_id=? AND remaining_turns>0 LIMIT 1",
            (session_id, user_id),
        )
        if not rows:
            return None
        remaining = rows[0][0]
        reason = rows[0][1]
        next_rem = remaining - 1
        now = int(time.time())
        if next_rem > 0:
            await db.execute(
                "UPDATE memoria_follow_up SET remaining_turns=?, updated_at=?"
                " WHERE session_id=? AND user_id=?",
                (next_rem, now, session_id, user_id),
            )
        else:
            await db.execute(
                "DELETE FROM memoria_follow_up"
                " WHERE session_id=? AND user_id=?",
                (session_id, user_id),
            )
        await db.commit()
        return {"remaining_turns": max(0, remaining), "reason": reason}


async def is_follow_up_suppressed(db_path: str, session_id: str) -> bool:
    now = int(time.time())
    async with aiosqlite.connect(db_path) as db:
        rows = await db.execute_fetchall(
            "SELECT disabled_until FROM memoria_suppression"
            " WHERE session_id=? AND disabled_until>? LIMIT 1",
            (session_id, now),
        )
        return len(rows) > 0


async def suppress_follow_up_for_session(
    db_path: str, session_id: str, reason: str,
) -> None:
    now = int(time.time())
    disabled_until = now + FOLLOW_UP_SUPPRESS_SECS
    reason = reason[:120]
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO memoria_suppression"
            " (session_id, disabled_until, reason, updated_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(session_id) DO UPDATE SET"
            " disabled_until=excluded.disabled_until,"
            " reason=excluded.reason, updated_at=excluded.updated_at",
            (session_id, disabled_until, reason, now),
        )
        await db.commit()
