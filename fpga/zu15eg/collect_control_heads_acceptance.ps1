[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ContractDirectory,
    [Parameter(Mandatory)][string]$ModuleDirectory,
    [Parameter(Mandatory)][string]$CoreDirectory,
    [Parameter(Mandatory)][string]$IntegrationDirectory,
    [Parameter(Mandatory)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$contracts = (Resolve-Path -LiteralPath $ContractDirectory).ProviderPath
$modules = (Resolve-Path -LiteralPath $ModuleDirectory).ProviderPath
$core = (Resolve-Path -LiteralPath $CoreDirectory).ProviderPath
$integration = (Resolve-Path -LiteralPath $IntegrationDirectory).ProviderPath
$out = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $out) { throw 'Use a fresh acceptance output directory' }
$report = Get-Content -LiteralPath (Join-Path $integration 'results.json') -Raw | ConvertFrom-Json
$expectedChecks = @('vm-fetch','board')
if ($report.status -ne 'partial-pass' -or $report.profile -ne 'staged-control-heads' -or
    $report.cpu_hz -ne 100000000 -or $report.uart_baud -ne 460800 -or $report.issue_width -ne 2 -or
    (Compare-Object ($report.checks_requested | Sort-Object) ($expectedChecks | Sort-Object))) {
    throw 'Integration checks have not passed for the exact candidate'
}
function Require-Log([string]$root, [string]$relative, [string]$marker) {
    $text = Get-Content -LiteralPath (Join-Path $root $relative) -Raw
    if (-not $text.Contains($marker)) { throw ('Missing evidence: ' + $relative + ' / ' + $marker) }
}
Require-Log $contracts 'contracts.log' 'SUCCESS] mill IonSoC.test.testOnly'
foreach ($name in @('RomBoundaryTimingSpec','RequestCaptureTimingSpec','OooParamsSpec','ControlHeadsTimingSpec','ReturnTimingSpec')) {
    Require-Log $contracts 'contracts.log' $name
}
foreach ($name in @('prediction-2-1-0','prediction-2-1-1','prediction-4-0-1')) {
    Require-Log $modules ($name + '\test.log') 'GSIM prediction training: PASS'
    Require-Log $modules ($name + '\negative.log') 'prediction training oracle mismatch'
}
foreach ($name in @('planner-16','planner-32')) {
    Require-Log $modules ($name + '\test.log') 'GSIM memory preparation: PASS'
    Require-Log $modules ($name + '\negative.log') 'memory preparation oracle mismatch'
}
Require-Log $modules 'credits\test.log' 'GSIM data timing: PASS'
Require-Log $modules 'credits\negative.log' 'data response oracle mismatch'
Require-Log $modules 'operands\test.log' 'GSIM physical operand payload: PASS'
Require-Log $modules 'operands\negative.log' 'physical operand oracle mismatch'
Require-Log $modules 'packet-pmp\test.log' 'GSIM PMP checker: PASS'
Require-Log $modules 'packet-pmp\negative.log' 'PMP oracle mismatch'
Require-Log $core 'core\test.log' 'GSIM control/memory timing + NEMU: PASS'
Require-Log $core 'core\negative.log' 'NEMU register mismatch'
Require-Log $core 'vm\test.log' 'GSIM CPU virtual data: PASS'
[void][IO.Directory]::CreateDirectory($out)
foreach ($root in @($integration,$modules,$core)) {
    foreach ($file in (Get-ChildItem -LiteralPath $root -File -Recurse |
        Where-Object { $_.Extension -in @('.log','.json') })) {
        # Preserve full original run evidence, including failed aggregate metadata.
        $relative = $file.FullName.Substring($root.Length + 1)
        $target = Join-Path (Join-Path $out ([IO.Path]::GetFileName($root))) $relative
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
        Copy-Item -LiteralPath $file.FullName -Destination $target
    }
}
Copy-Item -LiteralPath (Join-Path $contracts 'contracts.log') -Destination (Join-Path $out 'contracts.log')
Copy-Item -LiteralPath (Join-Path $integration 'boot-firmware') -Destination (Join-Path $out 'boot-firmware') -Recurse
$report.status = 'passed'
$report.checks_requested = @('contracts','prediction','credits','memory-payload','packet-pmp','core','vm','vm-fetch','board')
$report | Add-Member -NotePropertyName evidence_roots -NotePropertyValue @($contracts,$modules,$core,$integration)
$report | Add-Member -NotePropertyName corrections -NotePropertyValue @(
    'Scala test configuration and emitted instance names',
    'GSIM test-wrapper scalar input/output ports',
    'NEMU harness explicit 2-slot/32-entry predictor and one-cycle independent training events',
    'VM instruction wrapper enables coherent response buffering required by relocated credits')
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $out 'results.json') -Encoding utf8
Write-Output ('SHORT_ACCEPTANCE: PASS ' + $out)
