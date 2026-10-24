"""Read installed framework source only; no account configuration or chat data."""
import ast,hashlib,json
from pathlib import Path
from astrbot.core.pipeline.stage_order import STAGES_ORDER
root=Path('/AstrBot/astrbot')
paths=['dashboard/services/config_service.py','core/core_lifecycle.py','core/pipeline/whitelist_check/stage.py']
texts={p:(root/p).read_text() for p in paths}
service=texts[paths[0]];core=texts[paths[1]];white=texts[paths[2]]
save_methods=[]
for node in ast.walk(ast.parse(service)):
 if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
  calls=[(getattr(x.func,'attr',getattr(x.func,'id','')),x.lineno) for x in ast.walk(node) if isinstance(x,ast.Call)]
  saves=[line for name,line in calls if name=='save_config'];reloads=[line for name,line in calls if name=='reload_pipeline_scheduler']
  if saves and reloads and min(saves)<max(reloads):save_methods.append(node.name)
proof={
 'installed_source_sha256':{p:hashlib.sha256(v.encode()).hexdigest() for p,v in texts.items()},
 'webui_save_calls_save_config_and_reload':bool(save_methods),
 'save_and_reload_methods':save_methods,
 'reload_initializes_new_pipeline':all(x in core for x in ['scheduler = PipelineScheduler(','await scheduler.initialize()','self.pipeline_scheduler_mapping[conf_id] = scheduler']),
 'private_whitelist_is_copied_on_initialize':'str(i).strip() for i in self.whitelist' in white,
 'wake_precedes_whitelist':STAGES_ORDER.index('WakingCheckStage')<STAGES_ORDER.index('WhitelistCheckStage'),
 'stage_order':STAGES_ORDER,
 'configuration_or_database_modified':False,
}
assert all(proof[k] for k in ['webui_save_calls_save_config_and_reload','reload_initializes_new_pipeline','private_whitelist_is_copied_on_initialize','wake_precedes_whitelist'])
print(json.dumps(proof,indent=2))
