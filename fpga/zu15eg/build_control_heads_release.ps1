[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$AcceptanceDirectory,
    [Parameter(Mandatory)][string]$CandidateRoot,
    [ValidateSet('staged-control-heads','staged-throughput')][string]$Profile = 'staged-control-heads',
    [switch]$SynthesisOnly,
    [switch]$ResumeStaging
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
& (Join-Path $PSScriptRoot 'freeze_control_heads_candidate.ps1') -AcceptanceDirectory $AcceptanceDirectory -CandidateRoot $CandidateRoot -Profile $Profile -ResumeStaging:$ResumeStaging
$candidate = (Resolve-Path -LiteralPath $CandidateRoot).ProviderPath
$source = Get-Content -LiteralPath (Join-Path $candidate 'source-inputs.json') -Raw | ConvertFrom-Json
function Confirm-Source {
    foreach ($file in $source.source_files) {
        if ((Get-FileHash -LiteralPath (Join-Path $repo $file.path) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $file.sha256) {
            throw ('Source changed during export: ' + $file.path)
        }
    }
}
Confirm-Source
$rtl = Join-Path $candidate 'rtl'
[void][IO.Directory]::CreateDirectory($rtl)
$wslRtl = '/mnt/' + $rtl.Substring(0,1).ToLowerInvariant() + $rtl.Substring(2).Replace('\','/')
& wsl.exe -d Ubuntu-24.04 --cd /home/openion/Valence -- mill -i IonSoC.test.runMain ooo.BoardSocMain $wslRtl 100000000 ddr $Profile 460800 2 2 1 2>&1 |
    Tee-Object -FilePath (Join-Path $candidate 'rtl-export.log')
if ($LASTEXITCODE -ne 0) { throw 'RTL export failed' }
Confirm-Source
if (-not (Test-Path -LiteralPath (Join-Path $rtl 'BoardSocTop.sv'))) { throw 'Missing exported board SoC' }
$rtlFiles = foreach ($file in (Get-ChildItem -LiteralPath $rtl -File -Recurse | Sort-Object FullName)) {
    [ordered]@{path=$file.FullName.Substring($rtl.Length+1).Replace('\','/');bytes=$file.Length
        sha256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
}
[ordered]@{root=$candidate;profile=$Profile;cpu_hz=100000000;uart_baud=460800;files=@($rtlFiles)} |
    ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $candidate 'rtl-inputs.json') -Encoding utf8
$snapshot = Join-Path $candidate 'build-snapshot'
& (Join-Path $snapshot 'run_synthesis_guarded.ps1') -Script (Join-Path $snapshot 'synth_soc_partition.tcl') `
    -OutputDirectory (Join-Path $candidate 'soc-runtime-log') -TclArguments @(
        $rtl, (Join-Path $candidate 'ip-build\board_ip.gen\sources_1\ip\blk_mem_gen_0\blk_mem_gen_0.dcp'),
        (Join-Path $candidate 'soc-runtime'), '10', '10', 'RuntimeOptimized', 'rebuilt'
    ) -MaxMinutes 45
if ($LASTEXITCODE -ne 0) { throw ('SoC synthesis failed: ' + $LASTEXITCODE) }
if ($SynthesisOnly) {
    Write-Output 'Combined synthesis completed; routed 100 MHz timing is not yet verified.'
    return
}
& (Join-Path $snapshot 'complete_soc_release.ps1') -CandidateRoot $candidate -SocDirectory soc-runtime
