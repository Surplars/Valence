# Native Windows only. Sequential stages; never launch a stale/failed downstream job.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Manifest,
    [Parameter(Mandatory)][string]$Vivado,
    [Parameter(Mandatory)][string]$Python,
    [switch]$GenerateBit
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Run this entry in native Windows PowerShell.' }
$manifestPath = [IO.Path]::GetFullPath($Manifest)
$root = Split-Path -Parent $manifestPath
$checker = Join-Path $root 'fpga\common\manifest.py'
$pythonExe = (Get-Command $Python -CommandType Application -ErrorAction Stop).Source
$env:VALENCE_WINDOWS_PYTHON = $pythonExe
$vivadoExe = (Get-Item -LiteralPath $Vivado -ErrorAction Stop).FullName
$env:VALENCE_VIVADO_HOME = Split-Path -Parent (Split-Path -Parent $vivadoExe)
foreach ($path in @($manifestPath, $pythonExe, $vivadoExe)) {
    if ($path -notmatch '^[A-Za-z]:[\\/]' -or $path.Contains('"')) { throw "Native Windows path required: $path" }
}
function Invoke-Check([string[]]$CheckArguments) {
    & $pythonExe $checker @CheckArguments
    if ($LASTEXITCODE -ne 0) { throw "Common package check failed: $($CheckArguments[0]) exit=$LASTEXITCODE" }
}
Invoke-Check @('prepare', '--manifest', $manifestPath)
$run = Join-Path $root 'local-run'
$config = Join-Path $run 'config.tcl'
$events = @()
function Invoke-VivadoStage([string]$Name, [string]$Script, [string[]]$StageArguments) {
    $folder = Join-Path $run $Name
    if (Test-Path -LiteralPath $folder) { throw "Preserve earlier evidence: $folder" }
    [void][IO.Directory]::CreateDirectory($folder)
    $started = Get-Date
    $exitCode = $null
    Push-Location -LiteralPath $folder
    try {
        & $vivadoExe -mode batch -notrace -source $Script -log (Join-Path $folder 'vivado.log') -journal (Join-Path $folder 'vivado.jou') -tclargs @StageArguments
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) { throw "Vivado stage $Name failed: exit=$exitCode" }
    } finally {
        Pop-Location
        $script:events += [ordered]@{ phase=$Name; started=$started.ToString('o'); finished=(Get-Date).ToString('o'); exit_code=$exitCode }
        $script:events | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $run 'stages.json') -Encoding UTF8
    }
}
try {
    foreach ($phase in @('simulation', 'synthesis', 'implementation')) {
        Invoke-Check @('check', '--manifest', $manifestPath, '--windows')
        Invoke-VivadoStage $phase (Join-Path $root 'fpga\common\stage.tcl') @($config, $phase)
        Invoke-Check @('stage', '--manifest', $manifestPath, '--windows', '--phase', $phase)
    }
    $dcp = Join-Path $run 'implementation\routed.dcp'
    $dcpHash = (Get-FileHash -LiteralPath $dcp -Algorithm SHA256).Hash.ToLowerInvariant()
    $generate = if ($GenerateBit) { '1' } else { '0' }
    Invoke-VivadoStage 'signoff' (Join-Path $root 'fpga\common\signoff.tcl') @($config, $pythonExe, $dcpHash, $generate)
    Invoke-Check @('signoff', '--manifest', $manifestPath, '--reports', (Join-Path $run 'signoff'), '--dcp', $dcp, '--dcp-sha256', $dcpHash)
    $release = [ordered]@{ status='PASS_REPORT_CONTRACT'; dcp_sha256=$dcpHash; board_tested=$false; bit_generated=$false }
    if ($GenerateBit) {
        $bit = Join-Path $run 'signoff\qualified.bit'
        if (-not (Test-Path -LiteralPath $bit) -or (Get-Item -LiteralPath $bit).Length -eq 0) { throw 'Requested bitstream is missing/empty.' }
        $release['bit_generated'] = $true
        $release['bit_sha256'] = (Get-FileHash -LiteralPath $bit -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $release | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'result.json') -Encoding UTF8
} catch {
    [ordered]@{ status='FAIL'; error=$_.Exception.Message; board_tested=$false } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'result.json') -Encoding UTF8
    throw
}
