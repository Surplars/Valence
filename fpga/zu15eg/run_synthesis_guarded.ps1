# One bounded Vivado batch job; only validated descendants may be stopped.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Script,
    [Parameter(Mandatory)][string]$OutputDirectory,
    [Parameter(Mandatory)][string[]]$TclArguments,
    [ValidateRange(1,180)][int]$MaxMinutes = 25,
    [string]$Vivado = 'E:\Xilinx\2025.1\Vivado\bin\vivado.bat'
)
$ErrorActionPreference = 'Stop'
$resolvedScript = (Resolve-Path -LiteralPath $Script).ProviderPath
$resolvedVivado = (Resolve-Path -LiteralPath $Vivado).ProviderPath
$resolvedOutput = [IO.Path]::GetFullPath($OutputDirectory)
$artifactRoot = [IO.Path]::GetFullPath('E:\VM\Share\Valence-rtl') + '\'
if (-not $resolvedOutput.StartsWith($artifactRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Output must be an explicitly named artifact subdirectory'
}
if ($resolvedOutput.Contains('"') -or $resolvedScript.Contains('"')) { throw 'Invalid quoted path' }
[void][IO.Directory]::CreateDirectory($resolvedOutput)
$logPath = Join-Path $resolvedOutput 'synth.log'
$journalPath = Join-Path $resolvedOutput 'synth.jou'
if ((Test-Path -LiteralPath $logPath) -or (Test-Path -LiteralPath $journalPath)) {
    throw 'Use a fresh run directory; do not overwrite previous evidence'
}
$jobArguments = @('-mode','batch','-notrace','-source',$resolvedScript,
    '-log',$logPath,'-journal',$journalPath,'-tclargs') + $TclArguments
foreach ($argument in $jobArguments) {
    if ($argument.Contains('"') -or $argument.IndexOf([char]13) -ge 0 -or
        $argument.IndexOf([char]10) -ge 0) { throw 'Invalid argument' }
}
$quotedArguments = $jobArguments | ForEach-Object { '"' + $_ + '"' }
$launchOptions = @{
    FilePath=$resolvedVivado; ArgumentList=$quotedArguments
    WorkingDirectory=$resolvedOutput; WindowStyle='Hidden'; PassThru=$true
}
$started = Get-Date
$launcher = Start-Process @launchOptions
$null = $launcher.Handle
Write-Output ('GUARDED_SYNTH: launcher={0} max_minutes={1} started={2:o}' -f
    $launcher.Id, $MaxMinutes, $started)
$known = @{}
$launcherInfo = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $launcher.Id)
if ($launcherInfo) { $known[$launcher.Id] = $launcherInfo.CreationDate.ToUniversalTime() }
$timedOut = $false
while (-not $launcher.HasExited) {
    $all = @(Get-CimInstance Win32_Process)
    do {
        $added = $false
        foreach ($child in $all) {
            if ($known.ContainsKey([int]$child.ParentProcessId) -and
                -not $known.ContainsKey([int]$child.ProcessId)) {
                $parent = $all | Where-Object { $_.ProcessId -eq $child.ParentProcessId } |
                    Select-Object -First 1
                if ($parent -and $parent.CreationDate.ToUniversalTime() -eq
                    $known[[int]$parent.ProcessId]) {
                    $known[[int]$child.ProcessId] = $child.CreationDate.ToUniversalTime()
                    $added = $true
                }
            }
        }
    } while ($added)
    if (((Get-Date) - $started).TotalMinutes -ge $MaxMinutes) {
        $timedOut = $true
        Write-Output ('GUARDED_SYNTH: timeout; stopping only this job, launcher={0}' -f $launcher.Id)
        $targets = @($all | Where-Object { $known.ContainsKey([int]$_.ProcessId) -and
            $_.CreationDate.ToUniversalTime() -eq $known[[int]$_.ProcessId] })
        foreach ($target in $targets | Sort-Object @{Expression={
            if ($_.Name -eq 'vivado.exe') { 0 } else { 1 }
        }}) {
            $current = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $target.ProcessId)
            if ($current -and $current.CreationDate.ToUniversalTime() -eq
                $known[[int]$current.ProcessId]) {
                Stop-Process -Id $current.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
        break
    }
    Start-Sleep -Seconds 5
    $launcher.Refresh()
}
$launcher.WaitForExit()
$elapsed = ((Get-Date) - $started).TotalSeconds
Write-Output ('GUARDED_SYNTH: completed exit={0} timed_out={1} elapsed_seconds={2:F1}' -f
    $launcher.ExitCode, $timedOut, $elapsed)
[ordered]@{
    script=$resolvedScript; arguments=$TclArguments; started_local=$started.ToString('o')
    finished_local=(Get-Date).ToString('o'); limit_minutes=$MaxMinutes
    elapsed_seconds=[Math]::Round($elapsed,1); exit_code=$launcher.ExitCode; timed_out=$timedOut
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $resolvedOutput 'job-result.json') -Encoding utf8
if ($timedOut) { exit 124 }
exit $launcher.ExitCode
