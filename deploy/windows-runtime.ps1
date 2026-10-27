#Requires -Version 5.1
param([switch]$LibraryOnly,[switch]$CheckOnly,[switch]$PlanOnly)
$ErrorActionPreference = 'Stop'
function Get-CompanionRuntimeFolder { return (Join-Path $env:LOCALAPPDATA 'P1Companion') }
function Test-CompanionRuntimeHost {
    try {
        $Record = Get-Content -LiteralPath (Join-Path (Get-CompanionRuntimeFolder) 'runtime-host.json') -Raw | ConvertFrom-Json
        $Process = Get-Process -Id ([int]$Record.pid) -ErrorAction Stop
        $Command = (Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$Record.pid)).CommandLine
        if ($Process.ProcessName -ne 'wsl' -or $Process.StartTime.ToUniversalTime().Ticks -ne [long]$Record.ticks -or
            $Command -notmatch '(?:^|\s)--distribution\s+P1Companion\s+--user\s+root\s+--exec\s+/bin/bash\s+/usr/local/lib/p1-companion/wsl-runtime\.sh\s*$') { return $false }
        & wsl.exe --distribution P1Companion --user root --exec /bin/bash /usr/local/lib/p1-companion/wsl-runtime.sh --check 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}
function Ensure-CompanionRuntime {
    $RuntimeMutex = New-Object System.Threading.Mutex($false, 'Local\P1CompanionRuntime')
    $Acquired = $false
    try {
        $Acquired = $RuntimeMutex.WaitOne(15000)
        if (-not $Acquired) { throw '伙伴后台正在启动，请稍后再试。' }
        if (Test-CompanionRuntimeHost) { return }
        $Folder = Get-CompanionRuntimeFolder
        $OwnerRecord = Get-Content -LiteralPath (Join-Path $Folder 'distro-created.json') -Raw | ConvertFrom-Json
        if ($OwnerRecord.name -ne 'P1Companion') { throw '未找到本程序创建的 WSL 环境。' }
        # The Linux helper stops only its recorded PID with matching boot/start,
        # exact command line and lock descriptor. Never terminate the WSL distro.
        & wsl.exe --distribution P1Companion --user root --exec /bin/bash /usr/local/lib/p1-companion/wsl-runtime.sh --stop 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { throw '后台运行组件尚未安装，请先运行原安装程序。' }
        $HostClient = Start-Process -FilePath wsl.exe -ArgumentList @('--distribution','P1Companion','--user','root','--exec','/bin/bash','/usr/local/lib/p1-companion/wsl-runtime.sh') -WindowStyle Hidden -PassThru
        $Receipt = @{ pid = $HostClient.Id; ticks = $HostClient.StartTime.ToUniversalTime().Ticks }
        $Next = Join-Path $Folder 'runtime-host.next.json'
        $Receipt | ConvertTo-Json | Set-Content -LiteralPath $Next -Encoding UTF8
        Move-Item -LiteralPath $Next -Destination (Join-Path $Folder 'runtime-host.json') -Force
        for ($Try = 0; $Try -lt 20; $Try++) {
            if (Test-CompanionRuntimeHost) { return }
            Start-Sleep -Milliseconds 300
        }
        throw '后台运行未就绪，安装向导会保留。请检查 WSL 后重试。'
    } finally {
        if ($Acquired) { $RuntimeMutex.ReleaseMutex() }
        $RuntimeMutex.Dispose()
    }
}
function Install-CompanionRuntimeShortcut {
    $Controller = Join-Path (Get-CompanionRuntimeFolder) 'Start-P1Companion.ps1'
    $Shell = New-Object -ComObject WScript.Shell
    $Link = $Shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) '打开 P1 Companion.lnk'))
    $Link.TargetPath = 'powershell.exe'
    $Link.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $Controller + '"'
    $Link.Save()
}
function Clear-CompanionInstallerCache {
    $Folder = Get-CompanionRuntimeFolder
    $Record = Get-Content -LiteralPath (Join-Path $Folder 'distro-created.json') -Raw | ConvertFrom-Json
    $Archive = Join-Path $Folder 'ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz'
    if ((Test-Path -LiteralPath $Archive) -and $Record.name -eq 'P1Companion') {
        $Item = Get-Item -LiteralPath $Archive
        if (-not ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -and (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Record.sha256) {
            Remove-Item -LiteralPath $Archive
        }
    }
}
function Clear-CompanionResumeShortcut {
    $Folder = Get-CompanionRuntimeFolder
    $Saved = Get-Content -LiteralPath (Join-Path $Folder 'setup-state.json') -Raw | ConvertFrom-Json
    $Path = Join-Path ([Environment]::GetFolderPath('Desktop')) '继续安装 P1 Companion.lnk'
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $Shell = New-Object -ComObject WScript.Shell
    $Link = $Shell.CreateShortcut($Path)
    $Expected = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $Saved.source 'deploy\windows-setup.ps1') + '"'
    if ($Link.Arguments -eq $Expected -and [IO.Path]::GetFileName($Link.TargetPath) -eq 'powershell.exe') { Remove-Item -LiteralPath $Path }
}
if ($LibraryOnly) { return }
if ($PlanOnly) { @{ gui_required = $false; installs_software = $false; distro = 'P1Companion'; keeps_wsl_client_alive = $true; clears_only_verified_installer_cache = $true } | ConvertTo-Json; exit 0 }
if ($CheckOnly) { $Ready = Test-CompanionRuntimeHost; @{ runtime_host_ready = $Ready } | ConvertTo-Json; if ($Ready) { exit 0 } else { exit 1 } }
try {
    Ensure-CompanionRuntime
    Install-CompanionRuntimeShortcut
    Clear-CompanionInstallerCache
    $Finished = (& wsl.exe --distribution P1Companion --user root --exec cat /var/lib/p1-companion-installer/completed.json 2>$null) -join ''
    if ($LASTEXITCODE -eq 0 -and ($Finished | ConvertFrom-Json).cleanup_complete) { Clear-CompanionResumeShortcut }
    Start-Process 'http://127.0.0.1:6185/'
} catch {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show([string]$_.Exception.Message,'P1 Companion','OK','Information') | Out-Null
    exit 1
}
