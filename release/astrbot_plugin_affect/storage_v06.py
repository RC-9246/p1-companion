"""P1 Affect V0.6 transactional state storage."""

import re
import sqlite3
import time
from contextlib import closing

from .storage import AffectStore
from .dynamics import evolve_state


class AffectStoreV06(AffectStore):

    def record_unique_event(
        self,
        identity_key,
        event_key,
        valence=0.0,
    ):
        self.validate_key(identity_key)

        if (
            not isinstance(event_key, str)
            or not re.fullmatch(r"[0-9a-f]{64}", event_key)
        ):
            raise ValueError("Affect: Invalid event key")

        now = int(time.time())

        with closing(self.connect()) as conn:
            with conn:
                conn.execute("BEGIN IMMEDIATE")

                # Step 1: Event deduplication
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

                if not inserted:
                    owner = conn.execute(
                        """
                        SELECT identity_key
                        FROM affect_processed_events
                        WHERE event_key = ?
                        """,
                        (event_key,),
                    ).fetchone()

                    if (
                        owner is None
                        or owner["identity_key"] != identity_key
                    ):
                        raise ValueError(
                            "Affect: Event ownership mismatch"
                        )

                    state = self._read_state(
                        conn, identity_key
                    )

                    if state is None:
                        raise RuntimeError(
                            "Affect: Missing state for event"
                        )

                    return {
                        "inserted": False,
                        "state": state,
                    }

                # Step 2: Ensure state exists
                conn.execute(
                    """
                    INSERT OR IGNORE INTO affect_state
                        (identity_key)
                    VALUES (?)
                    """,
                    (identity_key,),
                )

                previous = self._read_state(
                    conn, identity_key
                )

                if previous is None:
                    raise RuntimeError(
                        "Affect: Cannot initialize state"
                    )

                # Step 3: Calculate simulated state
                evolved = evolve_state(
                    previous,
                    now,
                    valence=valence,
                )

                # Step 4: Atomic update
                conn.execute(
                    """
                    UPDATE affect_state
                    SET mood = ?,
                        energy = ?,
                        familiarity = ?,
                        interaction_count =
                            interaction_count + 1,
                        last_interaction_at = ?,
                        updated_at = ?
                    WHERE identity_key = ?
                    """,
                    (
                        evolved["mood"],
                        evolved["energy"],
                        evolved["familiarity"],
                        now,
                        now,
                        identity_key,
                    ),
                )

                state = self._read_state(
                    conn, identity_key
                )

                return {
                    "inserted": True,
                    "state": state,
                }

    @staticmethod
    def _read_state(conn, identity_key):
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

        return dict(row) if row is not None else None
