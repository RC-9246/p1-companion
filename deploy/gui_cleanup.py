"""Retire only this installer's session and verified managed staging files.

Never remove runtime services, user downloads, account data or recovery copies.
The caller retains in-memory HTTP assets until its orderly shutdown.
"""
import hashlib,json,os,re,shutil,stat,subprocess,time
from pathlib import Path
import firstboot as F
import install as I

MANAGED_SOURCE=Path('/opt/p1-companion-installer')

def protected(path):
    path=Path(path)
    F.need(path.is_absolute() and path==path.resolve(),'unsafe_cleanup_path')
    for p in (path,*path.parents):
        F.need(not p.is_symlink(),'unsafe_cleanup_path')
    s=path.stat()
    F.need(s.st_uid==os.geteuid() and not s.st_mode&0o022,'unsafe_cleanup_path')
    return path

def acceptance(root,point,state,confirmed):
    F.need(confirmed is True,'real_chat_confirmation_required')
    F.need(state.get('status')=='committed' and state.get('root')==str(root),'integration_not_committed')
    protected(point)
    services={n:I.healthy(I.inspect(n)) for n in ('astrbot','snowluma',*I.TOOLS)}
    flags=F.read(root/'astrbot/data/plugin_data/affect/companion_health.json')
    F.need(all(services.values()) and all(flags.get(k) is True for k in I.READY),'final_health_check_failed')
    return {'services_checked':len(services),'plugin_ready_flags_checked':len(I.READY)}

def windows_runtime_ready():
    # Linux hosts need no Windows keepalive. WSL must prove an independent native
    # client exists before the foreground installation process can disappear.
    release=Path('/proc/sys/kernel/osrelease')
    if not release.exists() or 'microsoft' not in release.read_text().lower():return
    exe=shutil.which('powershell.exe')
    F.need(bool(exe) and re.fullmatch(r'/mnt/[a-z]/Windows/System32/WindowsPowerShell/v1\.0/powershell\.exe',exe,re.I),'windows_runtime_not_ready')
    command="$p=Join-Path $env:LOCALAPPDATA 'P1Companion\\Start-P1Companion.ps1'; & $p -CheckOnly"
    p=subprocess.run([exe,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-Command',command],capture_output=True,timeout=30)
    try:ready=p.returncode==0 and len(p.stdout)<4096 and json.loads(p.stdout.decode('utf-8-sig')).get('runtime_host_ready') is True
    except (ValueError,UnicodeError,AttributeError):ready=False
    F.need(ready,'windows_runtime_not_ready')

def remove_managed_source(source):
    source=Path(source)
    if source!=MANAGED_SOURCE:return {'managed_files_removed':0,'managed_files_retained':0,'user_source_preserved':True}
    protected(source)
    marker=source/'.p1-wizard-source'
    F.need(marker.is_file() and not marker.is_symlink() and marker.stat().st_uid==os.geteuid() and not marker.stat().st_mode&0o022 and marker.read_text()=='1\n','unmanaged_installer_source')
    manifest_path=source/'source-manifest.json'
    F.need(manifest_path.is_file() and not manifest_path.is_symlink(),'unmanaged_installer_source')
    manifest=I.read(manifest_path);F.need(isinstance(manifest,dict) and bool(manifest),'unmanaged_installer_source')
    # Validate all relative paths before the first deletion. Modified/extra files
    # are retained; no recursive removal and no following directory symlinks.
    candidates=[];retained=0;dirs=set()
    for rel,digest in manifest.items():
        r=Path(rel)
        F.need(not r.is_absolute() and '..' not in r.parts and rel not in ('source-manifest.json','.p1-wizard-source') and re.fullmatch('[0-9a-f]{64}',digest) is not None,'unmanaged_installer_source')
        p=source/r
        if any(q.is_symlink() for q in (p,*p.parents)) or not p.is_file():retained+=1;continue
        if hashlib.sha256(p.read_bytes()).hexdigest()!=digest:retained+=1;continue
        candidates.append(p);dirs.update(q for q in p.parents if q!=source and q.is_relative_to(source))
    for p in candidates:p.unlink()
    if not retained:
        manifest_path.unlink();marker.unlink()
    for d in sorted(dirs,key=lambda p:len(p.parts),reverse=True):
        try:d.rmdir()
        except OSError:pass
    try:source.rmdir()
    except OSError:pass
    return {'managed_files_removed':len(candidates),'managed_files_retained':retained,'user_source_preserved':True}

def finish(root,point,state,session,confirmed,auto_cleanup=True,source=None):
    health=acceptance(root,point,state,confirmed)
    if not auto_cleanup:return {**health,'cleanup_complete':False,'gui_kept':True}
    windows_runtime_ready();session=protected(session)
    F.need(not (session/'browser.url').is_symlink(),'unsafe_cleanup_path')
    archive=point/('wizard-final-'+str(time.time_ns()));archive.mkdir(mode=0o700)
    # Archive only this installer's known progress files, never arbitrary paths.
    evidence=[p for p in session.iterdir() if re.fullmatch(r'job-[0-9]+-[0-9a-f]+\.(json|private\.log)',p.name) or p.name=='launcher.log']
    for p in evidence:
        F.need(p.is_file() and not p.is_symlink() and stat.S_ISREG(p.stat().st_mode),'unsafe_cleanup_path')
        shutil.copy2(p,archive/p.name);(archive/p.name).chmod(0o600)
    result={**health,**remove_managed_source(I.SOURCE if source is None else source),'cleanup_complete':True,'gui_kept':False,'logs_archived':len(evidence)}
    # Write a durable completion receipt before removing session credentials.
    I.atomic(session/'completed.json',{'schema':1,'root':str(root),'point':str(point),'at':int(time.time()),**result})
    for p in evidence:p.unlink()
    for name in ('browser.url',):
        p=session/name
        F.need(not p.is_symlink(),'unsafe_cleanup_path');p.unlink(missing_ok=True)
    return result
