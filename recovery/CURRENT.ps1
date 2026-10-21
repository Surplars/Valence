param(
 [ValidateSet('Status','RunDiagnostic')][string]$Mode='Status',
 [string]$OutputDirectory,
 [ValidateSet('LINKED','RESTORED','RAW_OPT','POST_OPT','PLACED')][string]$Stage='RESTORED',
 [string]$Checkpoint,
 [string]$CheckpointSha256,
 [string]$RetainedDebugHubDcp,
 [string]$IpConstraintInventory,
 [string]$StatusFile=(Join-Path $PSScriptRoot '../../CURRENT/STATUS.json')
)
$ErrorActionPreference='Stop'
$state=Get-Content -LiteralPath $StatusFile -Raw | ConvertFrom-Json
if($Mode -eq 'Status'){$state | ConvertTo-Json -Depth 8;return}
if(-not $OutputDirectory){throw 'RunDiagnostic requires a fresh native Windows OutputDirectory.'}
if($state.implementation_directory){
 $activeLog=Join-Path $state.implementation_directory 'implementation-console.log'
 $activeExit=Join-Path $state.implementation_directory 'implementation-exit.json'
 if((Test-Path -LiteralPath $activeLog) -and -not (Test-Path -LiteralPath $activeExit)){
  throw "Existing diagnostic may still be active: $activeLog. Monitor it before starting another."
 }
}
$repo=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$target=$state.resume_checkpoint
$expectedHash=$state.resume_checkpoint_sha256
if($Checkpoint){$target=$Checkpoint;$expectedHash=$CheckpointSha256}
if(-not $target -or -not $expectedHash){throw 'No hash-verified resume checkpoint recorded.'}
if((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $expectedHash){throw 'Resume checkpoint SHA256 mismatch.'}
$expectedName=@{LINKED='synthesized-unqualified.dcp';RESTORED='ip-restored-unqualified.dcp';RAW_OPT='optimized-unqualified.dcp';POST_OPT='post-opt-constrained-diagnostic.dcp';PLACED='placed-diagnostic.dcp'}[$Stage]
if((Split-Path -Leaf $target) -ne $expectedName){throw 'Checkpoint filename does not match declared stage.'}
if(-not (Test-Path -LiteralPath $state.vivado)){throw 'Recorded native Vivado executable unavailable.'}
if(Test-Path -LiteralPath $OutputDirectory){throw 'Output already exists; retain it and choose a fresh directory.'}
$out=(New-Item -ItemType Directory -Path $OutputDirectory).FullName
$hashes=@{}
foreach($folder in @('fpga/common','fpga/inorder','fpga/next')){
 foreach($file in Get-ChildItem -LiteralPath (Join-Path $repo $folder) -Filter '*.tcl' -File){
  $hashes[$file.FullName]=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
 }
}
$reference=Join-Path $repo 'recovery/mig-io-reference.tcl'
$hashes[$reference]=(Get-FileHash -LiteralPath $reference).Hash
if($Stage -eq 'LINKED'){
 if(!$IpConstraintInventory){throw 'LINKED requires the original IP implementation constraint inventory.'}
 $IpConstraintInventory=(Resolve-Path -LiteralPath $IpConstraintInventory).Path
 $inventoryHashes=Join-Path (Split-Path $IpConstraintInventory) 'original-implementation-xdc-hashes.json'
 foreach($row in (Get-Content -LiteralPath $inventoryHashes -Raw | ConvertFrom-Json)){
  if((Get-FileHash -LiteralPath $row.path).Hash -ne $row.sha256){throw "Original IP constraint hash mismatch: $($row.path)"}
  $hashes[$row.path]=$row.sha256
 }
 $hashes[$IpConstraintInventory]=(Get-FileHash -LiteralPath $IpConstraintInventory).Hash
}
if($RetainedDebugHubDcp){
 $hubHash=(Get-FileHash -LiteralPath $RetainedDebugHubDcp -Algorithm SHA256).Hash
 if($hubHash -ne 'F88A2EF15C36FC04273D93759D5885C436A86A0E33CBC61C75E12FC713D0D342'){throw 'Original debug hub DCP hash mismatch.'}
 $hashes[(Resolve-Path -LiteralPath $RetainedDebugHubDcp).Path]=$hubHash
}
@{mode='DIAGNOSTIC_IMPLEMENT_NO_BIT';rtl_source_commit=$state.source_commit;
 preparation_commit=$state.preparation_commit;profile_sha256=$state.emission_profile_sha256;
 checkpoint=$target;checkpoint_sha256=$expectedHash;resume_stage=$Stage;scripts_sha256=$hashes;
 final_signoff=$false;bitstream_generated=$false} | ConvertTo-Json -Depth 5 |
 Set-Content -LiteralPath (Join-Path $out 'implementation-inputs.json')
$state.implementation_directory=$out
$state.status='DIAGNOSTIC_IMPLEMENTATION_RUNNING_NOT_SIGNED_OFF'
$state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $StatusFile
$exitCode=-1
try{
 $inventoryArg='REUSE_HASH_VERIFIED_IP_RESTORED_CHECKPOINT'
 $mappingStage=$Stage
 if($Stage -eq 'LINKED'){$inventoryArg=$IpConstraintInventory;$mappingStage='RESTORED'}
 $mappingArgs=@($repo,$out,$target,$state.emission_profile_sha256,'1',$inventoryArg,'DIAGNOSTIC_IMPLEMENT_NO_BIT',$mappingStage)
 if($RetainedDebugHubDcp){$mappingArgs+=(Resolve-Path -LiteralPath $RetainedDebugHubDcp).Path}
 & $state.vivado -mode batch -notrace -source (Join-Path $repo 'fpga/common/recovery_map_constraints.tcl') `
  -log (Join-Path $out 'implementation-vivado.log') -journal (Join-Path $out 'implementation-vivado.jou') `
  -tclargs @mappingArgs `
  *> (Join-Path $out 'implementation-console.log')
 $exitCode=$LASTEXITCODE
} finally {
 @{exit_code=$exitCode;utc=[DateTime]::UtcNow.ToString('o');final_signoff=$false;bitstream_generated=$false} |
  ConvertTo-Json | Set-Content -LiteralPath (Join-Path $out 'implementation-exit.json')
 $state.status=if($exitCode -eq 0){'DIAGNOSTIC_REPORTS_COMPLETE_NOT_SIGNED_OFF'}else{'DIAGNOSTIC_BLOCKED_SEE_ORIGINAL_LOG'}
 $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $StatusFile
}
exit $exitCode
