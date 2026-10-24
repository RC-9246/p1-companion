"""Memoria 做梦系统"""

from __future__ import annotations

import asyncio
import hashlib
from ..privacy import memory_safe, scrub_credentials
import json
import logging
import re
import time
from typing import TYPE_CHECKING

from .utils import compact_memory_content, normalize_memory_type, session_memory_user_id, relationship_memory_user_id

if TYPE_CHECKING:
    from .db import MemoriaDB

logger = logging.getLogger("memoria.dream")

DREAM_PROMPT_TEMPLATE = (
    "你是 AstrBot 的长期记忆整理器。请分析对象 {owner}（范围：{scope}）的聊天记录，"
    "提取稳定、有用、未来可帮助回复的长期记忆。\n"
    "只记录对个性化有帮助的事实、偏好、项目、限制、习惯和长期目标。"
    "不要记录一次性闲聊、敏感隐私推断、密码、token、身份证、银行卡、精确住址。\n"
    "如果信息不确定，降低 confidence。短期事件请写明时效性。"
    "输出必须是 JSON 数组，不要 Markdown，不要解释。\n"
    '每项格式：{{"memory_type":"preference|profile|project|constraint|habit|summary|note'
    '|style_preference|conversation_habit|humor_preference|response_length_preference'
    '|topic_interest","content":"一句中文记忆","confidence":0.0到1.0,"reason":"来源依据"}}\n\n'
    "聊天记录：\n{transcript}"
)


def parse_dream_candidates(text: str) -> list[dict]:
    raw = text.strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if m:
        raw = m.group(1).strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end < 0:
        raise ValueError("做梦结果缺少 JSON 数组")
    arr = json.loads(raw[start:end + 1])
    if not isinstance(arr, list):
        raise ValueError("做梦结果不是数组")
    out = []
    for item in arr:
        out.append({
            "memory_type": normalize_memory_type(item.get("memory_type", "note")),
            "content": str(item.get("content", "")).strip(),
            "confidence": max(0.0, min(1.0, float(item.get("confidence", 0.5)))),
            "reason": str(item.get("reason", "")),
        })
    return out


def build_dream_prompt(owner: str, scope: str, transcript: str) -> str:
    return DREAM_PROMPT_TEMPLATE.format(owner=owner, scope=scope, transcript=transcript)


async def _fetch_transcript_from_db(
    astrbot_db_path: str, session_id: str, user_id: str, scope: str, max_messages: int,
) -> list[str]:
    """Fetch conversation history from AstrBot's conversations table."""
    import aiosqlite
    lines: list[str] = []
    try:
        async with aiosqlite.connect(astrbot_db_path) as db:
            qualified = str(session_id)
            if ":" not in qualified:
                qualified = "qq_snowluma:FriendMessage:" + qualified
            if not qualified.startswith("qq_snowluma:FriendMessage:"):
                return []
            rows = await db.execute_fetchall(
                "SELECT content FROM conversations WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
                (qualified, max_messages),
            )
            for row in reversed(rows):
                content = row[0]
                if isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except (json.JSONDecodeError, TypeError):
                        continue
                if not isinstance(content, list):
                    continue
                for msg in content[-max_messages:]:
                    if not isinstance(msg, dict):
                        continue
                    role = msg.get("role", "user")
                    text = msg.get("content", "")
                    if isinstance(text, list):
                        text = " ".join(
                            p.get("text", "") for p in text if isinstance(p, dict)
                        )
                    if text:
                        text = scrub_credentials(str(text)).replace("\n", " ")[:500]
                        lines.append(f"[{role}] {text}")
    except Exception as e:
        logger.warning(f"Failed to fetch transcript from AstrBot DB: {type(e).__name__}")
    return lines[-max_messages:]


async def run_dream_for_user(
    db: "MemoriaDB",
    astrbot_db_path: str,
    user_id: str,
    scope: str,
    source_session: str,
    max_messages: int,
    bypass_activity: bool,
    llm_caller,
    auto_accept: bool,
) -> int:
    logger.info(
        f"[Dream] start user=redacted scope={scope} "
        f"session=redacted max_msgs={max_messages}"
    )
    if not bypass_activity and scope in ("session", "relationship"):
        activity = await db.session_activity_count(source_session)
        if activity < 20:
            raise ValueError(f"会话活跃度不足：当前 {activity}，需要至少 20 次 AI 互动")

    if re.fullmatch(r'v1:[0-9a-f]{64}',str(source_session)):
        transcript=await db.private_transcript(source_session,max_messages)
    else:
        transcript = await _fetch_transcript_from_db(
            astrbot_db_path, source_session, user_id, scope, max_messages,
        )
    if not transcript:
        raise ValueError("没有可分析的历史消息")

    if scope == "session":
        owner = session_memory_user_id(source_session)
        memory_scope = "session"
        memory_scope_id = source_session
    elif scope == "global_user":
        owner = user_id
        memory_scope = "global_user"
        memory_scope_id = user_id
    elif scope == "relationship":
        owner = relationship_memory_user_id(user_id, source_session)
        memory_scope = "relationship"
        memory_scope_id = source_session
    else:
        owner = user_id
        memory_scope = "user"
        memory_scope_id = source_session

    prompt = build_dream_prompt("current-authorized-user", memory_scope, "\n".join(transcript))
    logger.info(
        f"[Dream] prompt built owner=redacted "
        f"lines={len(transcript)} chars={len(prompt)}"
    )

    reply = await llm_caller(prompt)
    logger.info(f"[Dream] LLM response chars={len(reply)}")

    candidates = parse_dream_candidates(reply)
    logger.info(f"[Dream] parsed {len(candidates)} candidates")

    status = "active" if auto_accept else "candidate"
    written = 0
    for c in candidates:
        if not memory_safe(c["content"]) or c["confidence"] < 0.35:
            continue
        await db.add_memory(
            owner, memory_scope, memory_scope_id,
            c["memory_type"], c["content"], c["confidence"],
            "dream", status,
        )
        written += 1

    logger.info(f"[Dream] done owner=redacted status={status} written={written}")
    return written


async def auto_dream_loop(
    db: "MemoriaDB",
    astrbot_db_path: str,
    config_getter,
    llm_caller_factory,
    send_text_caller,
):
    """Background auto-dream loop. Runs forever."""
    while True:
        try:
            cfg = config_getter()
            scan_secs = max(60, min(86400, cfg.get("auto_dream_scan_secs", 300)))
            await asyncio.sleep(scan_secs)
            cfg = config_getter()
            if not cfg.get("enabled", True) or not cfg.get("auto_dream_enabled", True):
                continue
            now = int(time.time())
            idle_before = now - max(60, cfg.get("auto_dream_idle_secs", 900))
            dream_before = now - max(300, cfg.get("auto_dream_min_interval_secs", 21600))
            min_activity = max(0, cfg.get("min_dream_activity", 20))
            max_per_scan = max(1, min(20, cfg.get("auto_dream_max_sessions_per_scan", 2)))
            sessions = await db.get_dreamable_sessions(
                min_activity, idle_before, dream_before, max_per_scan,
            )
            if not sessions:
                continue
            for session_id, _activity, _last_interaction in sessions:
                if hashlib.sha256(str(session_id).encode()).hexdigest() not in set(cfg.get("_p1_allowed_sessions", [])):
                    continue
                await db.mark_dream_scheduled(session_id)
                owner = session_memory_user_id(session_id)
                max_msgs = max(20, min(1000, cfg.get("max_dream_messages", 160)))
                auto_accept = cfg.get("auto_accept_dream", False)
                try:
                    llm_caller = llm_caller_factory(cfg)
                    count = await run_dream_for_user(
                        db, astrbot_db_path, owner, "session", session_id,
                        max_msgs, False, llm_caller, auto_accept,
                    )
                    logger.info(
                        f"[AutoDream] finished session=redacted candidates={count}"
                    )
                except Exception as e:
                    logger.warning(f"[AutoDream] failed session=redacted: {type(e).__name__}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[AutoDream] scan error: {type(e).__name__}")
