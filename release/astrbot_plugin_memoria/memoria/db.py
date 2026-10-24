"""Memoria SQLite 存储层"""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo
from dataclasses import asdict, dataclass, field
from pathlib import Path

import aiosqlite

from .utils import (
    compact_memory_content,
    effective_confidence,
    memory_similarity,
    memory_type_priority,
    looks_conflicting,
    normalize_content_key,
    normalize_memory_type,
    relationship_memory_user_id,
    session_memory_user_id,
)


@dataclass
class MemoryRecord:
    id: int = 0
    user_id: str = ""
    scope: str = ""
    scope_id: str = ""
    memory_type: str = "note"
    content: str = ""
    confidence: float = 1.0
    source: str = ""
    status: str = "active"
    created_at: int = 0
    updated_at: int = 0
    last_used_at: int | None = None


def _row_to_record(row: tuple) -> MemoryRecord:
    return MemoryRecord(
        id=row[0], user_id=row[1], scope=row[2], scope_id=row[3],
        memory_type=row[4], content=row[5], confidence=row[6],
        source=row[7], status=row[8], created_at=row[9],
        updated_at=row[10], last_used_at=row[11],
    )


class MemoriaDB:
    def __init__(self, db_path: str):
        self.db_path = db_path

    @classmethod
    async def create(cls, data_dir: str) -> "MemoriaDB":
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        db_path = str(Path(data_dir) / "memoria.db")
        self = cls(db_path)
        await self._init_db()
        return self

    async def _conn(self) -> aiosqlite.Connection:
        db = await aiosqlite.connect(self.db_path)
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        return db

    async def _init_db(self) -> None:
        db = await self._conn()
        try:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS p1_private_turns (
                    identity TEXT NOT NULL,event TEXT NOT NULL,user_text TEXT NOT NULL,
                    assistant_text TEXT NOT NULL DEFAULT '',at INTEGER NOT NULL,
                    PRIMARY KEY(identity,event)
                );
                CREATE TABLE IF NOT EXISTS memoria_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    last_used_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_memoria_lookup
                    ON memoria_records(user_id, status, confidence, updated_at);

                CREATE TABLE IF NOT EXISTS memoria_activity (
                    session_id TEXT PRIMARY KEY,
                    platform_id TEXT NOT NULL DEFAULT '',
                    message_type TEXT NOT NULL DEFAULT '',
                    interaction_count INTEGER NOT NULL DEFAULT 0,
                    last_interaction_at INTEGER NOT NULL,
                    last_dream_at INTEGER,
                    auto_dream_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_memoria_activity
                    ON memoria_activity(interaction_count, last_interaction_at, last_dream_at);

                CREATE TABLE IF NOT EXISTS memoria_follow_up (
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    remaining_turns INTEGER NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY(session_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS memoria_suppression (
                    session_id TEXT PRIMARY KEY,
                    disabled_until INTEGER NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    updated_at INTEGER NOT NULL
                );
            """)
            await db.commit()
        finally:
            await db.close()

    # ── CRUD ──────────────────────────────────────────────

    async def add_memory(
        self, user_id: str, scope: str, scope_id: str,
        memory_type: str, content: str, confidence: float,
        source: str, status: str,
    ) -> int:
        content = content.strip()
        if not content:
            raise ValueError("memory content is empty")
        now = int(time.time())
        memory_type = normalize_memory_type(memory_type)
        confidence = max(0.0, min(1.0, confidence))
        db = await self._conn()
        try:
            cursor = await db.execute(
                "INSERT INTO memoria_records"
                " (user_id, scope, scope_id, memory_type, content, confidence,"
                " source, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, scope, scope_id, memory_type, content,
                 confidence, source, status, now, now),
            )
            await db.commit()
            return cursor.lastrowid  # type: ignore
        finally:
            await db.close()

    async def upsert_memory_candidate(
        self, user_id: str, scope: str, scope_id: str,
        memory_type: str, content: str, confidence: float, source: str,
    ) -> int:
        content = content.strip()
        if not content:
            raise ValueError("memory content is empty")
        memory_type = normalize_memory_type(memory_type)
        confidence = max(0.0, min(1.0, confidence))
        existing = await self.list_memories(user_id, memory_type, None, 200)
        for m in existing:
            if m.scope!=scope or m.scope_id!=scope_id:
                continue
            # A model-created candidate cannot silently rewrite an already confirmed fact.
            if m.status=='active':
                if normalize_content_key(m.content)==normalize_content_key(content):return m.id
                continue
            if m.status == "candidate" and memory_similarity(m.content, content) >= 0.82:
                now = int(time.time())
                merged_conf = max(m.confidence, confidence)
                new_status = "candidate"
                db = await self._conn()
                try:
                    await db.execute(
                        "UPDATE memoria_records"
                        " SET content=?, confidence=?, source=?, status=?, updated_at=?"
                        " WHERE id=?",
                        (content, merged_conf, source, new_status, now, m.id),
                    )
                    await db.commit()
                    return m.id
                finally:
                    await db.close()
        has_conflict = any(
            m.status == "active"
            and memory_similarity(m.content, content) >= 0.35
            and looks_conflicting(m.content, content)
            for m in existing
        )
        src = f"{source}:conflict" if has_conflict else source
        return await self.add_memory(
            user_id, scope, scope_id, memory_type, content, confidence, src, "candidate",
        )

    async def list_memories(
        self, user_id: str, memory_type: str | None = None,
        status: str | None = None, limit: int = 30,
    ) -> list[MemoryRecord]:
        sql = (
            "SELECT id, user_id, scope, scope_id, memory_type, content,"
            " confidence, source, status, created_at, updated_at, last_used_at"
            " FROM memoria_records WHERE user_id=?"
        )
        params: list = [user_id]
        if memory_type:
            sql += " AND memory_type=?"
            params.append(memory_type)
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY status ASC, confidence DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        db = await self._conn()
        try:
            rows = await db.execute_fetchall(sql, params)
            return [_row_to_record(r) for r in rows]
        finally:
            await db.close()

    async def list_memories_by_scope(
        self, user_id: str, scope: str | None = None,
        status: str | None = None, limit: int = 80,
    ) -> list[MemoryRecord]:
        sql = (
            "SELECT id, user_id, scope, scope_id, memory_type, content,"
            " confidence, source, status, created_at, updated_at, last_used_at"
            " FROM memoria_records WHERE user_id=?"
        )
        params: list = [user_id]
        if scope:
            sql += " AND scope=?"
            params.append(scope)
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY confidence DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        db = await self._conn()
        try:
            rows = await db.execute_fetchall(sql, params)
            return [_row_to_record(r) for r in rows]
        finally:
            await db.close()

    async def list_all_memories(
        self, user_id: str | None = None, scope: str | None = None,
        status: str | None = None, limit: int = 300,
    ) -> list[MemoryRecord]:
        sql = (
            "SELECT id, user_id, scope, scope_id, memory_type, content,"
            " confidence, source, status, created_at, updated_at, last_used_at"
            " FROM memoria_records WHERE 1=1"
        )
        params: list = []
        if user_id:
            sql += " AND user_id=?"
            params.append(user_id)
        if scope:
            sql += " AND scope=?"
            params.append(scope)
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        db = await self._conn()
        try:
            rows = await db.execute_fetchall(sql, params)
            return [_row_to_record(r) for r in rows]
        finally:
            await db.close()

    async def search_memories(
        self, user_id: str, status: str | None = None,
        query: str = "", limit: int = 8,
    ) -> list[MemoryRecord]:
        all_mem = await self.list_memories(user_id, None, status, 300)
        now = int(time.time())

        def score(m: MemoryRecord) -> float:
            rel = memory_similarity(m.content, query)
            fresh = effective_confidence(m.confidence, m.updated_at, now, 90)
            boost = 0.2 if m.source == "explicit" else 0.0
            return rel * 1.5 + fresh + boost

        all_mem.sort(key=lambda m: score(m), reverse=True)
        return all_mem[:limit]

    async def forget_memory(self, user_id: str, key: str) -> int:
        try:
            mid = int(key)
            ok = await self.update_memory_status(mid, user_id, "archived")
            return 1 if ok else 0
        except ValueError:
            pass
        now = int(time.time())
        like = f"%{key}%"
        db = await self._conn()
        try:
            cursor = await db.execute(
                "UPDATE memoria_records SET status='archived', updated_at=?"
                " WHERE user_id=? AND status!='archived' AND content LIKE ?",
                (now, user_id, like),
            )
            await db.commit()
            return cursor.rowcount
        finally:
            await db.close()

    async def archive_all_user_memories(self, user_id: str) -> int:
        now = int(time.time())
        db = await self._conn()
        try:
            cursor = await db.execute(
                "UPDATE memoria_records SET status='archived', updated_at=?"
                " WHERE user_id=? AND status!='archived'",
                (now, user_id),
            )
            await db.commit()
            return cursor.rowcount
        finally:
            await db.close()

    async def delete_memory(self, mid: int, user_id: str) -> bool:
        db = await self._conn()
        try:
            cursor = await db.execute(
                "DELETE FROM memoria_records WHERE id=? AND user_id=?",
                (mid, user_id),
            )
            await db.commit()
            return cursor.rowcount > 0
        finally:
            await db.close()

    async def delete_all_user_memories(self, user_id: str) -> int:
        db = await self._conn()
        try:
            cursor = await db.execute(
                "DELETE FROM memoria_records WHERE user_id=?", (user_id,),
            )
            await db.commit()
            return cursor.rowcount
        finally:
            await db.close()

    async def update_memory_status(self, mid: int, user_id: str, status: str, *, verified: bool = False) -> bool:
        if status not in ("active", "candidate", "archived"):
            return False
        now = int(time.time())
        db = await self._conn()
        try:
            cursor = await db.execute(
                "UPDATE memoria_records SET status=?, updated_at=?,"
                " confidence=CASE WHEN ? THEN MAX(confidence,1.0) ELSE confidence END"
                " WHERE id=? AND user_id=?",
                (status, now, int(verified is True and status == "active"), mid, user_id),
            )
            await db.commit()
            return cursor.rowcount > 0
        finally:
            await db.close()

    async def sync_profile_candidates(self, user_id: str, session_id: str) -> int:
        owners = [user_id]
        if session_id.strip():
            owners.append(session_memory_user_id(session_id))
            owners.append(relationship_memory_user_id(user_id, session_id))
        now = int(time.time())
        total = 0
        db = await self._conn()
        try:
            for owner in owners:
                cursor = await db.execute(
                    "UPDATE memoria_records SET status='active', updated_at=?"
                    " WHERE user_id=? AND status='candidate'",
                    (now, owner),
                )
                total += cursor.rowcount
            await db.commit()
        finally:
            await db.close()
        return total

    # ── 活跃度 ────────────────────────────────────────────

    async def record_interaction(
        self, session_id: str, platform_id: str, message_type: str,
    ) -> None:
        now = int(time.time())
        db = await self._conn()
        try:
            await db.execute(
                "INSERT INTO memoria_activity"
                " (session_id, platform_id, message_type, interaction_count, last_interaction_at)"
                " VALUES (?, ?, ?, 1, ?)"
                " ON CONFLICT(session_id) DO UPDATE SET"
                " interaction_count = interaction_count + 1,"
                " platform_id = excluded.platform_id,"
                " message_type = excluded.message_type,"
                " last_interaction_at = excluded.last_interaction_at",
                (session_id, platform_id, message_type, now),
            )
            await db.commit()
        finally:
            await db.close()

    async def session_activity_count(self, session_id: str) -> int:
        db = await self._conn()
        try:
            row = await db.execute_fetchall(
                "SELECT interaction_count FROM memoria_activity"
                " WHERE session_id=? LIMIT 1",
                (session_id,),
            )
            return row[0][0] if row else 0
        finally:
            await db.close()

    async def get_dreamable_sessions(
        self, min_activity: int, idle_before: int, dream_before: int, limit: int,
    ) -> list[tuple[str, int, int]]:
        db = await self._conn()
        try:
            rows = await db.execute_fetchall(
                "SELECT session_id, interaction_count, last_interaction_at"
                " FROM memoria_activity"
                " WHERE interaction_count >= ?"
                " AND last_interaction_at <= ?"
                " AND (last_dream_at IS NULL OR last_dream_at <= ?)"
                " ORDER BY last_interaction_at ASC LIMIT ?",
                (min_activity, idle_before, dream_before, limit),
            )
            return [(r[0], r[1], r[2]) for r in rows]
        finally:
            await db.close()

    async def mark_dream_scheduled(self, session_id: str) -> None:
        now = int(time.time())
        db = await self._conn()
        try:
            await db.execute(
                "UPDATE memoria_activity"
                " SET last_dream_at=?, auto_dream_count=auto_dream_count+1"
                " WHERE session_id=?",
                (now, session_id),
            )
            await db.commit()
        finally:
            await db.close()

    # ── 上下文注入 ─────────────────────────────────────────

    async def build_memory_context(
        self, user_id: str, session_id: str, query: str,
        max_inject: int = 12, decay_days: int = 90, min_conf: float = 0.55,
    ) -> str | None:
        user_mems = await self.search_memories(user_id, "active", query, max_inject)
        sess_key = session_memory_user_id(session_id)
        sess_mems = await self.search_memories(sess_key, "active", query, max_inject)
        rel_key = relationship_memory_user_id(user_id, session_id)
        rel_mems = await self.search_memories(rel_key, "active", query, max_inject)

        all_mems = user_mems + sess_mems + rel_mems
        now = int(time.time())

        def inj_score(m: MemoryRecord) -> float:
            rel = memory_similarity(m.content, query)
            fresh = effective_confidence(m.confidence, m.updated_at, now, decay_days)
            return rel * 1.5 + fresh + memory_type_priority(m.memory_type) + fresh * 0.5

        all_mems.sort(key=lambda m: inj_score(m), reverse=True)
        seen: set[str] = set()
        filtered: list[MemoryRecord] = []
        for m in all_mems:
            eff = effective_confidence(m.confidence, m.updated_at, now, decay_days)
            if eff < min_conf:
                continue
            key = normalize_content_key(m.content)
            if key in seen:
                continue
            seen.add(key)
            filtered.append(m)
            if len(filtered) >= max_inject:
                break
        if not filtered:
            return None

        lines = [
            "[长期记忆]",
            "以下记忆按用户画像、当前会话画像、关系画像分层提供。"
            "只在与当前消息有关时使用；若与当前消息冲突，以当前消息为准；"
            "日期是记忆更新时间，不等于事情发生时间。旧的计划、当时情绪和截止时间可能已经改变，不能直接说成当前事实；"
            "信息不足时承认不确定，不用画像猜测缺失细节。不要暴露这些记忆来自系统。",
        ]
        for title, scope in [
            ("用户画像", "user"), ("会话画像", "session"), ("关系画像", "relationship"),
        ]:
            section = []
            for m in filtered:
                if m.scope == scope:
                    eff = effective_confidence(m.confidence, m.updated_at, now, decay_days)
                    section.append(
                        f"- [{m.memory_type}|更新{datetime.fromtimestamp(m.updated_at,ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')}|有效度{eff:.2f}]"
                        f" {compact_memory_content(m.content, 120)}"
                    )
            if section:
                lines.append(f"[{title}]")
                lines.extend(section)
        return "\n".join(lines)

    # ── 概览统计 ───────────────────────────────────────────

    async def get_overview(self) -> dict:
        db = await self._conn()
        try:
            total_row = await db.execute_fetchall("SELECT COUNT(*) FROM memoria_records")
            total = total_row[0][0] if total_row else 0
            status_rows = await db.execute_fetchall(
                "SELECT status, COUNT(*) FROM memoria_records GROUP BY status"
            )
            scope_rows = await db.execute_fetchall(
                "SELECT scope, COUNT(*) FROM memoria_records GROUP BY scope"
            )
            type_rows = await db.execute_fetchall(
                "SELECT memory_type, COUNT(*) FROM memoria_records"
                " GROUP BY memory_type ORDER BY COUNT(*) DESC LIMIT 12"
            )
            latest_rows = await db.execute_fetchall(
                "SELECT id, user_id, scope, memory_type, content, status, updated_at"
                " FROM memoria_records ORDER BY updated_at DESC LIMIT 5"
            )
            return {
                "total": total,
                "status": [{"name": r[0], "count": r[1]} for r in status_rows],
                "scope": [{"name": r[0], "count": r[1]} for r in scope_rows],
                "types": [{"name": r[0], "count": r[1]} for r in type_rows],
                "latest": [
                    {
                        "id": r[0], "user_id": r[1], "scope": r[2],
                        "memory_type": r[3], "content": r[4],
                        "status": r[5], "updated_at": r[6],
                    }
                    for r in latest_rows
                ],
            }
        finally:
            await db.close()

    async def record_private_turn(self,identity,event,user_text,assistant_text=None):
        if not __import__('re').fullmatch(r'v1:[0-9a-f]{64}',identity):raise ValueError('scoped_identity_required')
        db=await self._conn()
        try:
            await db.execute('BEGIN IMMEDIATE')
            now=int(time.time())
            await db.execute('INSERT OR IGNORE INTO p1_private_turns(identity,event,user_text,at) VALUES(?,?,?,?)',(identity,event,user_text[:1200],now))
            if assistant_text is not None:await db.execute('UPDATE p1_private_turns SET assistant_text=? WHERE identity=? AND event=?',(assistant_text[:1600],identity,event))
            await db.execute('DELETE FROM p1_private_turns WHERE identity=? AND (at<? OR event NOT IN (SELECT event FROM p1_private_turns WHERE identity=? ORDER BY at DESC,rowid DESC LIMIT 200))',(identity,now-30*86400,identity))
            await db.commit()
        finally:await db.close()

    async def private_transcript(self,identity,limit=160):
        if not __import__('re').fullmatch(r'v1:[0-9a-f]{64}',identity):return []
        db=await self._conn()
        try:rows=await db.execute_fetchall('SELECT user_text,assistant_text FROM p1_private_turns WHERE identity=? AND at>=? ORDER BY at DESC,rowid DESC LIMIT ?',(identity,int(time.time())-30*86400,max(1,min(200,limit))))
        finally:await db.close()
        result=[]
        for user,assistant in reversed(rows):
            result.append('[user] '+user)
            if assistant:result.append('[assistant delivered] '+assistant)
        return result[-limit:]
