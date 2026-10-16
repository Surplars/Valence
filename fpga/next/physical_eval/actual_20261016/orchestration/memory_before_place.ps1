$ErrorActionPreference='Stop'
$root=$args[0]
$phase=if($args.Count -gt 1){$args[1]}else{'before-opt'}
$ram=Get-CimInstance Win32_OperatingSystem
$processes=@(Get-CimInstance Win32_Process | Where-Object {$_.Name -eq 'vivado.exe'} | Select-Object ProcessId,ParentProcessId,CommandLine)
$mine=@($processes|Where-Object {$_.CommandLine -like ('*'+$root+'*')})
$currentPrivate=0L
foreach($process in $mine){$currentPrivate+=(Get-Process -Id $process.ProcessId).PrivateMemorySize64}
$oldPeakBytes=[long](7881.727*1MB)
$estimatedGrowth=[Math]::Max(0L,$oldPeakBytes-$currentPrivate)
$freeBytes=[long]$ram.FreePhysicalMemory*1KB
$choice=if($freeBytes -ge 10GB -and ($freeBytes-$estimatedGrowth) -ge 6GB){8}else{4}
$data=[ordered]@{utc=[DateTime]::UtcNow.ToString('o');phase=$phase;freePhysicalMemoryKiB=$ram.FreePhysicalMemory;totalVisibleKiB=$ram.TotalVisibleMemorySize;currentDiagnosticPrivateBytes=$currentPrivate;historicalPlacePeakMB=7881.727;estimatedAdditionalBytes=$estimatedGrowth;reservedFreeBytes=6GB;selectedPlacementThreads=$choice;historicalLog='E:\VM\Share\Valence-rtl\Valence-combined-3554932-611-recovery-control-20261016-r1\physical-r4.log';processes=$processes}
$stamp=[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ')
$data|ConvertTo-Json -Depth 5|Set-Content -LiteralPath (Join-Path $root ('memory-'+$phase+'-'+$stamp+'.json')) -Encoding utf8
if($ram.FreePhysicalMemory -lt 6291456){throw 'Less than6GiB free before placement; preserve synthesis DCP and pause'}
$tclLines=@("set_param general.maxThreads $choice",('diag_event placement_threads applied {'+$choice+' freeKiB='+$ram.FreePhysicalMemory+' oldPeakMB=7881.727 reservedGiB=6}'))
$romGate=Join-Path $root 'external-rom-polarity-minimal-r3\r3_rom_graph_leaf_r3.tcl'
$romContract=Join-Path $root 'rom-preflight-official-r3\local-rom-contract.tcl'
if((Test-Path -LiteralPath $romGate) -and (Test-Path -LiteralPath $romContract)){
    $tclLines+=('source {'+($romGate -replace '\\','/')+'}')
    $tclLines+=('source {'+($romContract -replace '\\','/')+'}')
    $tclLines+='diag_event rom_gate_version applied {OFFICIAL_R3 d573df041cf6e78ed625b9db509f9575ede62732b5bc39cb68ab3596a1b637c0}'
}
$tclLines|Set-Content -LiteralPath (Join-Path $root 'placement-thread-choice.tcl') -Encoding ascii
Write-Output ('MEMORY_BEFORE_PLACE_PASS freeKiB='+$ram.FreePhysicalMemory+' selectedPlaceThreads='+$choice)
