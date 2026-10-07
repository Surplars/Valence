[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$AcceptanceDirectory,
    [Parameter(Mandatory)][string]$CandidateRoot,
    [ValidateSet('staged-control-heads','staged-throughput')][string]$Profile = 'staged-control-heads',
    [switch]$ResumeStaging,
    [string]$BaselineDirectory = 'E:\VM\Share\Valence-rtl\ddr-opt-20261002\rom-boundary-board100-u460800'
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$candidate = [IO.Path]::GetFullPath($CandidateRoot)
$base = (Resolve-Path -LiteralPath $BaselineDirectory).ProviderPath
$acceptance = (Resolve-Path -LiteralPath $AcceptanceDirectory).ProviderPath
$artifactRoot = [IO.Path]::GetFullPath('E:\VM\Share\Valence-rtl') + '\'
if (-not $candidate.StartsWith($artifactRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Use a named artifact subdirectory'
}
$staged = Test-Path -LiteralPath $candidate
if ($staged -and (-not $ResumeStaging -or
    (Test-Path -LiteralPath (Join-Path $candidate 'source-inputs.json')) -or
    (Test-Path -LiteralPath (Join-Path $candidate 'rtl')))) {
    throw 'Resume is allowed only for incomplete input staging, before source freeze/RTL export'
}
$short = Get-Content -LiteralPath (Join-Path $acceptance 'results.json') -Raw | ConvertFrom-Json
if ($short.status -ne 'passed' -or $short.profile -ne $Profile -or
    $short.issue_width -ne 2 -or $short.cpu_hz -ne 100000000 -or $short.uart_baud -ne 460800) {
    throw 'Exact candidate short acceptance must pass before freezing'
}
if ($Profile -eq 'staged-throughput' -and
    ($short.performance_verified -ne $true -or $short.pipeline_oracles_verified -ne $true)) {
    throw 'Throughput profile also requires independent pipeline and performance A/B evidence'
}
function Hash-File([string]$path) {
    (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Resolve-ReceiptPath([string]$root, [string]$relative) {
    # Receipts use canonical forward-slash relative paths. Reject drive/UNC,
    # traversal, ADS and wildcard spellings before resolving a source/target.
    if ([string]::IsNullOrWhiteSpace($relative) -or [IO.Path]::IsPathRooted($relative) -or
        $relative -match '[\\:*?"<>|\x00-\x1f]' -or
        @($relative.Split('/') | Where-Object { $_ -in @('', '.', '..') }).Count -gt 0) {
        throw ('Unsafe receipt path: ' + $relative)
    }
    $resolvedRoot = [IO.Path]::GetFullPath($root).TrimEnd('\')
    $path = [IO.Path]::GetFullPath((Join-Path $resolvedRoot $relative))
    if (-not $path.StartsWith($resolvedRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw ('Receipt path leaves its input directory: ' + $relative)
    }
    $path
}
$acceptedResultsHash = Hash-File (Join-Path $acceptance 'results.json')
$receiptFiles = @()
$receiptManifestHash = $null
function Assert-AcceptanceReceipt {
    if ((Hash-File (Join-Path $acceptance 'results.json')) -cne $acceptedResultsHash) {
        throw 'Acceptance results changed during candidate freeze'
    }
    if ($Profile -eq 'staged-throughput') {
        if ((Hash-File (Join-Path $acceptance 'evidence-files.json')) -cne $receiptManifestHash) {
            throw 'Acceptance evidence manifest changed during candidate freeze'
        }
        foreach ($file in $receiptFiles) {
            $path = Resolve-ReceiptPath $acceptance $file.path
            if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
                (Get-Item -LiteralPath $path).Length -ne $file.bytes -or
                (Hash-File $path) -cne $file.sha256) {
                throw ('Acceptance evidence changed or is missing: ' + $file.path)
            }
        }
    }
}
function Assert-HardwareReceipt([string]$root) {
    if ($Profile -ne 'staged-throughput') { return }
    if ($null -eq $short.hardware_source_sha256) { throw 'Missing accepted hardware source manifest' }
    $expectedPaths = @($short.hardware_source_sha256.PSObject.Properties.Name | Sort-Object)
    $actualPaths = @(Get-ChildItem -LiteralPath (Join-Path $root 'src\main\scala') -Recurse -File -Filter '*.scala' |
        ForEach-Object { $_.FullName.Substring($root.TrimEnd('\').Length + 1).Replace('\', '/') } | Sort-Object)
    if ($expectedPaths.Count -eq 0 -or $expectedPaths.Count -ne $actualPaths.Count -or
        (Compare-Object $expectedPaths $actualPaths)) { throw 'Complete hardware source set differs from acceptance' }
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($relative in $expectedPaths) {
        $path = Resolve-ReceiptPath $root $relative
        $expected = $short.hardware_source_sha256.PSObject.Properties[$relative].Value
        if (-not $seen.Add($relative) -or -not $relative.StartsWith('src/main/scala/', [StringComparison]::Ordinal) -or
            -not $relative.EndsWith('.scala', [StringComparison]::Ordinal) -or
            $expected -cnotmatch '^[0-9a-f]{64}$' -or (Hash-File $path) -cne $expected) {
            throw ('Hardware source differs from the accepted tested snapshot: ' + $relative)
        }
    }
}
if ($Profile -eq 'staged-throughput') {
    if ($short.evidence_hash_manifest -cne 'evidence-files.json') { throw 'Missing collector evidence receipt' }
    $receiptPath = Join-Path $acceptance 'evidence-files.json'
    $receiptManifestHash = Hash-File $receiptPath
    $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
    $receiptFiles = @($receipt.files)
    if ($receiptFiles.Count -eq 0) { throw 'Empty collector evidence receipt' }
    $seenReceiptPaths = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($file in $receiptFiles) {
        [void](Resolve-ReceiptPath $acceptance $file.path)
        if (-not $seenReceiptPaths.Add($file.path) -or $file.sha256 -cnotmatch '^[0-9a-f]{64}$' -or
            $null -eq $file.bytes -or $file.bytes -lt 0 -or $file.bytes -ne [long]$file.bytes) {
            throw ('Invalid collector evidence receipt record: ' + $file.path)
        }
    }
}
Assert-AcceptanceReceipt
Assert-HardwareReceipt $repo
[void][IO.Directory]::CreateDirectory($candidate)
foreach ($directory in @('ip-build','vendor-mig','firmware','linux-final')) {
    if ($staged) {
        if (-not (Test-Path -LiteralPath (Join-Path $candidate $directory) -PathType Container)) {
            throw ('Incomplete copied input: ' + $directory)
        }
    } else {
        Copy-Item -LiteralPath (Join-Path $base $directory) -Destination (Join-Path $candidate $directory) -Recurse
    }
}
$expectedRom = 'e801fec10610204be32cc6688d63728cb1307c604636abb1b270bcc825556554'
foreach ($rom in @((Join-Path $candidate 'firmware\bootrom.bin'), (Join-Path $acceptance 'boot-firmware\bootrom.bin'))) {
    if ((Get-FileHash -LiteralPath $rom -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedRom) {
        throw 'ROM differs from the short-tested 100 MHz boot firmware'
    }
}
$prior = Get-Content -LiteralPath (Join-Path $base 'source-inputs.json') -Raw | ConvertFrom-Json
$paths = @($prior.source_files.path)
foreach ($directory in @('src\main','src\test','fpga\zu15eg','simulator\gsim')) {
    $paths += Get-ChildItem -LiteralPath (Join-Path $repo $directory) -File -Recurse |
        Where-Object { $_.Extension -in @('.scala','.sv','.v','.tcl','.ps1','.xdc','.json','.md','.py','.cpp','.h') } |
        ForEach-Object { $_.FullName.Substring($repo.Length + 1).Replace('\','/') }
}
$paths += @('simulator/gsim/rom_boundary.py','simulator/gsim/harness/prediction_training.cpp')
$sourceFiles = foreach ($relative in ($paths | Sort-Object -Unique)) {
    $source = Join-Path $repo $relative
    $target = Join-Path (Join-Path $candidate 'source-snapshot') $relative
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
    Copy-Item -LiteralPath $source -Destination $target
    [ordered]@{path=$relative; sha256=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()}
}
# The frozen copy, rather than only the live pre-copy tree, must match the
# hardware that the short and A/B runners actually measured.
Assert-HardwareReceipt (Join-Path $candidate 'source-snapshot')
Assert-HardwareReceipt $repo
Assert-AcceptanceReceipt
[ordered]@{profile=$Profile;cpu_hz=100000000;uart_baud=460800;issue_width=2
    synthesis_directive='RuntimeOptimized';hierarchy='rebuilt';synthesis_period_ns=10
    dynamic_clock=$false;source_files=@($sourceFiles)} |
    ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $candidate 'source-inputs.json') -Encoding utf8
$snapshot = Join-Path $candidate 'build-snapshot'
[void][IO.Directory]::CreateDirectory($snapshot)
$buildFiles = foreach ($file in (Get-ChildItem -LiteralPath $PSScriptRoot -File |
    Where-Object { $_.Extension -in @('.tcl','.ps1','.sv','.xdc') })) {
    Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $snapshot $file.Name)
    [ordered]@{path=$file.Name;sha256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
}
@{files=@($buildFiles)} | ConvertTo-Json -Depth 5 |
    Set-Content -LiteralPath (Join-Path $candidate 'build-tools.json') -Encoding utf8
$proof = Join-Path $candidate 'short-validation'
[void][IO.Directory]::CreateDirectory($proof)
$evidenceFiles = foreach ($file in (Get-ChildItem -LiteralPath $acceptance -Recurse -File |
    Where-Object { $_.Extension -in @('.log','.json') })) {
    $relative = $file.FullName.Substring($acceptance.Length + 1)
    $target = Join-Path $proof $relative
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
    Copy-Item -LiteralPath $file.FullName -Destination $target
    [ordered]@{path=$relative.Replace('\','/');sha256=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()}
}
Assert-AcceptanceReceipt
foreach ($file in $evidenceFiles) {
    $relative = $file.path
    if ((Hash-File (Resolve-ReceiptPath $acceptance $relative)) -cne $file.sha256) {
        throw ('Frozen evidence copy differs from its verified input: ' + $relative)
    }
}
$short | Add-Member -NotePropertyName evidence_files -NotePropertyValue @($evidenceFiles)
$short | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $candidate 'short-tests.json') -Encoding utf8
Write-Output ('FROZEN_CANDIDATE: ' + $candidate)
Get-FileHash -LiteralPath (Join-Path $candidate 'source-inputs.json') -Algorithm SHA256
