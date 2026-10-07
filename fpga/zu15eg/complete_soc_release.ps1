# Continue one frozen, short-tested candidate through board signoff and release.
# Never lower the requested clock, change timing exceptions, or program hardware.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$CandidateRoot,
    [ValidateSet('soc','soc-runtime')][string]$SocDirectory = 'soc'
)
$ErrorActionPreference = 'Stop'
$candidate = (Resolve-Path -LiteralPath $CandidateRoot).ProviderPath
$artifactRoot = [IO.Path]::GetFullPath('E:\VM\Share\Valence-rtl') + '\'
if (-not $candidate.StartsWith($artifactRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Candidate must be an explicitly named artifact subdirectory'
}
$snapshot = Join-Path $candidate 'build-snapshot'
$guard = Join-Path $snapshot 'run_synthesis_guarded.ps1'
$soc = Join-Path (Join-Path $candidate $SocDirectory) 'soc_candidate.dcp'
$rom = Join-Path $candidate 'ip-build\board_ip.gen\sources_1\ip\blk_mem_gen_0\blk_mem_gen_0.dcp'
$short = Get-Content -LiteralPath (Join-Path $candidate 'short-tests.json') -Raw | ConvertFrom-Json
if ($short.profile -notin @('staged-rom-boundary','staged-control-heads','staged-throughput') -or $short.cpu_hz -ne 100000000 -or
    $short.uart_baud -ne 460800 -or $short.issue_width -ne 2 -or
    $short.status -notin @('passed','passed_after_test_driver_corrections')) { throw 'Wrong/failed short-test candidate' }
if (-not (Test-Path -LiteralPath $soc)) { throw 'Complete SoC synthesis first' }
$rtlManifest = Get-Content -LiteralPath (Join-Path $candidate 'rtl-inputs.json') -Raw | ConvertFrom-Json
foreach ($file in $rtlManifest.files) {
    $path = Join-Path (Join-Path $candidate 'rtl') $file.path
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $file.sha256) {
        throw ('Frozen RTL changed: ' + $file.path)
    }
}
function Invoke-CandidateStage([string]$name, [string]$script, [string[]]$arguments, [int]$minutes) {
    Write-Output ('CANDIDATE_STAGE: ' + $name)
    & $guard -Script (Join-Path $snapshot $script) -OutputDirectory (Join-Path $candidate ($name + '-log')) -TclArguments $arguments -MaxMinutes $minutes
    if ($LASTEXITCODE -ne 0) { throw ('Candidate stage failed: ' + $name + ' exit=' + $LASTEXITCODE) }
}
Invoke-CandidateStage 'board-assembly' 'assemble_soc_candidate.tcl' @(
    $soc, (Join-Path $candidate 'ip-build\board_ip.srcs\sources_1\ip'),
    (Join-Path $snapshot 'soc_top_ddr.sv'), (Join-Path $snapshot 'board_ddr.xdc'),
    (Join-Path $snapshot 'pl_ddr4_pins.xdc'), (Join-Path $candidate 'board'), '100000000',
    (Join-Path $candidate 'vendor-mig\ZU15EG.srcs\sources_1\ip\ddr4_0\ddr4_0.xci'), 'assemble'
) 25
Invoke-CandidateStage 'board-placement' 'place_soc_checkpoint.tcl' @(
    (Join-Path $candidate 'board\assembled.dcp'), (Join-Path $candidate 'implementation'),
    '100000000', 'AltSpreadLogic_high', 'AlternateCLBRouting', 'place-only'
) 60
Invoke-CandidateStage 'board-routing' 'route_soc_checkpoint.tcl' @(
    (Join-Path $candidate 'implementation\placed.dcp'), (Join-Path $candidate 'implementation\routing'),
    '100000000', 'AlternateCLBRouting', 'route-only'
) 90
Invoke-CandidateStage 'board-post-route' 'route_soc_checkpoint.tcl' @(
    (Join-Path $candidate 'implementation\routing\routed_initial.dcp'), (Join-Path $candidate 'implementation\post-route'),
    '100000000', 'AlternateCLBRouting', 'post-route'
) 45
Invoke-CandidateStage 'release' 'release_soc_partition.tcl' @(
    $soc, (Join-Path $candidate 'implementation\post-route\routed.dcp'),
    (Join-Path $candidate 'release'), '100000000', '460800', $rom,
    (Join-Path $candidate 'firmware\bootrom.bin')
) 25
$release = Join-Path $candidate 'release'
$bit = Join-Path $release 'valence_ddr100_uart460800_fifo.bit'
if (-not (Test-Path -LiteralPath $bit) -or (Get-Item -LiteralPath $bit).Length -lt 1000000) {
    throw 'Signoff did not produce a complete bitstream'
}
$linux = Join-Path $candidate 'linux-final'
$linuxManifest = Get-Content -LiteralPath (Join-Path $linux 'manifest.json') -Raw | ConvertFrom-Json
if ($linuxManifest.cpu_hz -ne 100000000 -or $linuxManifest.uart_baud -ne 460800) {
    throw 'Linux timebase or UART does not match the bitstream'
}
foreach ($name in @('opensbi_linux_ddr100_uart460800.bin', 'valence-ddr100_uart460800.dtb')) {
    $expected = $linuxManifest.files.PSObject.Properties[$name].Value.sha256
    if ((Get-FileHash -LiteralPath (Join-Path $linux $name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
        throw ('Linux input changed: ' + $name)
    }
    Copy-Item -LiteralPath (Join-Path $linux $name) -Destination (Join-Path $release $name)
}
Copy-Item -LiteralPath (Join-Path $linux 'manifest.json') -Destination (Join-Path $release 'linux_manifest.json')
Copy-Item -LiteralPath (Join-Path $candidate 'firmware\uart_load.py') -Destination (Join-Path $release 'uart_load.py')
Copy-Item -LiteralPath (Join-Path $candidate 'short-tests.json') -Destination (Join-Path $release 'short-tests.json')
Get-FileHash -LiteralPath $bit -Algorithm SHA256
Write-Output ('CANDIDATE_RELEASE: COMPLETE ' + $release)
Write-Output 'Board programming and physical Linux boot are user-operated; not claimed verified.'
