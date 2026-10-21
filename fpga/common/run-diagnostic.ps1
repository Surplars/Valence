[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Manifest,
    [Parameter(Mandatory)][string]$Vivado,
    [Parameter(Mandatory)][string]$Python
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Native Windows required.' }
$manifestPath = [IO.Path]::GetFullPath($Manifest)
$root = Split-Path -Parent $manifestPath
$pythonExe = (Get-Command $Python -CommandType Application -ErrorAction Stop).Source
$vivadoExe = (Get-Item -LiteralPath $Vivado -ErrorAction Stop).FullName
$env:VALENCE_WINDOWS_PYTHON = $pythonExe
$env:VALENCE_VIVADO_HOME = Split-Path -Parent (Split-Path -Parent $vivadoExe)
$checker = Join-Path $root 'fpga\common\diagnostic.py'
& $pythonExe $checker prepare --manifest $manifestPath
if ($LASTEXITCODE -ne 0) { throw 'Diagnostic preparation blocked.' }
$run = Join-Path $root 'diagnostic-run'
foreach ($phase in @('synthesis','implementation')) {
    & $pythonExe $checker check --manifest $manifestPath
    if ($LASTEXITCODE -ne 0) { throw 'Diagnostic input changed.' }
    $out = Join-Path $run $phase
    if (Test-Path -LiteralPath $out) { throw 'Preserve earlier diagnostic stage.' }
    [void][IO.Directory]::CreateDirectory($out)
    Push-Location -LiteralPath $out
    try {
        & $vivadoExe -mode batch -notrace -source (Join-Path $root 'fpga\common\diagnostic.tcl') -log vivado.log -journal vivado.jou -tclargs (Join-Path $run 'config.tcl') $phase
        if ($LASTEXITCODE -ne 0) { throw "Diagnostic $phase failed. Inspect preserved checkpoint/logs." }
        & $pythonExe $checker record --manifest $manifestPath --phase $phase
        if ($LASTEXITCODE -ne 0) { throw 'Diagnostic output evidence missing.' }
    } finally { Pop-Location }
}
[ordered]@{status='DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM';missing_functional_receipt=$true;physical_qualified=$false;board_tested=$false;bit_generated=$false} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'diagnostic-result.json') -Encoding UTF8
