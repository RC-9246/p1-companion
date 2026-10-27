$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Root 'deploy/windows-setup.ps1'
$Tokens = $null; $ParseErrors = $null
$Ast = [System.Management.Automation.Language.Parser]::ParseFile($Script,[ref]$Tokens,[ref]$ParseErrors)
if ($ParseErrors.Count) { throw ($ParseErrors | Out-String) }
$Plan = & $Script -PlanOnly | ConvertFrom-Json
if ($Plan.minimumBuild -ne 19041 -or $Plan.distro -ne 'P1Companion' -or $Plan.autoReboot -or $Plan.installsDockerDesktop -or $Plan.overwritesWslConfig) { throw 'Unsafe or incompatible Windows plan' }
$Raw = Get-Content -LiteralPath $Script -Raw
foreach ($Forbidden in @('--unregister','--shutdown','Restart-Computer','--set-default ')) {
    if ($Raw.Contains($Forbidden)) { throw "Unexpected destructive/global WSL action: $Forbidden" }
}
if (-not $Raw.Contains('Get-FileHash') -or -not $Raw.Contains('SHA256SUMS') -or -not $Raw.Contains('Wsl-Command -Arguments')) { throw 'Checksum or argument boundary missing' }
# Exercise the actual argument-forwarding helper with a fake native command.
$Function = $Ast.Find({param($Node) $Node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $Node.Name -eq 'Wsl-Command'},$true)
Invoke-Expression $Function.Extent.Text
function global:wsl.exe { $script:Received = @($args); $global:LASTEXITCODE = 0 }
Wsl-Command -Arguments @('--distribution','P1Companion','--exec','wslpath','-u','C:\A Folder\项目')
if ($script:Received.Count -ne 6 -or $script:Received[-1] -ne 'C:\A Folder\项目') { throw 'Native argv lost a path or argument' }
Remove-Item Function:\wsl.exe
$Runtime = Join-Path $Root 'deploy/windows-runtime.ps1'
$RuntimeTokens = $null; $RuntimeErrors = $null
$RuntimeAst = [System.Management.Automation.Language.Parser]::ParseFile($Runtime,[ref]$RuntimeTokens,[ref]$RuntimeErrors)
if ($RuntimeErrors.Count) { throw ($RuntimeErrors | Out-String) }
$RuntimePlan = & $Runtime -PlanOnly | ConvertFrom-Json
if ($RuntimePlan.gui_required -or $RuntimePlan.installs_software -or -not $RuntimePlan.keeps_wsl_client_alive) { throw 'Runtime depends on installer GUI' }
. $Runtime -LibraryOnly
# Test exact host identity checks without enabling WSL or starting processes.
$SavedLocal = $env:LOCALAPPDATA
$RuntimeTest = Join-Path ([IO.Path]::GetTempPath()) ('p1-runtime-test-' + [guid]::NewGuid().ToString('N'))
try {
    $env:LOCALAPPDATA = $RuntimeTest
    New-Item -ItemType Directory -Path (Join-Path $RuntimeTest 'P1Companion') -Force | Out-Null
    @{pid=24680;ticks=12345} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $RuntimeTest 'P1Companion/runtime-host.json') -Encoding UTF8
    $script:FakeTicks = 12345; $script:FakeName = 'wsl'; $script:FakeCommand = 'wsl.exe --distribution P1Companion --user root --exec /bin/bash /usr/local/lib/p1-companion/wsl-runtime.sh'
    function Get-Process { param($Id,$ErrorAction) return [pscustomobject]@{ProcessName=$script:FakeName;StartTime=[datetime]::new([long]$script:FakeTicks,[DateTimeKind]::Utc)} }
    function Get-CimInstance { param($ClassName,$Filter) return [pscustomobject]@{CommandLine=$script:FakeCommand} }
    function global:wsl.exe { $global:LASTEXITCODE = 0 }
    if (-not (Test-CompanionRuntimeHost)) { throw 'Expected controlled native host to match' }
    $script:FakeTicks = 22222
    if (Test-CompanionRuntimeHost) { throw 'Reused PID accepted' }
    $script:FakeTicks = 12345; $script:FakeName = 'not-wsl'
    if (Test-CompanionRuntimeHost) { throw 'Foreign executable accepted' }
    $script:FakeName = 'wsl'; $script:FakeCommand = 'wsl.exe --distribution OtherDistro --exec /bin/bash unrelated.sh'
    if (Test-CompanionRuntimeHost) { throw 'Foreign distribution accepted' }
    $script:FakeCommand = 'wsl.exe --distribution P1Companion --user root --exec /bin/bash /usr/local/lib/p1-companion/wsl-runtime.sh'
    function global:wsl.exe { $global:LASTEXITCODE = 1 }
    if (Test-CompanionRuntimeHost) { throw 'Dead Linux holder accepted' }
    # The preceding expected-failure stub must not become the CI process exit code.
    $global:LASTEXITCODE = 0
} finally {
    Remove-Item Function:\Get-Process,Function:\Get-CimInstance,Function:\wsl.exe -ErrorAction SilentlyContinue
    $env:LOCALAPPDATA = $SavedLocal
    Remove-Item -LiteralPath $RuntimeTest -Recurse -Force
}
@{ runtimeSyntax = 'passed'; runtimePlan = 'passed'; nativeHostIdentityGuards = 'passed'; syntax = 'passed'; plan = 'passed'; argumentForwarding = 'passed'; realWslInstallation = $false; realReboot = $false } | ConvertTo-Json
