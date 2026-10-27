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
@{ syntax = 'passed'; plan = 'passed'; argumentForwarding = 'passed'; realWslInstallation = $false; realReboot = $false } | ConvertTo-Json
