param(
 [Parameter(Mandatory=$true)][string]$VivadoBin,
 [Parameter(Mandatory=$true)][string]$DutDir,
 [Parameter(Mandatory=$true)][string]$Fixture
)
$ErrorActionPreference='Stop'
$dutPath=(Resolve-Path -LiteralPath $DutDir).Path
$benchPath=Join-Path $PSScriptRoot 'packet-dma-control-tb.sv'
if(!(Test-Path -LiteralPath (Join-Path $dutPath 'EthernetPacketDma.sv'))){throw 'Emit ip.PacketDmaControlBatchMain before running this fixture'}
New-Item -ItemType Directory -Force -Path $Fixture | Out-Null
$fixturePath=(Resolve-Path -LiteralPath $Fixture).Path
Push-Location -LiteralPath $fixturePath
try {
 if(Test-Path -LiteralPath cycle-result.json){throw 'Preserve prior packet DMA evidence; choose a fresh Fixture'}
 $sources=@(Get-ChildItem -LiteralPath $dutPath -Filter '*.sv' -File | Sort-Object Name | ForEach-Object {'"'+$_.FullName.Replace('\','/')+'"'})
 $sources+=('"'+$benchPath.Replace('\','/')+'"')
 $sources | Set-Content sources.f
 "run all`nquit" | Set-Content run.tcl
 & (Join-Path $VivadoBin 'xvlog.bat') --sv -f sources.f *> compile.log
 if($LASTEXITCODE){throw 'Packet DMA xvlog failed; see compile.log'}
 & (Join-Path $VivadoBin 'xelab.bat') packet_dma_control_tb -s packet_dma_control --timescale 1ns/1ps --debug typical --mt 2 *> elaborate.log
 if($LASTEXITCODE){throw 'Packet DMA xelab failed; see elaborate.log'}
 & (Join-Path $VivadoBin 'xsim.bat') packet_dma_control -tclbatch run.tcl -log positive-xsim.log *> positive-console.log
 $positiveExit=$LASTEXITCODE
 $positive=Get-Content -LiteralPath positive-console.log -Raw
 if($positiveExit -or $positive -notmatch 'PACKET_DMA_CONTROL_BATCH_PASS' -or $positive -match 'Fatal:'){throw 'Packet DMA positive generated-DUT scoreboard failed'}
 & (Join-Path $VivadoBin 'xsim.bat') packet_dma_control -tclbatch run.tcl -testplusarg BAD_ORACLE -log negative-xsim.log *> negative-console.log
 $negative=Get-Content -LiteralPath negative-console.log -Raw
 if($negative -notmatch 'ORACLE_NEGATIVE_REJECT' -or $negative -match 'PACKET_DMA_CONTROL_BATCH_PASS'){throw 'Packet DMA intentionally damaged oracle did not reject'}
 $match=[regex]::Match($positive,'PACKET_DMA_CONTROL_BATCH_PASS cycles=(\d+) control=(\d+) replies=(\d+) memory=(\d+) memory_replies=(\d+) denied=(\d+) held_memory=(\d+) delayed_memory=(\d+) full_replies=(\d+)')
 if(!$match.Success){throw 'Packet DMA coverage summary missing'}
 @{
  result='PASS';dut='generated EthernetPacketDma';simulator='native Vivado xsim';
  cycles=[int]$match.Groups[1].Value;control_requests=[int]$match.Groups[2].Value;
  control_replies=[int]$match.Groups[3].Value;memory_writes=[int]$match.Groups[4].Value;
  memory_replies=[int]$match.Groups[5].Value;denied_requests=[int]$match.Groups[6].Value;
  held_memory_cycles=[int]$match.Groups[7].Value;delayed_memory_cycles=[int]$match.Groups[8].Value;
  full_control_reply_cycles=[int]$match.Groups[9].Value;
  all_256_offsets=$true;invalid_size_mask_address_stop=$true;
  same_cycle_post_stop_cancellation=$true;invalid_stop_preserves_launch=$true;
  accepted_write_response_drain=$true;held_offer_survives_stop=$true;
  posted_and_legacy_rx=$true;negative_oracle='REJECTED';
  physical_signoff=$false;utc=[DateTime]::UtcNow.ToString('o')
 } | ConvertTo-Json | Set-Content cycle-result.json
 Get-Content -LiteralPath cycle-result.json
} finally {Pop-Location}
