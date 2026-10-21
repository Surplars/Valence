param(
 [Parameter(Mandatory=$true)][string]$VivadoBin,
 [Parameter(Mandatory=$true)][string]$DutDir,
 [Parameter(Mandatory=$true)][string]$Fixture
)
$ErrorActionPreference='Stop'
$dutPath=(Resolve-Path -LiteralPath $DutDir).Path
$benchPath=Join-Path $PSScriptRoot 'store-clear-admission-tb.sv'
if(!(Test-Path -LiteralPath (Join-Path $dutPath 'StoreClearAdmissionBatch.sv'))){throw 'Emit inorder.StoreClearAdmissionBatchMain first'}
New-Item -ItemType Directory -Force -Path $Fixture | Out-Null
Push-Location -LiteralPath (Resolve-Path -LiteralPath $Fixture).Path
try {
 if(Test-Path -LiteralPath cycle-result.json){throw 'Preserve prior evidence; select a fresh Fixture'}
 $sources=@(Get-ChildItem -LiteralPath $dutPath -Filter '*.sv' -File | Sort-Object Name | ForEach-Object {'"'+$_.FullName.Replace('\','/')+'"'})
 $sources+=('"'+$benchPath.Replace('\','/')+'"')
 $sources | Set-Content sources.f
 "run all`nquit" | Set-Content run.tcl
 & (Join-Path $VivadoBin 'xvlog.bat') --sv -f sources.f *> compile.log
 if($LASTEXITCODE){throw 'store-clear xvlog failed'}
 & (Join-Path $VivadoBin 'xelab.bat') store_clear_admission_tb -s store_clear_admission --timescale 1ns/1ps --debug typical --mt 2 *> elaborate.log
 if($LASTEXITCODE){throw 'store-clear xelab failed'}
 & (Join-Path $VivadoBin 'xsim.bat') store_clear_admission -tclbatch run.tcl -log positive-xsim.log *> positive-console.log
 $positive=Get-Content -LiteralPath positive-console.log -Raw
 if($LASTEXITCODE -or $positive -notmatch 'STORE_CLEAR_ADMISSION_PASS' -or $positive -match 'Fatal:|STORE_CLEAR_FAIL'){throw 'actual-DT store-clear positive scoreboard failed'}
 & (Join-Path $VivadoBin 'xsim.bat') store_clear_admission -tclbatch run.tcl -testplusarg BAD_ORACLE -log negative-xsim.log *> negative-console.log
 $negative=Get-Content -LiteralPath negative-console.log -Raw
 if($negative -notmatch 'ORACLE_NEGATIVE_REJECT' -or $negative -notmatch 'Fatal:' -or $negative -match 'STORE_CLEAR_ADMISSION_PASS'){throw 'store-clear bad oracle did not reject'}
 $match=[regex]::Match($positive,'STORE_CLEAR_ADMISSION_PASS cycles=(\d+) requests=(\d+) responses=(\d+) stores=(\d+) reads=(\d+) atomics=(\d+) faults=(\d+) ahead_blocked=(\d+) handoffs=(\d+) blocked=(\d+) native=(\d+) invalidations=(\d+)')
 if(!$match.Success){throw 'store-clear coverage summary missing'}
 $result=[ordered]@{result='PASS';dut='actual FiveStageAddressTranslation CommonCpuProfile.I1.i1';simulator='native Vivado xsim';negative_oracle='REJECTED';seed='5a64123a';ordinary_store_event_matches_accepted_history=$true;read_ahead_store_never_accepted=$true;physical_signoff=$false;utc=[DateTime]::UtcNow.ToString('o')}
 $names=@('cycles','requests','responses','stores','reads','atomics','faults','read_ahead_store_blocked','read_handoffs','blocked_reply_cycles','native_requests','invalidate_cycles')
 for($i=0;$i -lt $names.Count;$i++){$result[$names[$i]]=[int]$match.Groups[$i+1].Value}
 $result | ConvertTo-Json | Set-Content cycle-result.json
 Get-Content -LiteralPath cycle-result.json
} finally {Pop-Location}
