param(
 [Parameter(Mandatory=$true)][string]$BuildDirectory,
 [Parameter(Mandatory=$true)][int]$SynthesisProcessId,
 [Parameter(Mandatory=$true)][string]$SourceCommit,
 [Parameter(Mandatory=$true)][string]$ProfileSha256
)
$ErrorActionPreference='Stop'
$repo=Split-Path $PSScriptRoot -Parent
$workspace=Split-Path $repo -Parent
$build=(Resolve-Path -LiteralPath $BuildDirectory).Path
$exitFile=Join-Path $build 'synthesis-exit.json'
$waitStart=[DateTime]::UtcNow
while(!(Test-Path -LiteralPath $exitFile)){
 if(! (Get-Process -Id $SynthesisProcessId -ErrorAction SilentlyContinue)){
  Start-Sleep -Seconds 2
  if(!(Test-Path -LiteralPath $exitFile)){throw 'Synthesis process ended without exit receipt; inspect original log, do not restart automatically.'}
 }
 if(([DateTime]::UtcNow-$waitStart).TotalHours -gt 4){throw 'Synthesis wait exceeded four hours; process left untouched.'}
 Start-Sleep -Seconds 15
}
$synth=Get-Content -LiteralPath $exitFile -Raw | ConvertFrom-Json
if($synth.exit_code -ne 0){throw 'Synthesis failed; preserve original log and checkpoints.'}
if($synth.source_commit -ne $SourceCommit){throw 'Synthesis source receipt differs.'}
$inputs=Get-Content -LiteralPath (Join-Path $build 'synthesis-inputs.json') -Raw | ConvertFrom-Json
if($inputs.emission_profile_sha256 -ne $ProfileSha256){throw 'Production profile receipt differs.'}
$checkpoint=Join-Path $build 'synthesized-unqualified.dcp'
$checkpointHash=(Get-FileHash -LiteralPath $checkpoint -Algorithm SHA256).Hash
$statusFile=Join-Path $workspace 'CURRENT/STATUS.json'
$state=Get-Content -LiteralPath $statusFile -Raw | ConvertFrom-Json
$state.source_commit=$SourceCommit
$state.preparation_commit=(& 'D:\TOOLS\ENV\Git\cmd\git.exe' -C $repo rev-parse HEAD)
$state.emission_profile_sha256=$ProfileSha256
$state.synthesis_directory=$build
$state.synthesis_pid=$null
$state.current_rtl=Join-Path $repo 'out/recovery-timing-batch-r1-production'
$state.linked_checkpoint=$checkpoint
$state.linked_checkpoint_sha256=$checkpointHash
$state.resume_checkpoint=$checkpoint
$state.resume_checkpoint_sha256=$checkpointHash
$state.status='TIMING_BATCH_SYNTHESIS_COMPLETE_AUTO_DIAGNOSTIC_PENDING'
$state | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $statusFile
$inventory=Join-Path $workspace 'CURRENT/recovery-ip-xdc-inventory/original-implementation-xdc.tcl'
$hub='E:\VM\Share\Valence-rtl\valence-i1-optional-20261019-r1\recovery-r1-quiesce-20261021-r1\ip\dbg_hub.dcp'
@{source_commit=$SourceCommit;preparation_commit=$state.preparation_commit;checkpoint_sha256=$checkpointHash;
 profile_sha256=$ProfileSha256;stage='LINKED';no_bit=$true;utc=[DateTime]::UtcNow.ToString('o')} |
 ConvertTo-Json | Set-Content -LiteralPath (Join-Path $build 'diagnostic-auto-launch.json')
& (Join-Path $PSScriptRoot 'CURRENT.ps1') -Mode RunDiagnostic -Stage LINKED `
 -Checkpoint $checkpoint -CheckpointSha256 $checkpointHash -IpConstraintInventory $inventory `
 -RetainedDebugHubDcp $hub -OutputDirectory (Join-Path $build 'diagnostic-implementation-r1')
exit $LASTEXITCODE
