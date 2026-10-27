#Requires -Version 5.1
param([switch]$PlanOnly,[switch]$SetupAgain)
$ErrorActionPreference = 'Stop'
$Distro = 'P1Companion'
$Repo = Split-Path -Parent $PSScriptRoot
$StateDir = Join-Path $env:LOCALAPPDATA 'P1Companion'
$StatePath = Join-Path $StateDir 'setup-state.json'
function Show-Info([string]$Message) {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($Message, 'P1 Companion 安装向导', 'OK', 'Information') | Out-Null
}
function Save-Phase([string]$Phase) {
    New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
    @{ schema = 1; phase = $Phase; distro = $Distro; source = $Repo } | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8
}
function Wsl-Command([string[]]$Arguments) {
    & wsl.exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "WSL 操作未完成（退出码 $LASTEXITCODE）。请更新 Windows / WSL，确认 BIOS 虚拟化已启用，然后重新双击安装程序。" }
}
function Read-WizardStateFile([ValidateSet('browser.url','completed.json')][string]$Name) {
    $File = '/var/lib/p1-companion-installer/' + $Name
    # An absent receipt is expected before startup/completion. Probe without
    # stderr so PowerShell 5.1 Stop does not turn it into a fatal native error.
    & wsl.exe --distribution P1Companion --user root --exec test -f $File | Out-Null
    if ($LASTEXITCODE -ne 0) { return '' }
    return (((& wsl.exe --distribution P1Companion --user root --exec cat $File) -join '').Trim())
}
function Test-WizardUrl([string]$Url) {
    if ($Url -notmatch '^http://127\.0\.0\.1:6191/#([A-Za-z0-9_-]+)$') { return $false }
    $SessionToken = $Matches[1]
    try {
        $Status = Invoke-RestMethod -Uri 'http://127.0.0.1:6191/api/state' -Headers @{ 'X-P1-Setup-Token' = $SessionToken } -TimeoutSec 3
        return ($Status.project -eq 'p1-companion-installer' -and -not $Status.preview)
    } catch { return $false }
}
try {
    if ($PlanOnly) {
        @{ target = 'Windows 10/11 x64'; minimumBuild = 19041; distro = $Distro; ubuntu = '24.04'; nativeLinuxDocker = $true; installsDockerDesktop = $false; autoReboot = $false; overwritesWslConfig = $false; phases = @('system_check','elevation','wsl_install','reboot_if_required','ubuntu_setup','local_web_wizard') } | ConvertTo-Json -Depth 4
        exit 0
    }
    $OS = Get-CimInstance Win32_OperatingSystem
    if ([int]$OS.BuildNumber -lt 19041 -or -not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
        throw '支持 Windows 10 2004（Build 19041）及更新版本，或 Windows 11，x64。Windows ARM、32 位和较旧版本请先升级或使用 Linux 设备。'
    }
    if (-not $SetupAgain -and (Test-Path -LiteralPath (Join-Path $StateDir 'setup-state.json'))) {
        $Previous = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
        if ($Previous.phase -eq 'completed' -and (Test-Path -LiteralPath (Join-Path $StateDir 'Start-P1Companion.ps1'))) {
            & (Join-Path $StateDir 'Start-P1Companion.ps1'); exit 0
        }
    }
    $Admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $Admin) {
        # Run the local script as the same Windows user with a normal UAC prompt.
        $ElevatedArguments = @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"' + $PSCommandPath + '"'))
        if ($SetupAgain) { $ElevatedArguments += '-SetupAgain' }
        Start-Process powershell.exe -Verb RunAs -ArgumentList $ElevatedArguments
        exit 0
    }
    if ([long]$OS.TotalVisibleMemorySize * 1KB -lt 8GB) { throw 'Windows 至少需要 8GB 内存，推荐 16GB；Linux 独立主机可用 4GB 档设备。' }
    $Drive = New-Object System.IO.DriveInfo ([System.IO.Path]::GetPathRoot($StateDir))
    if ($Drive.AvailableFreeSpace -lt 20GB) { throw 'Windows 系统盘至少需要 20GB 可用空间，用于 Ubuntu 与容器镜像。请先腾出空间。' }
    $Computer = Get-CimInstance Win32_ComputerSystem
    $Processor = Get-CimInstance Win32_Processor | Select-Object -First 1
    if (-not $Computer.HypervisorPresent -and $Processor.VirtualizationFirmwareEnabled -eq $false) { throw '请先在 BIOS/UEFI 中开启 CPU 虚拟化（Intel VT-x / AMD-V），再双击安装程序。可在任务管理器 → 性能 → CPU 查看“虚拟化”。程序不会替你修改 BIOS。' }
    New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) '继续安装 P1 Companion.lnk'))
    $Shortcut.TargetPath = 'powershell.exe'
    $Shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"'
    $Shortcut.WorkingDirectory = $Repo
    $Shortcut.Save()
    $NeedReboot = $false
    foreach ($Feature in @('Microsoft-Windows-Subsystem-Linux','VirtualMachinePlatform')) {
        $Current = Get-WindowsOptionalFeature -Online -FeatureName $Feature
        if ($Current.State -ne 'Enabled') {
            $Result = Enable-WindowsOptionalFeature -Online -FeatureName $Feature -All -NoRestart
            if ($Result.RestartNeeded) { $NeedReboot = $true }
        }
    }
    if ($NeedReboot) {
        Save-Phase 'restart_required'
        Show-Info "已启用 WSL2 所需的 Windows 组件。`n`n请保存工作并手动重启电脑，然后双击桌面上的“继续安装 P1 Companion”。`n`n程序不会自动重启，也不会丢弃你的工作。"
        exit 0
    }
    Save-Phase 'preparing_wsl'
    & wsl.exe --install --no-distribution
    if ($LASTEXITCODE -in @(3010,1641)) { Save-Phase 'restart_required'; Show-Info '请手动重启电脑，再双击桌面的继续安装快捷方式。'; exit 0 }
    if ($LASTEXITCODE -ne 0) { throw 'WSL 未准备好。请更新 Windows，检查虚拟化支持后重试。' }
    Wsl-Command -Arguments @('--update')
    $Installed = ((& wsl.exe --list --quiet) -replace "`0", '')
    $DistroMarker = Join-Path $StateDir 'distro-created.json'
    if ($Installed -match '(?m)^P1Companion\s*$') {
        if (-not (Test-Path -LiteralPath $DistroMarker)) { throw '已存在同名 P1Companion 发行版，但没有本程序的创建记录。为保护原有数据，停止自动接管。' }
        $FinishedRaw = Read-WizardStateFile -Name 'completed.json'
        if (-not $SetupAgain -and $LASTEXITCODE -eq 0 -and ($FinishedRaw | ConvertFrom-Json).cleanup_complete -and (Test-Path -LiteralPath (Join-Path $StateDir 'Start-P1Companion.ps1'))) {
            . (Join-Path $StateDir 'Start-P1Companion.ps1') -LibraryOnly
            Clear-CompanionResumeShortcut
            Save-Phase 'completed'
            & (Join-Path $StateDir 'Start-P1Companion.ps1'); exit 0
        }
        # Reuse a running installation without terminating it or copying its source.
        $ExistingUrl = Read-WizardStateFile -Name 'browser.url'
        if (Test-WizardUrl $ExistingUrl) { Start-Process $ExistingUrl; exit 0 }
    } else {
        Write-Host '正在准备独立的 Ubuntu 24.04 环境，不修改你已有的 WSL 发行版…'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $BaseUrl = 'https://cloud-images.ubuntu.com/wsl/releases/noble/current/'
        $ImageName = 'ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz'
        $Archive = Join-Path $StateDir $ImageName
        $Sums = (Invoke-WebRequest -Uri ($BaseUrl + 'SHA256SUMS') -UseBasicParsing).Content
        $DigestLine = ($Sums -split "`n" | Where-Object { $_ -match ('^[a-fA-F0-9]{64}\s+\*?' + [regex]::Escape($ImageName) + '$') } | Select-Object -First 1)
        if (-not $DigestLine) { throw '无法取得 Ubuntu 官方镜像校验值，未继续安装。' }
        $ExpectedDigest = $DigestLine.Substring(0,64).ToLowerInvariant()
        if (-not (Test-Path -LiteralPath $Archive) -or (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedDigest) {
            Invoke-WebRequest -Uri ($BaseUrl + $ImageName) -OutFile $Archive -UseBasicParsing
        }
        if ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedDigest) { throw 'Ubuntu 下载不完整或校验失败，未导入。请检查网络并重试。' }
        $InstallLocation = Join-Path $StateDir 'WSL'
        Wsl-Command -Arguments @('--import',$Distro,$InstallLocation,$Archive,'--version','2')
        @{ name = $Distro; source = $BaseUrl; sha256 = $ExpectedDigest } | ConvertTo-Json | Set-Content -LiteralPath $DistroMarker -Encoding UTF8
    }
    # Convert only this explicitly selected distro; never change the global default.
    Wsl-Command -Arguments @('--set-version',$Distro,'2')
    $LinuxRepo = ((& wsl.exe --distribution $Distro --user root --exec wslpath -u $Repo) -join '').Trim()
    if ($LASTEXITCODE -ne 0 -or -not $LinuxRepo.StartsWith('/')) { throw '无法读取解压目录。请将项目解压到本机磁盘，避免网络路径。' }
    Wsl-Command -Arguments @('--distribution',$Distro,'--user','root','--exec','/bin/bash',($LinuxRepo + '/deploy/windows-bootstrap.sh'),$LinuxRepo)
    if ($LASTEXITCODE -ne 0) { throw 'Ubuntu 环境准备未完成，请重试。' }
    # systemd changes take effect after restarting this distro, not all WSL instances.
    & wsl.exe --terminate $Distro
    # Keep WSL alive independently of the temporary web installer.
    $Controller = Join-Path $StateDir 'Start-P1Companion.ps1'
    $ControllerReceipt = Join-Path $StateDir 'runtime-controller.sha256'
    if (Test-Path -LiteralPath $Controller) {
        if (-not (Test-Path -LiteralPath $ControllerReceipt) -or (Get-Item -LiteralPath $Controller).Attributes -band [IO.FileAttributes]::ReparsePoint -or (Get-FileHash -LiteralPath $Controller -Algorithm SHA256).Hash -ne (Get-Content -LiteralPath $ControllerReceipt -Raw).Trim()) { throw '后台启动脚本已发生变化，请保留原文件并检查后重试。' }
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'windows-runtime.ps1') -Destination $Controller -Force
    (Get-FileHash -LiteralPath $Controller -Algorithm SHA256).Hash | Set-Content -LiteralPath $ControllerReceipt -Encoding ASCII
    . $Controller -LibraryOnly
    Ensure-CompanionRuntime
    Install-CompanionRuntimeShortcut
    Clear-CompanionInstallerCache
    $GuiClient = Start-Process -FilePath wsl.exe -ArgumentList @('--distribution',$Distro,'--user','root','--exec','/bin/bash','/opt/p1-companion-installer/deploy/windows-bootstrap.sh','--start') -WindowStyle Hidden -PassThru
    $Url = ''
    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
        $Url = Read-WizardStateFile -Name 'browser.url'
        if (Test-WizardUrl $Url) { break }
        $Url = ''; Start-Sleep -Seconds 1
    }
    if (-not $Url) { throw '本机向导未能启动。请检查 WSL 是否运行、6191 端口是否被占用；安装数据会保留。' }
    Save-Phase 'wizard_ready'
    Start-Process $Url
    Write-Host '安装向导已在浏览器打开。完成验收后会自动清理临时向导，后台与数据保留。'
    $GuiClient.WaitForExit()
    $CompletedRaw = Read-WizardStateFile -Name 'completed.json'
    if ($LASTEXITCODE -eq 0 -and ($CompletedRaw | ConvertFrom-Json).cleanup_complete) {
        Clear-CompanionResumeShortcut
        Save-Phase 'completed'
    }
} catch {
    Show-Info ([string]$_.Exception.Message)
    exit 1
}
