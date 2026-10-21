param(
 [Parameter(Mandatory=$true)][string]$VivadoBin,
 [Parameter(Mandatory=$true)][string]$DutDir,
 [Parameter(Mandatory=$true)][string]$Fixture
)
$ErrorActionPreference='Stop'
$dutPath=(Resolve-Path -LiteralPath $DutDir).Path
$benchPath=Join-Path $PSScriptRoot 'gmac-ready-tb.sv'
if(!(Test-Path -LiteralPath (Join-Path $dutPath 'GmacReadyBatch.sv'))){throw 'Emit ip.GmacReadyBatchMain before running this fixture'}
New-Item -ItemType Directory -Force -Path $Fixture | Out-Null
$fixturePath=(Resolve-Path -LiteralPath $Fixture).Path
Push-Location -LiteralPath $fixturePath
try {
 if(Test-Path -LiteralPath cycle-result.json){throw 'Preserve prior GMAC ready evidence; choose a fresh Fixture'}
 $sources=@(Get-ChildItem -LiteralPath $dutPath -Filter '*.sv' -File | Sort-Object Name | ForEach-Object {'"'+$_.FullName.Replace('\','/')+'"'})
 $sources+=('"'+$benchPath.Replace('\','/')+'"')
 $sources | Set-Content sources.f
 "run all`nquit" | Set-Content run.tcl
 & (Join-Path $VivadoBin 'xvlog.bat') --sv -f sources.f *> compile.log
 if($LASTEXITCODE){throw 'GMAC ready xvlog failed; see compile.log'}
 & (Join-Path $VivadoBin 'xelab.bat') gmac_ready_tb -s gmac_ready --timescale 1ns/1ps --debug typical --mt 2 *> elaborate.log
 if($LASTEXITCODE){throw 'GMAC ready xelab failed; see elaborate.log'}
 & (Join-Path $VivadoBin 'xsim.bat') gmac_ready -tclbatch run.tcl -log positive-xsim.log *> positive-console.log
 $positiveExit=$LASTEXITCODE
 $positive=Get-Content -LiteralPath positive-console.log -Raw
 if($positiveExit -or $positive -notmatch 'GMAC_READY_BATCH_PASS' -or $positive -match 'Fatal:'){throw 'GMAC ready positive generated-DUT scoreboard failed'}
 & (Join-Path $VivadoBin 'xsim.bat') gmac_ready -tclbatch run.tcl -testplusarg BAD_ORACLE -log negative-xsim.log *> negative-console.log
 $negative=Get-Content -LiteralPath negative-console.log -Raw
 if($negative -notmatch 'ORACLE_NEGATIVE_REJECT' -or $negative -match 'GMAC_READY_BATCH_PASS'){throw 'GMAC ready intentionally damaged oracle did not reject'}
 $match=[regex]::Match($positive,'GMAC_READY_BATCH_PASS cycles=(\d+) accepted=(\d+) replied=(\d+) mdio=(\d+) blocked=(\d+) denied_no_credit=(\d+) full=(\d+) stable=(\d+)')
 if(!$match.Success){throw 'GMAC ready coverage summary missing'}
 @{
  result='PASS';dut='generated GmacReadyBatch / TileLinkGmacControl';simulator='native Vivado xsim';
  ports=4;seed='47ac1234';cycles=[int]$match.Groups[1].Value;
  requests=[int]$match.Groups[2].Value;replies=[int]$match.Groups[3].Value;
  mdio_commands=[int]$match.Groups[4].Value;legal_mdio_blocked_cycles=[int]$match.Groups[5].Value;
  denied_accepted_without_mdio_credit=[int]$match.Groups[6].Value;
  reply_queue_full_cycles=[int]$match.Groups[7].Value;stalled_response_cycles=[int]$match.Groups[8].Value;
  independent_original_ready_oracle=$true;reply_payload_metadata_order=$true;
  control_mac_rxstop_irq_restart_side_effects=$true;negative_oracle='REJECTED';
  physical_signoff=$false;utc=[DateTime]::UtcNow.ToString('o')
 } | ConvertTo-Json | Set-Content cycle-result.json
 Get-Content -LiteralPath cycle-result.json
} finally {Pop-Location}
