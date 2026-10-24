"""P1 Affect: idempotent LLM context injection."""

from astrbot.core.agent.message import TextPart

from .prompt_context import (
    CONTEXT_MARKER,
    build_affect_context,
)


def _part_text(part):
    """Read text from supported content-part representations."""

    if isinstance(part, dict):
        value = part.get("text")
    else:
        value = getattr(part, "text", None)

    return value if isinstance(value, str) else ""


def inject_affect_context(request, state):
    """
    Append one temporary Affect context to an LLM request.

    Returns:
        True  - a new Affect context was appended.
        False - skipped because of invalid input,
                missing request support or prior injection.

    Does not modify:
        - request.system_prompt
        - request.prompt
        - request.contexts
        - pre-existing content parts
    """

    if request is None:
        return False

    parts = getattr(
        request,
        "extra_user_content_parts",
        None,
    )

    # Fail closed on unsupported request structures.
    if not isinstance(parts, list):
        return False

    # Never inject twice into the same request.
    for part in parts:
        text = _part_text(part)

        if text.startswith(CONTEXT_MARKER):
            return False

    context = build_affect_context(state)

    if not context:
        return False

    # Match the temporary-context mechanism used by Memoria.
    affect_part = TextPart(
        text=context
    ).mark_as_temp()

    parts.append(affect_part)

    return True
