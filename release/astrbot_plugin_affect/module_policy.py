"""Low-cost runtime feature switches. These never grant identity/tool permission.

Absent config preserves legacy behavior. An invalid present config disables
optional capabilities; privacy isolation and the core reply path remain intact.
"""
import json
from pathlib import Path

FEATURES = frozenset(('learning','reflection','stickers','qq_actions','autonomy','proactive',
                      'public_web','bilibili','workbench','workflows','mcp'))
TOOL_MODULES = {
    'p1_browser': ('public_web',), 'p1_public_research': ('public_web',),
    'p1_saki_reaction': ('stickers',), 'p1_qq_stickers': ('stickers','qq_actions'),
    'p1_qq_social': ('qq_actions',), 'p1_qq_detail': ('qq_actions',), 'p1_qq_records': ('qq_actions',),
    'p1_documents': ('workbench',), 'p1_bilibili': ('bilibili',),
    'p1_mcp_read': ('public_web',), 'p1_mcp_search': ('public_web',),
    'p1_mcp_sources': ('public_web',), 'p1_mcp_workflow': ('workflows',),
    'p1_mcp_experiment': ('workbench',), 'p1_mcp_transform': ('workbench',),
    'p1_mcp_document_formats': ('workbench',),
}
_cache = {}


def enabled(data, name):
    if name == 'core':
        return True
    if name not in FEATURES:
        return False
    p = Path(data) / 'modules_enabled.json'
    try:
        s = p.stat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if p.is_symlink() or s.st_size > 16384:
        return False
    key = (str(p), s.st_mtime_ns, s.st_size)
    if key not in _cache:
        try:
            v = json.loads(p.read_bytes())
            names = v.get('enabled')
            good = (v.get('schema') == 1 and isinstance(names, list) and len(names) <= 64 and
                    all(isinstance(n, str) for n in names) and 'core' in names)
            result = set(names) if good else set()
        except (OSError, ValueError, TypeError, AttributeError):
            result = set()
        _cache.clear()
        _cache[key] = result
    return name in _cache[key]


def tool_enabled(data, name):
    if name.startswith('p1_mcp_') and not enabled(data, 'mcp'):
        return False
    return all(enabled(data, m) for m in TOOL_MODULES.get(name, ()))
