"""P1 Affect: authorized, read-only LLM context hook."""

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path

from astrbot.api import logger

from .identity import identity_from_event
from .llm_injection import inject_affect_context


def read_affect_state(database, identity_key):
    """
    Read only the matching user's state.

    - SQLite read-only mode
    - Parameterized query
    - No creation of missing user records
    - No mutation of database
    """

    path = Path(database)

    with closing(
        sqlite3.connect(
            f"file:{path}?mode=ro",
            uri=True,
            timeout=5.0,
        )
    ) as conn:
        row = conn.execute(
            """
            SELECT mood, energy, familiarity
            FROM affect_state
            WHERE identity_key = ?
            """,
            (identity_key,),
        ).fetchone()

    if row is None:
        return None

    return {
        "mood": row[0],
        "energy": row[1],
        "familiarity": row[2],
    }


async def try_inject_affect(
    event,
    request,
    is_allowed,
    database,
):
    """
    Inject Affect only for authorized QQ private chats.

    Returns True only when a new context part is appended.
    Failure is nonfatal and does not block the LLM request.
    """

    try:
        # 1. Accept only the explicitly configured QQ platform.
        if event.get_platform_id() != "qq_snowluma":
            return False

        # 2. Match the existing persisted identity.
        identity_key = identity_from_event(event)

        # The caller provides the existing strict allowlist check.
        if not is_allowed(identity_key):
            return False

        # 3. Reject group messages and other message types.
        if not event.is_private_chat():
            return False

        # Reject unsupported requests before database access.
        parts = getattr(
            request,
            "extra_user_content_parts",
            None,
        )

        if not isinstance(parts, list):
            return False

        # 4. Read matching state without blocking event loop.
        state = await asyncio.to_thread(
            read_affect_state,
            database,
            identity_key,
        )

        if state is None:
            return False

        # 5. Append one temporary context, without modifying
        # system_prompt, prompt or previous context parts.
        return inject_affect_context(request, state)

    except Exception as exc:
        # Never expose QQ IDs, message text or identity hashes.
        logger.warning(
            "[P1 Affect] LLM context skipped: "
            f"{type(exc).__name__}"
        )
        return False
