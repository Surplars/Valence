param([Parameter(Mandatory=$true)][string]$VivadoBin,[Parameter(Mandatory=$true)][string]$Fixture)
$ErrorActionPreference='Stop'
Push-Location -LiteralPath $Fixture
try {
 if(Test-Path cycle-result.json){throw 'Preserve prior evidence'}
 & (Join-Path $VivadoBin 'xvlog.bat') --sv -f sources.f *> compile.log
 if($LASTEXITCODE){throw 'xvlog failed'}
 & (Join-Path $VivadoBin 'xelab.bat') shared_quiesce_tb -s shared_quiesce --timescale 1ps/1ps --debug typical --mt 2 *> elaborate.log
 if($LASTEXITCODE){throw 'xelab failed'}
 & (Join-Path $VivadoBin 'xsim.bat') shared_quiesce -tclbatch run.tcl -log positive-xsim.log *> positive-console.log
 $positive=Get-Content positive-console.log -Raw
 if($LASTEXITCODE -or $positive -notmatch 'SHARED_QUIESCE_CYCLE_PASS' -or $positive -match 'Fatal:'){throw 'Positive cycle fixture failed'}
 & (Join-Path $VivadoBin 'xsim.bat') shared_quiesce -tclbatch run.tcl -testplusarg BAD_ORACLE -log negative-xsim.log *> negative-console.log
 $negative=Get-Content negative-console.log -Raw
 if($negative -notmatch 'ORACLE_NEGATIVE_REJECT' -or $negative -match 'SHARED_QUIESCE_CYCLE_PASS'){throw 'Bad scoreboard did not reject'}
 @{result='PASS';raw_period_ps=8000;quiesce_phase_ps=719;stopped_ack_retention=$true;raw_wake_while_stopped=$true;two_actual_managed_progress_stages=$true;cold_reset_while_stopped=$true;exact_payload_delay_cycles=64;negative_oracle='REJECTED';whole_mac_acceptance=$false;physical_signoff=$false;utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content cycle-result.json
 Get-Content cycle-result.json
} finally {Pop-Location}
