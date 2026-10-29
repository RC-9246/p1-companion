"""Opt-in stdio MCP for engineering assistants. All six tools are read-only.

No arbitrary path argument for live tools, no shell, no accounts, no DB access.
"""
from __future__ import annotations
import argparse
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
import sys
sys.dont_write_bytecode=True
from companion import SOURCE, AccessError, bounded_json, bounded_text, describe, verify, plan, handoff, health, doctor, root_path

TOOL_NAMES=('p1_project_overview','p1_verify_source','p1_deployment_plan',
            'p1_deployment_check','p1_runtime_health','p1_handoff_template')

def create_server(live_root=None):
    # Keep this optional dependency separate from the standard-library CLI.
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
    target=root_path(str(live_root)) if live_root is not None else None
    server=FastMCP('p1-companion-engineering',log_level='ERROR')
    annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,idempotentHint=True,openWorldHint=False)
    def denied(): return {'ok':False,'error':'live_root_not_configured','writes':False}

    @server.tool(annotations=annotations)
    def p1_project_overview()->dict:
        """Read public project entrypoints, constraints and acceptance layers. No live machine or credentials."""
        return describe()

    @server.tool(annotations=annotations)
    def p1_verify_source()->dict:
        """Verify local distributed source hashes. Does not prove publisher identity or runtime correctness."""
        return verify()

    @server.tool(annotations=annotations)
    def p1_deployment_plan(root:str='/srv/p1-agent',mode:str='fresh_host')->dict:
        """Return command arrays for fresh_host, existing_core or existing_companion. Never executes them or grants permission."""
        try: return plan(root,mode)
        except AccessError: return {'ok':False,'error':'invalid_plan_root','writes':False}

    @server.tool(annotations=annotations)
    def p1_deployment_check()->dict:
        """Read-only first-install preflight at the operator-fixed root. Existing installs are refused. No raw config or logs."""
        return doctor(target) if target is not None else denied()

    @server.tool(annotations=annotations)
    def p1_runtime_health()->dict:
        """Read a closed summary of local startup/maintenance reports at the fixed root. Not account login or a live container probe."""
        return health(target) if target is not None else denied()

    @server.tool(annotations=annotations)
    def p1_handoff_template()->dict:
        """Produce an empty, model-neutral evidence handoff. It contains no private history or hidden reasoning."""
        return handoff()

    @server.resource('companion://project/manifest')
    def manifest_resource()->str:
        import json
        return json.dumps(bounded_json(SOURCE/'ai/PROJECT.json',SOURCE),ensure_ascii=False)

    @server.resource('companion://project/agent-guide')
    def guide_resource()->str:
        return bounded_text(SOURCE/'AGENTS.md',SOURCE,14000)

    @server.prompt()
    def companion_takeover()->str:
        """Reusable handoff guidance. The human's concrete task and actual authorization take precedence."""
        return bounded_text(SOURCE/'ai/TAKEOVER.md',SOURCE,12000)

    return server

def main():
    p=argparse.ArgumentParser(description='Read-only engineering MCP; stdio only, default offline')
    p.add_argument('--live-root',help='Explicit operator-owned runtime root; only health summaries and read-only preflight')
    a=p.parse_args()
    try:
        installed=version('mcp')
        if installed!='1.30.0': raise AccessError('use_optional_mcp_1_30_environment')
        server=create_server(a.live_root);server.run(transport='stdio');return 0
    except (ImportError,PackageNotFoundError,AccessError):
        print('MCP unavailable: use the isolated mcp==1.30.0 environment documented in docs/ai-access.md. No live access enabled.',file=sys.stderr)
        return 1

if __name__=='__main__': raise SystemExit(main())
