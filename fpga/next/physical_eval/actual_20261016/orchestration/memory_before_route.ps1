$ErrorActionPreference='Stop'
$diagRoot=$args[0]
$routeProcessId=[int]$args[1]
$ram=Get-CimInstance Win32_OperatingSystem
$process=Get-Process -Id $routeProcessId
$free=[long]$ram.FreePhysicalMemory*1KB
$available=$free+$process.PrivateMemorySize64
$threads=if($free -ge 8GB -and $available -ge 17GB){8}else{4}
if($free -lt 6GB -or $available -lt 15GB){throw 'Insufficient memory headroom for route; original placed DCP preserved'}
$record=[ordered]@{utc=[DateTime]::UtcNow.ToString('o');vivadoPid=$routeProcessId;freePhysicalMemoryKiB=$ram.FreePhysicalMemory;currentPrivateBytes=$process.PrivateMemorySize64;selectedThreads=$threads;estimatedRouteBudgetGiB=if($threads -eq 8){11}else{9};reservedGiB=6;processes=@(Get-CimInstance Win32_Process|Where-Object {$_.Name -eq 'vivado.exe'}|Select-Object ProcessId,ParentProcessId,CommandLine)}
$record|ConvertTo-Json -Depth 5|Set-Content -LiteralPath (Join-Path $diagRoot 'run-route-r1\memory-before-route.json') -Encoding utf8
@("set_param general.maxThreads $threads",('diag_event route_threads applied {'+$threads+' freeKiB='+$ram.FreePhysicalMemory+' reservedGiB=6}'))|Set-Content -LiteralPath (Join-Path $diagRoot 'run-route-r1\route-threads.tcl') -Encoding ascii
Write-Output ('MEMORY_BEFORE_ROUTE_PASS selectedThreads='+$threads+' freeKiB='+$ram.FreePhysicalMemory)
