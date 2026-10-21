param(
 [Parameter(Mandatory=$true)][string]$VivadoBin,
 [Parameter(Mandatory=$true)][string]$DutDir,
 [Parameter(Mandatory=$true)][string]$Fixture
)
$ErrorActionPreference='Stop'
$dutPath=(Resolve-Path -LiteralPath $DutDir).Path
$benchPath=Join-Path $PSScriptRoot 'imsic-rmw-tb.sv'
if(!(Test-Path -LiteralPath (Join-Path $dutPath 'Imsic.sv'))){throw 'Emit ip.ImsicRmwBatchMain before running this fixture'}
New-Item -ItemType Directory -Force -Path $Fixture | Out-Null
$fixturePath=(Resolve-Path -LiteralPath $Fixture).Path
Push-Location -LiteralPath $fixturePath
try {
 if(Test-Path -LiteralPath cycle-result.json){throw 'Preserve prior IMSIC RMW evidence; choose a fresh Fixture'}
 $sources=@(Get-ChildItem -LiteralPath $dutPath -Filter '*.sv' -File | Sort-Object Name | ForEach-Object {'"'+$_.FullName.Replace('\','/')+'"'})
 $sources+=('"'+$benchPath.Replace('\','/')+'"')
 $sources | Set-Content sources.f
 "run all`nquit" | Set-Content run.tcl
 & (Join-Path $VivadoBin 'xvlog.bat') --sv -f sources.f *> compile.log
 if($LASTEXITCODE){throw 'IMSIC RMW xvlog failed; see compile.log'}
 & (Join-Path $VivadoBin 'xelab.bat') imsic_rmw_tb -s imsic_rmw --timescale 1ns/1ps --debug typical --mt 2 *> elaborate.log
 if($LASTEXITCODE){throw 'IMSIC RMW xelab failed; see elaborate.log'}
 & (Join-Path $VivadoBin 'xsim.bat') imsic_rmw -tclbatch run.tcl -log positive-xsim.log *> positive-console.log
 $positiveExit=$LASTEXITCODE
 $positive=Get-Content -LiteralPath positive-console.log -Raw
 if($positiveExit -or $positive -notmatch 'IMSIC_RMW_BATCH_PASS' -or $positive -match 'Fatal:|IMSIC_FAIL'){throw 'IMSIC RMW positive generated-DUT scoreboard failed'}
 & (Join-Path $VivadoBin 'xsim.bat') imsic_rmw -tclbatch run.tcl -testplusarg BAD_ORACLE -log negative-xsim.log *> negative-console.log
 $negative=Get-Content -LiteralPath negative-console.log -Raw
 if($negative -notmatch 'ORACLE_NEGATIVE_REJECT' -or $negative -match 'IMSIC_RMW_BATCH_PASS'){throw 'IMSIC RMW intentionally damaged oracle did not reject'}
 $match=[regex]::Match($positive,'IMSIC_RMW_BATCH_PASS cycles=(\d+) csr=(\d+) mmio=(\d+) claims=(\d+) simultaneous=(\d+) blocked=(\d+)')
 if(!$match.Success){throw 'IMSIC RMW coverage summary missing'}
 @{
  result='PASS';dut='generated Imsic identities127 guestFiles2';simulator='native Vivado xsim';
  files=4;seed='152ac913';cycles=[int]$match.Groups[1].Value;
  csr_requests=[int]$match.Groups[2].Value;mmio_requests=[int]$match.Groups[3].Value;
  claims=[int]$match.Groups[4].Value;simultaneous_claim_msi=[int]$match.Groups[5].Value;
  blocked_response_cycles=[int]$match.Groups[6].Value;
  independent_architectural_bank_oracle=$true;old_response_and_priority=$true;
  threshold_highbits_rejection=$true;negative_oracle='REJECTED';
  physical_signoff=$false;utc=[DateTime]::UtcNow.ToString('o')
 } | ConvertTo-Json | Set-Content cycle-result.json
 Get-Content -LiteralPath cycle-result.json
} finally {Pop-Location}


