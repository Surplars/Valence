param(
 [Parameter(Mandatory=$true)][string]$VivadoBin,
 [Parameter(Mandatory=$true)][string]$Fixture
)
$ErrorActionPreference='Stop'
Push-Location -LiteralPath $Fixture
try {
 if(Test-Path cycle-result.json){throw 'Preserve prior run'}
 & (Join-Path $VivadoBin 'xvlog.bat') --sv -f sources.f *> compile.log
 if($LASTEXITCODE){throw 'xvlog failed; see compile.log'}
 & (Join-Path $VivadoBin 'xelab.bat') idle_cycle_tb -s recovery_idle --timescale 1ps/1ps --debug typical --mt 2 *> elaborate.log
 if($LASTEXITCODE){throw 'xelab failed; see elaborate.log'}
 & (Join-Path $VivadoBin 'xsim.bat') recovery_idle -tclbatch run.tcl -log positive-xsim.log *> positive-console.log
 $positiveExit=$LASTEXITCODE
 $positive=Get-Content positive-console.log -Raw
 if($positiveExit -or $positive -notmatch 'IDLE_CYCLE_PASS' -or $positive -match 'Fatal:|IDLE_CYCLE_TIMEOUT'){throw 'Positive cycle run failed'}
 & (Join-Path $VivadoBin 'xsim.bat') recovery_idle -tclbatch run.tcl -testplusarg BAD_ORACLE -log negative-xsim.log *> negative-console.log
 $negative=Get-Content negative-console.log -Raw
 if($negative -notmatch 'ORACLE_NEGATIVE_REJECT' -or $negative -match 'IDLE_CYCLE_PASS'){throw 'Negative scoreboard control did not reject'}
 [ordered]@{result='PASS';fixture='actual-unmodified-CommonCpuClockBoundary';positive_exit=$positiveExit;negative_control='ORACLE_NEGATIVE_REJECT';intended_cpu_hz=300000000;cpu_period_ps=3334;fabric_period_ps=4000;independent_phase_ps=719;messages_each_direction=26;backpressure_required=$true;first_offer_after_idle_required=$true;physical_signoff=$false;gsim_cpu_acceptance=$false;utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content cycle-result.json
 Get-Content cycle-result.json
} finally {Pop-Location}
