param(
 [Parameter(Mandatory=$true)][string]$MillPath,
 [Parameter(Mandatory=$true)][string]$JavaHome,
 [Parameter(Mandatory=$true)][string]$ToolCacheRoot,
 [string]$OutputTag='targeted-tests'
)
$ErrorActionPreference='Stop'
if($OutputTag -notmatch '^[A-Za-z0-9-]+$'){throw 'Invalid output tag'}
$repoRoot=Split-Path $PSScriptRoot -Parent
$log=Join-Path $PSScriptRoot "$OutputTag.log"
$receipt=Join-Path $PSScriptRoot "$OutputTag-exit.json"
if((Test-Path -LiteralPath $log) -or (Test-Path -LiteralPath $receipt)){throw 'Preserve earlier evidence; choose a fresh tag'}
$env:JAVA_HOME=$JavaHome
$env:PATH=(Join-Path $JavaHome 'bin')+';'+$env:PATH
$env:MILL_VERSION='1.1.7-jvm'
$env:MILL_FINAL_DOWNLOAD_FOLDER=Join-Path $ToolCacheRoot 'mill\download'
$env:COURSIER_CACHE=Join-Path $ToolCacheRoot 'cache\coursier'
$env:COURSIER_REPOSITORIES='https://repo.maven.apache.org/maven2'
$env:PWD=$repoRoot
Push-Location -LiteralPath $repoRoot
try {
 & $MillPath --no-server IonSoC.test.testOnly platform.TransportEmptyAnnouncementSpec platform.CommonPlatformBoundarySpec ip.TileLinkClockDomainBoundarySpec *> $log
 $e=$LASTEXITCODE
 [ordered]@{exit_code=$e;utc=[DateTime]::UtcNow.ToString('o');hardware_simulation=$false;implementation_started=$false} | ConvertTo-Json | Set-Content -LiteralPath $receipt
 Get-Content -LiteralPath $log -Tail 35
} finally {Pop-Location}
exit $e
