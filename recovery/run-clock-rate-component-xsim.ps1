param(
 [Parameter(Mandatory=$true)][string]$VivadoBin,
 [Parameter(Mandatory=$true)][string]$DutDir,
 [Parameter(Mandatory=$true)][string]$Fixture
)
$ErrorActionPreference='Stop'
$dutPath=(Resolve-Path -LiteralPath $DutDir).Path
$benchPath=Join-Path $PSScriptRoot 'clock-rate-component-tb.sv'
if(!(Test-Path -LiteralPath (Join-Path $dutPath 'ClockRateManagementBoundary.sv'))){throw 'Emit ClockRateComponentMain first'}
if(Test-Path -LiteralPath $Fixture){throw 'Preserve previous evidence; choose a fresh fixture directory'}
New-Item -ItemType Directory -Path $Fixture | Out-Null
Push-Location -LiteralPath (Resolve-Path -LiteralPath $Fixture).Path
try {
 $sources=@(Get-ChildItem -LiteralPath $dutPath -Filter '*.sv' -File | Sort-Object Name | ForEach-Object {'"'+$_.FullName.Replace('\','/')+'"'})
 $sources+=('"'+$benchPath.Replace('\','/')+'"')
 $sources | Set-Content sources.f
 "run all`nquit" | Set-Content run.tcl
 & (Join-Path $VivadoBin 'xvlog.bat') --sv -f sources.f *> compile.log
 if($LASTEXITCODE){throw 'clock-rate xvlog failed'}
 & (Join-Path $VivadoBin 'xelab.bat') clock_rate_component_tb -s clock_rate_component --timescale 1ns/1ps --debug typical --mt 2 *> elaborate.log
 if($LASTEXITCODE){throw 'clock-rate xelab failed'}
 & (Join-Path $VivadoBin 'xsim.bat') clock_rate_component -tclbatch run.tcl -log positive-xsim.log *> positive-console.log
 $positive=Get-Content -LiteralPath positive-console.log -Raw
 if($LASTEXITCODE -or $positive -notmatch 'RATE_COMPONENT_PASS' -or $positive -match 'Fatal:|RATE_COMPONENT_FAIL'){throw 'clock-rate positive oracle failed'}
 & (Join-Path $VivadoBin 'xsim.bat') clock_rate_component -tclbatch run.tcl -testplusarg BAD_ORACLE -log negative-xsim.log *> negative-console.log
 $negative=Get-Content -LiteralPath negative-console.log -Raw
 if($negative -notmatch 'ORACLE_NEGATIVE_REJECT' -or $negative -notmatch 'Fatal:' -or $negative -match 'RATE_COMPONENT_PASS'){throw 'clock-rate negative oracle did not reject'}
 $summary=[regex]::Match($positive,'RATE_COMPONENT_PASS[^\r\n]+').Value
 $result=[ordered]@{result='PASS';simulator='native Vivado2025.2 xsim';dut='actual ClockRateManagementBoundary and AON controllers';
  backend='behavioral model, not vendor DRP or production quiesce integration';negative_oracle='REJECTED';
  synthetic_qualification_flags=$true;production_platform_connected=$false;physical_signoff=$false;
  utc=[DateTime]::UtcNow.ToString('o')}
 foreach($m in [regex]::Matches($summary,'(\w+)=(\d+)')){$result[$m.Groups[1].Value]=[int]$m.Groups[2].Value}
 $result | ConvertTo-Json | Set-Content cycle-result.json
 Get-Content cycle-result.json
} finally {Pop-Location}
