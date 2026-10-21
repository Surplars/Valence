param(
 [Parameter(Mandatory=$true)][string]$VivadoBin,
 [Parameter(Mandatory=$true)][string]$DutDir,
 [Parameter(Mandatory=$true)][string]$Fixture
)
$ErrorActionPreference='Stop'
$dutPath=(Resolve-Path -LiteralPath $DutDir).Path
$benchPath=Join-Path $PSScriptRoot 'axi-cdc-channels-tb.sv'
$top='Axi4CdcFixture'
if(!(Test-Path -LiteralPath (Join-Path $dutPath ($top+'.sv')))){throw 'Emit Axi4CdcFixture first'}
if(Test-Path -LiteralPath $Fixture){throw 'Preserve previous evidence; choose a fresh fixture directory'}
New-Item -ItemType Directory -Path $Fixture | Out-Null
Push-Location -LiteralPath (Resolve-Path -LiteralPath $Fixture).Path
try {
 $sources=@(Get-ChildItem -LiteralPath $dutPath -Filter '*.sv' -File | Sort-Object Name | ForEach-Object {'"'+$_.FullName.Replace('\','/')+'"'})
 $sources+=('"'+$benchPath.Replace('\','/')+'"')
 $sources | Set-Content sources.f
 "run all`nquit" | Set-Content run.tcl
 & (Join-Path $VivadoBin 'xvlog.bat') --sv -f sources.f *> compile.log
 if($LASTEXITCODE){throw 'AXI CDC xvlog failed'}
 & (Join-Path $VivadoBin 'xelab.bat') axi_cdc_channels_tb -s axi_cdc_channels --timescale 1ns/1ps --debug typical --mt 2 *> elaborate.log
 if($LASTEXITCODE){throw 'AXI CDC xelab failed'}
 & (Join-Path $VivadoBin 'xsim.bat') axi_cdc_channels -tclbatch run.tcl -log positive-xsim.log *> positive-console.log
 $positive=Get-Content -LiteralPath positive-console.log -Raw
 if($LASTEXITCODE -or $positive -notmatch 'AXI_CDC_PASS' -or $positive -match 'Fatal:|AXI_CDC_FAIL'){throw 'AXI CDC positive oracle failed'}
 & (Join-Path $VivadoBin 'xsim.bat') axi_cdc_channels -tclbatch run.tcl -testplusarg BAD_ORACLE -log negative-xsim.log *> negative-console.log
 $negative=Get-Content -LiteralPath negative-console.log -Raw
 if($negative -notmatch 'ORACLE_NEGATIVE_REJECT' -or $negative -notmatch 'Fatal:' -or $negative -match 'AXI_CDC_PASS'){throw 'AXI CDC negative oracle did not reject'}
 $summary=[regex]::Match($positive,'AXI_CDC_PASS[^\r\n]+').Value
 $result=[ordered]@{result='PASS';simulator='native xsim';dut='Axi4ClockDomainBoundary';
  scope='synthetic complete channel conservation under independent clock edges, stalls and common reset';
  negative_oracle='REJECTED';transaction_owner_drain=$false;physical_signoff=$false;
  utc=[DateTime]::UtcNow.ToString('o')}
 foreach($m in [regex]::Matches($summary,'(\w+)=(\d+)')){$result[$m.Groups[1].Value]=[int]$m.Groups[2].Value}
 $result | ConvertTo-Json | Set-Content cycle-result.json
 Get-Content cycle-result.json
} finally {Pop-Location}
