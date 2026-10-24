import math
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path


FIELDS = (
    "mood",
    "energy",
    "familiarity",
    "interaction_count",
    "last_interaction_at",
    "updated_at",
)

DEFAULT_STATE = {
    "mood": 0.0,
    "energy": 0.5,
    "familiarity": 0.0,
    "interaction_count": 0,
    "last_interaction_at": 0,
    "updated_at": 0,
}


class AffectStore:
    def __init__(self, db_path):
        self.db_path = Path(db_path)

        if not self.db_path.is_file():
            raise FileNotFoundError(self.db_path)

    @staticmethod
    def validate_key(key):
        if not isinstance(key, str) or not re.fullmatch(
            r"v1:[0-9a-f]{64}", key
        ):
            raise ValueError("Affect: 无效身份键")

    def connect(self):
        conn = sqlite3.connect(
            self.db_path,
            timeout=5.0,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def get_state(self, identity_key):
        self.validate_key(identity_key)

        with closing(self.connect()) as conn:
            row = conn.execute(
                """
                SELECT mood, energy, familiarity,
                       interaction_count,
                       last_interaction_at, updated_at
                FROM affect_state
                WHERE identity_key = ?
                """,
                (identity_key,),
            ).fetchone()

        return dict(row) if row else DEFAULT_STATE.copy()

    def record_interaction(
        self,
        identity_key,
        mood_delta=0.0,
        energy_delta=0.0,
        familiarity_delta=0.0,
    ):
        self.validate_key(identity_key)

        deltas = (
            mood_delta,
            energy_delta,
            familiarity_delta,
        )

        for delta in deltas:
            if (
                isinstance(delta, bool)
                or not isinstance(delta, (int, float))
                or not math.isfinite(delta)
                or abs(delta) > 1.0
            ):
                raise ValueError("Affect: 无效状态变化量")

        now = int(time.time())

        with closing(self.connect()) as conn:
            with conn:
                conn.execute("BEGIN IMMEDIATE")

                conn.execute(
                    """
                    INSERT OR IGNORE INTO affect_state
                    (identity_key)
                    VALUES (?)
                    """,
                    (identity_key,),
                )

                conn.execute(
                    """
                    UPDATE affect_state
                    SET
                        mood = MAX(-1.0, MIN(1.0, mood + ?)),
                        energy = MAX(0.0, MIN(1.0, energy + ?)),
                        familiarity = MAX(
                            0.0, MIN(1.0, familiarity + ?)
                        ),
                        interaction_count = interaction_count + 1,
                        last_interaction_at = ?,
                        updated_at = ?
                    WHERE identity_key = ?
                    """,
                    (
                        mood_delta,
                        energy_delta,
                        familiarity_delta,
                        now,
                        now,
                        identity_key,
                    ),
                )

                row = conn.execute(
                    """
                    SELECT mood, energy, familiarity,
                           interaction_count,
                           last_interaction_at, updated_at
                    FROM affect_state
                    WHERE identity_key = ?
                    """,
                    (identity_key,),
                ).fetchone()

        return dict(row)

    def record_unique_event(self, identity_key, event_key):
        """原子化记录消息。同一事件最多增加一次互动计数。"""

        self.validate_key(identity_key)

        if (
            not isinstance(event_key, str)
            or not re.fullmatch(r"[0-9a-f]{64}", event_key)
        ):
            raise ValueError("Affect: 无效事件指纹")

        now = int(time.time())

        with closing(self.connect()) as conn:
            with conn:
                conn.execute("BEGIN IMMEDIATE")

                cursor = conn.execute(
                    """
                    INSERT INTO affect_processed_events
                        (event_key, identity_key, processed_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(event_key) DO NOTHING
                    """,
                    (event_key, identity_key, now),
                )

                inserted = cursor.rowcount == 1

                if inserted:
                    conn.execute(
                        """
                        INSERT INTO affect_state (
                            identity_key,
                            interaction_count,
                            last_interaction_at,
                            updated_at
                        )
                        VALUES (?, 1, ?, ?)
                        ON CONFLICT(identity_key)
                        DO UPDATE SET
                            interaction_count =
                                interaction_count + 1,
                            last_interaction_at =
                                excluded.last_interaction_at,
                            updated_at = excluded.updated_at
                        """,
                        (identity_key, now, now),
                    )
                else:
                    owner = conn.execute(
                        """
                        SELECT identity_key
                        FROM affect_processed_events
                        WHERE event_key = ?
                        """,
                        (event_key,),
                    ).fetchone()

                    if owner is None or owner[0] != identity_key:
                        raise ValueError(
                            "Affect: 事件指纹与用户身份不匹配"
                        )

                row = conn.execute(
                    """
                    SELECT mood, energy, familiarity,
                           interaction_count,
                           last_interaction_at, updated_at
                    FROM affect_state
                    WHERE identity_key = ?
                    """,
                    (identity_key,),
                ).fetchone()

                if row is None:
                    raise RuntimeError(
                        "Affect: 事件与状态记录不一致"
                    )

                return {
                    "inserted": inserted,
                    "state": dict(row),
                }
