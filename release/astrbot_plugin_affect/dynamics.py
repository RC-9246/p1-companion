"""P1 Affect V0.6: deterministic simulated-state dynamics."""

import math

MOOD_HALF_LIFE = 6 * 3600
ENERGY_HALF_LIFE = 12 * 3600
FAMILIARITY_HALF_LIFE = 180 * 24 * 3600

ENERGY_BASELINE = 0.5
ENERGY_GAIN = 0.02
FAMILIARITY_GAIN = 0.002
MOOD_SIGNAL_GAIN = 0.10


def clamp(value, low, high):
    return max(low, min(high, value))


def decay_factor(elapsed, half_life):
    return 2.0 ** (-elapsed / half_life)


def evolve_state(state, now, valence=0.0):
    """
    Compute the next simulated state without database writes.

    state: previous state dictionary
    now: Unix timestamp
    valence: bounded external signal [-1, 1]

    Returns mood, energy, familiarity.
    Does not modify state or interaction_count.
    """

    if (
        isinstance(now, bool)
        or not isinstance(now, (int, float))
        or not math.isfinite(now)
        or now < 0
    ):
        raise ValueError("Invalid timestamp")

    if (
        isinstance(valence, bool)
        or not isinstance(valence, (int, float))
        or not math.isfinite(valence)
        or not -1.0 <= valence <= 1.0
    ):
        raise ValueError("Invalid valence signal")

    mood = float(state["mood"])
    energy = float(state["energy"])
    familiarity = float(state["familiarity"])
    last = int(state["last_interaction_at"])

    if not all(math.isfinite(x) for x in (
        mood, energy, familiarity
    )):
        raise ValueError("Non-finite state")

    elapsed = max(0.0, now - last) if last > 0 else 0.0

    # First interaction receives a normal initial gain.
    first_interaction = last <= 0

    # Limit mood changes from closely spaced messages.
    mood_weight = (
        1.0 if first_interaction
        else min(1.0, elapsed / 60.0)
    )

    # Mood decays toward neutral and responds to bounded signals.
    mood = (
        mood * decay_factor(elapsed, MOOD_HALF_LIFE)
        + MOOD_SIGNAL_GAIN * valence * mood_weight
    )

    # Short intervals receive proportionally smaller rewards.
    energy_weight = (
        1.0 if first_interaction
        else min(1.0, elapsed / 60.0)
    )

    familiarity_weight = (
        1.0 if first_interaction
        else min(1.0, elapsed / 300.0)
    )

    # Energy decays toward baseline and gains gradually.
    energy = (
        ENERGY_BASELINE
        + (energy - ENERGY_BASELINE)
        * decay_factor(elapsed, ENERGY_HALF_LIFE)
        + ENERGY_GAIN * energy_weight
    )

    # Familiarity decays slowly and has diminishing returns.
    familiarity = (
        familiarity
        * decay_factor(elapsed, FAMILIARITY_HALF_LIFE)
    )

    familiarity_gain = (
        FAMILIARITY_GAIN
        * familiarity_weight
        * (1.0 - clamp(familiarity, 0.0, 0.7) / 0.7)
    )

    familiarity += familiarity_gain

    return {
        "mood": clamp(mood, -1.0, 1.0),
        "energy": clamp(energy, 0.0, 1.0),
        "familiarity": clamp(familiarity, 0.0, 0.7),
    }
