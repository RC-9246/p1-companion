import hashlib
import json


def make_identity_key(platform_id, bot_id, sender_id):
    """生成稳定的用户身份键，不依赖会话 ID。"""

    values = [platform_id, bot_id, sender_id]

    if any(v is None or not str(v).strip() for v in values):
        raise ValueError("Affect: 缺少必要的用户身份字段")

    values = [str(v).strip() for v in values]

    payload = json.dumps(
        values,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    digest = hashlib.sha256(payload).hexdigest()

    return "v1:" + digest


def identity_from_event(event):
    """仅使用 AstrBot 可信的事件身份接口。"""

    return make_identity_key(
        event.get_platform_id(),
        event.get_self_id(),
        event.get_sender_id(),
    )
