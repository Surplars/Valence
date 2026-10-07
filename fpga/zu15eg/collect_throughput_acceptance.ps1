[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ShortDirectory,
    [Parameter(Mandatory)][string]$PerformanceDirectory,
    [Parameter(Mandatory)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$shortRoot = (Resolve-Path -LiteralPath $ShortDirectory).ProviderPath.TrimEnd('\')
$performanceRoot = (Resolve-Path -LiteralPath $PerformanceDirectory).ProviderPath.TrimEnd('\')
$out = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $out) { throw 'Use a fresh throughput acceptance output directory' }
foreach ($inputRoot in @($shortRoot, $performanceRoot)) {
    if (-not (Test-Path -LiteralPath $inputRoot -PathType Container) -or
        $out.StartsWith($inputRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Acceptance output must be separate from the input evidence directories'
    }
}
function Hash-File([string]$path) {
    (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Read-Json([string]$path) {
    Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
}
function Require-Log([string]$root, [string]$relative, [string]$marker, [switch]$Negative) {
    $text = Get-Content -LiteralPath (Join-Path $root $relative) -Raw
    if (-not $text.Contains($marker)) { throw ('Missing raw evidence: ' + $relative + ' / ' + $marker) }
    if ($Negative -and ($text -match 'AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:')) {
        throw ('Negative control crashed instead of demonstrating oracle rejection: ' + $relative)
    }
    $text
}
function Assert-SameSet($actual, $expected, [string]$context) {
    $actual = @($actual)
    $expected = @($expected)
    if ($actual.Count -ne $expected.Count -or
        @($actual | Sort-Object -Unique).Count -ne $actual.Count -or
        (Compare-Object ($actual | Sort-Object) ($expected | Sort-Object))) {
        throw ('Evidence set differs: ' + $context)
    }
}
function Assert-Close($actual, $expected, [string]$context) {
    if ($null -eq $actual -or [double]::IsNaN([double]$actual) -or [double]::IsInfinity([double]$actual) -or
        [Math]::Abs([double]$actual - [double]$expected) -gt [Math]::Max(1e-10, [Math]::Abs($expected) * 1e-7)) {
        throw ('Measured value differs: ' + $context)
    }
}
function Evidence-Path([string]$path) {
    if ($path.StartsWith('/')) {
        if ($repo -notmatch '^(\\\\(?:wsl\.localhost|wsl\$)\\[^\\]+)\\') {
            throw 'Linux evidence paths require invoking this collector from the WSL repository UNC path'
        }
        return Join-Path $Matches[1] $path.TrimStart('/').Replace('/', '\')
    }
    [IO.Path]::GetFullPath($path)
}
$short = Read-Json (Join-Path $shortRoot 'results.json')
$performance = Read-Json (Join-Path $performanceRoot 'results.json')
$checks = @('contracts', 'pipelines', 'vm', 'vm-fetch', 'board')
if ($short.status -ne 'passed' -or $short.profile -ne 'staged-throughput' -or
    $short.issue_width -ne 2 -or $short.cpu_hz -ne 100000000 -or $short.uart_baud -ne 460800) {
    throw 'Exact 100 MHz / 460800 baud / two-issue short batch has not passed'
}
Assert-SameSet $short.checks_requested $checks 'all affected short checks'
if ($performance.status -ne 'passed' -or $performance.issue_width -ne 2 -or
    $performance.rob_entries -ne 16 -or $performance.physical_registers -ne 48 -or
    $performance.memory_entries -ne 2 -or $performance.branch_predictor_entries -ne 32) {
    throw 'A/B performance evidence does not match the two-issue FPGA backend geometry'
}
$profiles = @('staged-control-heads', 'staged-throughput')
Assert-SameSet $performance.profiles.PSObject.Properties.Name $profiles 'baseline/candidate profiles'
if ($null -eq $short.hardware_source_sha256 -or $null -eq $performance.hardware_source_sha256) {
    throw 'Both runners must provide hardware source manifests; legacy evidence cannot be relabeled'
}
$hardwarePaths = @($short.hardware_source_sha256.PSObject.Properties.Name | Sort-Object)
Assert-SameSet $performance.hardware_source_sha256.PSObject.Properties.Name $hardwarePaths 'short/performance hardware manifests'
function Assert-HardwareSnapshot {
    $liveHardwarePaths = @(Get-ChildItem -LiteralPath (Join-Path $repo 'src\main\scala') -Recurse -File -Filter '*.scala' |
        ForEach-Object { $_.FullName.Substring($repo.Length + 1).Replace('\', '/') })
    Assert-SameSet $hardwarePaths $liveHardwarePaths 'complete current hardware source set'
    foreach ($relative in $hardwarePaths) {
        if (-not $relative.StartsWith('src/main/scala/') -or $relative.Split('/') -contains '..') {
            throw ('Invalid hardware manifest path: ' + $relative)
        }
        $expected = $short.hardware_source_sha256.PSObject.Properties[$relative].Value
        $other = $performance.hardware_source_sha256.PSObject.Properties[$relative].Value
        if ($expected -notmatch '^[0-9a-f]{64}$' -or $expected -cne $other -or
            $expected -cne (Hash-File (Join-Path $repo $relative))) {
            throw ('Hardware source changed or A/B and short evidence differ: ' + $relative)
        }
    }
}
Assert-HardwareSnapshot
[void](Require-Log $shortRoot 'contracts.log' 'SUCCESS] mill IonSoC.test.testOnly')
foreach ($spec in @('RomBoundaryTimingSpec', 'RequestCaptureTimingSpec', 'OooParamsSpec',
    'ControlHeadsTimingSpec', 'ReturnTimingSpec', 'ThroughputTimingSpec',
    'FrontendSelectTimingSpec', 'FrontendFeedbackTimingSpec', 'InstructionPermissionTimingSpec',
    'SharedPhysicalSourceDecodeSpec')) {
    [void](Require-Log $shortRoot 'contracts.log' $spec)
}
[void](Require-Log $shortRoot 'execution-slot\test.log' 'ISSUE_EXECUTE_STAGE_PASS cycles=20000')
[void](Require-Log $shortRoot 'execution-slot\negative.log' 'execution stage oracle mismatch' -Negative)
$sideText = Require-Log $shortRoot 'side-issue\test.log' 'SIDE_ISSUE_TIMING_PASS cycles=6000 '
foreach ($field in @('ready_checks', 'wake_reserve_collisions', 'owner_replacements',
    'same_packet_raw', 'alias_init', 'blocked_units', 'dual_classes', 'store_grants', 'age_wrap')) {
    $match = [regex]::Match($sideText, ('(?:^|\s)' + $field + '=(\d+)'))
    if (-not $match.Success -or [long]$match.Groups[1].Value -le 0) { throw ('Missing side-issue witness: ' + $field) }
}
[void](Require-Log $shortRoot 'side-issue\negative.log' 'side issue timing oracle mismatch' -Negative)
if ($short.side_issue_oracles_verified -ne $true -or $short.side_issue_negative_exit_code -ne 1 -or
    (Get-Content -LiteralPath (Join-Path $shortRoot 'side-issue\negative.log') -Raw) -match '\bPASS\b') {
    throw 'Side-issue readiness/age/payload-cover negative control must exit 1 by the independent oracle'
}
if ($short.instruction_permission_oracles_verified -ne $true) { throw 'Retimed I-fetch permission evidence missing' }
$permissionKeys = @('2-1-0', '2-1-1', '4-1-1', '2-0-0')
Assert-SameSet $short.instruction_permission_negative_exit_codes.PSObject.Properties.Name $permissionKeys 'I-fetch permission configurations'
foreach ($key in $permissionKeys) {
    $geometry = $key.Split('-')
    $directory = 'instruction-permission-' + $key
    $text = Require-Log $shortRoot ($directory + '\test.log') ('GSIM instruction permission: PASS words=' +
        $geometry[0] + ' retimed=' + $geometry[1] + ' aligned=' + $geometry[2])
    $fields = @('cases', 'normalLaunch', 'partialLaunch', 'allRejected', 'translationFault',
        'delayed', 'held', 'heldPmpChanges', 'responseHeld', 'preOfferPmpChanges')
    if ($geometry[1] -eq '1') { $fields += 'faultExtraCycles' }
    if ($geometry[0] -eq '2' -and $geometry[2] -eq '0') { $fields += @('crossPage', 'secondOnly') }
    foreach ($field in $fields) {
        $match = [regex]::Match($text, ('(?:^|\s)' + $field + '=(\d+)'))
        if (-not $match.Success -or [long]$match.Groups[1].Value -le 0) { throw ('Missing I-fetch permission witness: ' + $key + '/' + $field) }
    }
    $negative = Require-Log $shortRoot ($directory + '\negative.log') 'independent I-fetch permission oracle mismatch' -Negative
    if ($short.instruction_permission_negative_exit_codes.PSObject.Properties[$key].Value -ne 1 -or $negative -match '\bPASS\b') {
        throw ('I-fetch permission negative must exit 1 by its independent oracle: ' + $key)
    }
}
foreach ($width in @(2, 4)) {
    foreach ($compressed in @(0, 1)) {
        $directory = if ($width -eq 2) { 'fetch-packet-' + $compressed } else { 'fetch-packet-4-' + $compressed }
        $marker = 'GSIM registered fetch packet: PASS width=' + $width + ' compressed=' + $compressed
        [void](Require-Log $shortRoot ($directory + '\test.log') $marker)
        $cases = if ($compressed) { 126 } else { 63 }
        [void](Require-Log $shortRoot ($directory + '\test.log') ('hintQualificationCases=' + $cases))
        [void](Require-Log $shortRoot ($directory + '\negative.log') 'fetch packet oracle mismatch' -Negative)
    }
    [void](Require-Log $shortRoot ('fetch-offsets-' + $width + '\test.log') ('GSIM fetch offsets: PASS width=' + $width))
    [void](Require-Log $shortRoot ('fetch-offsets-' + $width + '\test.log') 'GSIM fetch metadata kill isolation: PASS access/page disable/invalidate')
    [void](Require-Log $shortRoot ('fetch-offsets-' + $width + '\negative.log') 'mixed-length instruction mismatch' -Negative)
}
foreach ($field in @('frontend_feedback_oracles_verified', 'head_trap_ledger_oracle_verified', 'head_trap_machine_oracle_verified')) {
    if ($short.PSObject.Properties[$field].Value -ne $true) { throw ('Required feedback short oracle missing: ' + $field) }
}
[void](Require-Log $shortRoot 'frontend-select\test.log' 'GSIM frontend selection: PASS ')
[void](Require-Log $shortRoot 'frontend-select\test.log' 'adjacent_lookup=121296')
[void](Require-Log $shortRoot 'frontend-select\shifted-negative.log' 'adjacent fetch tag full64 selected-set oracle mismatch' -Negative)
$ledgerText = Require-Log $shortRoot 'head-trap-ledger\test.log' 'GSIM trusted head-trap ledger: PASS '
foreach ($field in @('headTraps', 'activeRollbackShrinks', 'emptyRequests', 'duplicateZeroBoundary', 'dualCommits', 'rejectedCompletions')) {
    $match = [regex]::Match($ledgerText, ('(?:^|\s)' + $field + '=(\d+)'))
    if (-not $match.Success -or [long]$match.Groups[1].Value -le 0) { throw ('Missing head-trap ledger witness: ' + $field) }
}
[void](Require-Log $shortRoot 'head-trap-ledger\negative.log' 'head trap acceptance oracle mismatch' -Negative)
$machineText = Require-Log $shortRoot 'head-trap-machine\test.log' 'GSIM head trap short: PASS programs=8 interrupts=8 traps=10 empty=2 memoryIrq=2 storeIrq=2 priority=2 mret=10'
[void](Require-Log $shortRoot 'head-trap-machine\test.log' 'irqBoundary=DIRECT-IRQ oracle=SystemModel registeredFetchPacket=1')
foreach ($field in @('csr', 'held', 'fastHeadTraps', 'emptyTrapEvents')) {
    $match = [regex]::Match($machineText, ('(?m)^GSIM head trap short: PASS .*\s' + $field + '=(\d+)'))
    if (-not $match.Success -or [long]$match.Groups[1].Value -le 0) { throw ('Missing head-trap machine witness: ' + $field) }
}
$caseKeys = @([regex]::Matches($machineText, '(?m)^HEAD_TRAP_CASE irq=(external|timer) scenario=([4-7]) seed=0 ') |
    ForEach-Object { $_.Groups[1].Value + '|' + $_.Groups[2].Value })
Assert-SameSet $caseKeys @('external|4', 'external|5', 'external|6', 'external|7', 'timer|4', 'timer|5', 'timer|6', 'timer|7') 'eight original machine IRQ scenarios'
[void](Require-Log $shortRoot 'head-trap-machine\negative.log' 'GSIM head trap short negative: oracle rejected injected interrupt cause' -Negative)
[void](Require-Log $shortRoot 'head-trap-machine\negative.log' 'GSIM MachineCore: FAIL trap metadata' -Negative)
if ($short.head_trap_machine_negative_exit_code -ne 1 -or
    (Get-Content -LiteralPath (Join-Path $shortRoot 'head-trap-machine\negative.log') -Raw) -match '\bPASS\b') {
    throw 'Machine IRQ negative control must exit 1 by the independent trap-metadata oracle'
}
# Parse raw oracle logs independently; JSON booleans alone are not evidence.
function Assert-OracleCounters([string]$text, [string]$prefix, [string[]]$fields,
    [object]$receipt, [string]$context, [string[]]$allowZero = @()) {
    if ($text -match '\bFAIL\b|AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:') {
        throw ('Positive oracle log contains failure/sanitizer output: ' + $context)
    }
    $summaries = [regex]::Matches($text, ('(?m)^' + [regex]::Escape($prefix) + '.*$'))
    if ($summaries.Count -ne 1 -or $null -eq $receipt) { throw ('Missing/duplicate oracle summary: ' + $context) }
    Assert-SameSet $receipt.PSObject.Properties.Name $fields ($context + ' counter fields')
    $actual = [ordered]@{}
    foreach ($field in $fields) {
        $values = [regex]::Matches($summaries[0].Value, ('(?:^|\s)' + [regex]::Escape($field) + '=(\d+)(?=\s|$)'))
        if ($values.Count -ne 1) { throw ('Missing/duplicate counter: ' + $context + '/' + $field) }
        $value = [long]$values[0].Groups[1].Value
        if (($value -eq 0 -and $field -notin $allowZero) -or
            $receipt.PSObject.Properties[$field].Value -ne $value) { throw ('Counter witness differs: ' + $context + '/' + $field) }
        $actual[$field] = $value
    }
    return [pscustomobject]$actual
}
function Assert-OracleNegative([string]$relative, [string]$marker, [object]$code) {
    $negative = Require-Log $shortRoot $relative $marker -Negative
    if ($code -ne 1 -or $negative -match '\bPASS\b|AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:') {
        throw ('Negative control did not exit1 on its oracle: ' + $relative)
    }
}
foreach ($field in @('side_store_oracle_verified', 'raw_fault_oracles_verified', 'shared_physical_oracles_verified', 'head_system_ledger_oracle_verified',
    'authorization_machine_oracle_verified', 'authorization_machine_cycles_equal')) {
    if ($short.PSObject.Properties[$field].Value -ne $true) { throw ('Required authorization oracle missing: ' + $field) }
}
$sideCounts = Assert-OracleCounters $sideText 'SIDE_ISSUE_TIMING_PASS ' @('cycles', 'ready_checks',
    'wake_reserve_collisions', 'owner_replacements', 'same_packet_raw', 'alias_init', 'blocked_units',
    'dual_classes', 'store_grants', 'age_wrap', 'resets', 'store_candidates', 'store_invariant_pairs',
    'alu_promise_changes', 'late_store_grant_changes', 'head_excluded', 'partial_address', 'known_data_wait',
    'unused_sources', 'prepared_excluded', 'class_excluded', 'control_held', 'candidate_age_wrap') $short.side_store_counts 'side-issue'
$sideExact = @{cycles=6000; resets=2; same_packet_raw=750; alias_init=750; store_candidates=6000;
    store_invariant_pairs=4500; alu_promise_changes=4500}
$sideMinimum = @{ready_checks=30001; wake_reserve_collisions=501; owner_replacements=1001;
    blocked_units=2001; dual_classes=4001; store_grants=3001; age_wrap=51; late_store_grant_changes=2250;
    head_excluded=750; partial_address=1500; known_data_wait=1500; unused_sources=1500;
    prepared_excluded=750; class_excluded=1500; control_held=750; candidate_age_wrap=51}
foreach ($field in $sideExact.Keys) {
    if ($sideCounts.PSObject.Properties[$field].Value -ne $sideExact[$field]) { throw ('Store exact coverage differs: ' + $field) }
}
foreach ($field in $sideMinimum.Keys) {
    if ($sideCounts.PSObject.Properties[$field].Value -lt $sideMinimum[$field]) { throw ('Store coverage threshold missing: ' + $field) }
}
Assert-OracleNegative 'side-issue\store-negative.log' 'side issue timing oracle mismatch: store candidate semantics' $short.side_store_negative_exit_code
Assert-SameSet $short.raw_fault_counts.PSObject.Properties.Name @('40', '48') 'raw-fault pressure geometries'
Assert-SameSet $short.raw_fault_negative_exit_codes.PSObject.Properties.Name @('40', '48') 'raw-fault negative geometries'
Assert-SameSet $short.raw_fault_fixtures.PSObject.Properties.Name @('40', '48') 'raw-fault fixture geometries'
foreach ($key in @('40', '48')) {
    $directory = 'raw-fault-' + $key
    $text = Require-Log $shortRoot ($directory + '\test.log') ('GSIM raw-fault rename: PASS physical=' + $key)
    $counts = Assert-OracleCounters $text 'GSIM raw-fault rename: PASS ' @('physical', 'cases', 'cycles',
        'mask0', 'mask1', 'mask2', 'mask3', 'pressure0', 'pressure1', 'pressure2', 'patterns', 'wakeModes',
        'accepted', 'aliases', 'blocked', 'noFreeFaultAccepted', 'noFreeFullBlocked', 'wakeReserveCollision',
        'readyChecks', 'rawForward', 'faultSuppressedRaw', 'aliasWithoutFree') $short.raw_fault_counts.PSObject.Properties[$key].Value $directory @('noFreeFaultAccepted', 'noFreeFullBlocked', 'aliasWithoutFree')
    $cycles = if ($key -eq '40') { 2880 } else { 5184 }
    $exact = @{physical=[int]$key; cases=288; cycles=$cycles; mask0=72; mask1=72; mask2=72; mask3=72;
        pressure0=96; pressure1=96; pressure2=96; patterns=12; wakeModes=2; readyChecks=$cycles * 32}
    foreach ($field in $exact.Keys) {
        if ($counts.PSObject.Properties[$field].Value -ne $exact[$field]) { throw ('Raw-fault coverage differs: ' + $key + '/' + $field) }
    }
    if (($key -eq '40' -and ($counts.noFreeFaultAccepted -le 0 -or $counts.aliasWithoutFree -le 0 -or $counts.noFreeFullBlocked -ne 0)) -or
        ($key -eq '48' -and ($counts.noFreeFaultAccepted -ne 0 -or $counts.aliasWithoutFree -ne 0 -or $counts.noFreeFullBlocked -le 0))) {
        throw ('Raw-fault free/ROB boundary witnesses differ: ' + $key)
    }
    $fixture = $short.raw_fault_fixtures.PSObject.Properties[$key].Value
    Assert-SameSet $fixture.PSObject.Properties.Name @('parameters', 'defines', 'runtime_args', 'positive_exit_code', 'negative_flags') ($directory + ' fixture receipt')
    if (@($fixture.parameters).Count -ne 1 -or $fixture.parameters[0] -cne $key -or
        @($fixture.runtime_args).Count -ne 0 -or $fixture.positive_exit_code -ne 0) { throw ('Wrong raw-fault fixture options: ' + $key) }
    Assert-SameSet $fixture.defines.PSObject.Properties.Name @('PHYSICAL_REGS') ($directory + ' compiler options')
    Assert-SameSet $fixture.negative_flags.PSObject.Properties.Name @('--inject-mismatch') ($directory + ' negative options')
    if ($fixture.defines.PHYSICAL_REGS -ne [int]$key -or $fixture.negative_flags.PSObject.Properties['--inject-mismatch'].Value -ne 1) {
        throw ('Raw-fault fixture or negative options differ: ' + $key)
    }
    Assert-OracleNegative ($directory + '\negative.log') 'independent raw-fault rename oracle mismatch' $short.raw_fault_negative_exit_codes.PSObject.Properties[$key].Value
}
$physicalKeys = @('16-48-1', '16-48-0', '32-64-1')
Assert-SameSet $short.shared_physical_negative_exit_codes.PSObject.Properties.Name $physicalKeys 'three independent physical-read configurations'
Assert-SameSet $short.shared_physical_counts.PSObject.Properties.Name $physicalKeys 'physical-read counter receipt configurations'
foreach ($key in $physicalKeys) {
    $geometry = $key.Split('-'); $directory = 'physical-shared-' + $key
    $text = Require-Log $shortRoot ($directory + '\test.log') ('GSIM physical operand payload: PASS rob=' + $geometry[0] + ' physical=' + $geometry[1])
    $counts = Assert-OracleCounters $text 'GSIM physical operand payload: PASS ' @('vectors', 'empty', 'dual',
        'invalidUnselected', 'sharedClients', 'independentOwnerVectors') $short.shared_physical_counts.PSObject.Properties[$key].Value $directory
    if ($counts.sharedClients -ne 3 -or $counts.independentOwnerVectors -ne [long]$geometry[0] * 64) {
        throw ('Six independent-owner combinations incomplete: ' + $key)
    }
    $expectedVectors = if ($geometry[0] -eq '16') { 57921 } else { 153185 }
    if ($counts.vectors -ne $expectedVectors -or $counts.invalidUnselected -ne 2 * [long]$geometry[0] -or
        $counts.empty + $counts.dual -ne $counts.vectors) { throw ('Physical-read coverage totals differ: ' + $key) }
    $codes = $short.shared_physical_negative_exit_codes.PSObject.Properties[$key].Value
    Assert-SameSet $codes.PSObject.Properties.Name @('normal', 'shared') ('physical negative controls ' + $key)
    Assert-OracleNegative ($directory + '\negative.log') 'physical operand oracle mismatch' $codes.normal
    Assert-OracleNegative ($directory + '\shared-negative.log') 'shared physical operand oracle mismatch' $codes.shared
}
Assert-SameSet $short.head_system_ledger_counts.PSObject.Properties.Name @('candidate', 'alias') 'authorization ledger geometries'
Assert-SameSet $short.head_system_ledger_negative_exit_codes.PSObject.Properties.Name @('candidate', 'alias') 'ledger negative geometries'
foreach ($kind in @('candidate', 'alias')) {
    $directory = if ($kind -eq 'candidate') { 'head-trap-ledger' } else { 'authorization-ledger-alias' }
    $log = if ($kind -eq 'candidate') { 'authorization.log' } else { 'test.log' }
    $text = Require-Log $shortRoot ($directory + '\' + $log) 'GSIM authorization ledger: PASS '
    $counts = Assert-OracleCounters $text 'GSIM authorization ledger: PASS ' @('headSystems', 'activeShrinks',
        'duplicateRetainOne', 'externalHeadTies', 'trapPriority', 'ownerChecks', 'rawWaw', 'x0', 'validHoles',
        'capacity', 'aliases') $short.head_system_ledger_counts.PSObject.Properties[$kind].Value $directory @('aliases')
    if ($counts.externalHeadTies -ne 2 -or $counts.trapPriority -ne 1 -or $counts.validHoles -ne 2 -or
        $counts.capacity -ne 2 -or ($kind -eq 'alias' -and $counts.aliases -ne 3) -or
        ($kind -eq 'candidate' -and $counts.aliases -ne 0)) { throw ('Ledger directed witnesses incomplete: ' + $kind) }
    $codes = $short.head_system_ledger_negative_exit_codes.PSObject.Properties[$kind].Value
    Assert-SameSet $codes.PSObject.Properties.Name @('system', 'source') ('ledger negative controls ' + $kind)
    Assert-OracleNegative ($directory + '\system-negative.log') 'head system acceptance oracle mismatch' $codes.system
    Assert-OracleNegative ($directory + '\sources-negative.log') 'same-packet source mapping' $codes.source
}
$authorizationKeys = @(foreach ($memory in @(0, 1)) { foreach ($delay in 1..12) { [string]$memory + '|' + $delay } })
Assert-SameSet $short.authorization_machine_cases.PSObject.Properties.Name @('candidate', 'generic') 'machine authorization A/B profiles'
Assert-SameSet $short.authorization_machine_counts.PSObject.Properties.Name @('candidate', 'generic') 'machine authorization summary profiles'
$authorizationCycles = @{}
foreach ($kind in @('candidate', 'generic')) {
    $directory = if ($kind -eq 'candidate') { 'head-trap-machine' } else { 'authorization-machine-generic' }
    $log = if ($kind -eq 'candidate') { 'authorization.log' } else { 'test.log' }
    $text = Require-Log $shortRoot ($directory + '\' + $log) 'GSIM authorization machine: PASS programs=24 '
    $counts = Assert-OracleCounters $text 'GSIM authorization machine: PASS ' @('programs', 'offers', 'blocked',
        'lsuCollision', 'mulCollision', 'repeatRollback', 'commitHolds', 'protectedReleases', 'acks', 'cycles') $short.authorization_machine_counts.PSObject.Properties[$kind].Value $directory
    if ($counts.programs -ne 24) { throw 'Authorization machine requires24 independent legal flush cases' }
    $headFlag = if ($kind -eq 'candidate') { 'true' } else { 'false' }
    [void](Require-Log $shortRoot ($directory + '\elaborate.log') ('AUTHORIZATION_MACHINE_FIXTURE headSystem=' +
        $headFlag + ' tentativeSources=true sharedDecode=true irqBoundary=DIRECT-IRQ oracle=SystemModel fixture=legal-fence-flush-backpressure'))
    $cases = $short.authorization_machine_cases.PSObject.Properties[$kind].Value
    Assert-SameSet $cases.PSObject.Properties.Name $authorizationKeys ($kind + ' exact24 case receipts')
    $lines = [regex]::Matches($text, '(?m)^AUTHORIZATION_CASE memory=([01]) delay=(\d+) cycles=(\d+) blocked=(\d+) lsu=(\d+) mul=(\d+) rollback=(\d+)\r?$')
    $keys = @($lines | ForEach-Object { $_.Groups[1].Value + '|' + $_.Groups[2].Value })
    Assert-SameSet $keys $authorizationKeys ($kind + ' raw24 legal phase cases')
    $totals = @{cycles=0L; blocked=0L; lsu=0L; mul=0L; rollback=0L}
    foreach ($line in $lines) {
        $key = $line.Groups[1].Value + '|' + $line.Groups[2].Value
        $receipt = $cases.PSObject.Properties[$key].Value
        Assert-SameSet $receipt.PSObject.Properties.Name @('cycles', 'blocked', 'lsu', 'mul', 'rollback') ('machine case fields ' + $kind + '/' + $key)
        $fields = @('cycles', 'blocked', 'lsu', 'mul', 'rollback')
        for ($i = 0; $i -lt $fields.Count; $i++) {
            $value = [long]$line.Groups[$i + 3].Value
            if (($i -eq 0 -and $value -le 0) -or $receipt.PSObject.Properties[$fields[$i]].Value -ne $value) {
                throw ('Raw authorization case differs: ' + $kind + '/' + $key + '/' + $fields[$i])
            }
            $totals[$fields[$i]] += $value
        }
        $authorizationCycles[$kind + '/' + $key] = [long]$line.Groups[3].Value
    }
    if ($totals.cycles -ne $counts.cycles -or $totals.blocked -ne $counts.blocked -or
        $totals.lsu -ne $counts.lsuCollision -or $totals.mul -ne $counts.mulCollision -or
        $totals.rollback -ne $counts.repeatRollback) { throw ('Machine authorization totals differ: ' + $kind) }
}
foreach ($key in $authorizationKeys) {
    if ($authorizationCycles['candidate/' + $key] -ne $authorizationCycles['generic/' + $key]) {
        throw ('Authorization cut changed same-stimulus cycle count: ' + $key)
    }
}
Assert-OracleNegative 'head-trap-machine\authorization-negative.log' 'GSIM MachineCore: FAIL system redirect architectural oracle mismatch' $short.authorization_machine_negative_exit_code
[void](Require-Log $shortRoot 'vm\test.log' 'GSIM CPU virtual data: PASS')
[void](Require-Log $shortRoot 'vm\elaborate.log' 'VM_DATA_THROUGHPUT: rob=16 prf=48 mem=2 issueExecute=1 fetchPacket=1 headTrap=1 headSystem=1 tentativeSources=1 sharedDecode=1 ownerReady=1 storePreparation=1 mulDivDispatch=1')
[void](Require-Log $shortRoot 'vm-fetch\test.log' 'GSIM CPU virtual fetch baseline: PASS')
[void](Require-Log $shortRoot 'vm-fetch\test.log' 'GSIM CPU virtual fetch cross-page: PASS')
$coremarkText = Require-Log $shortRoot 'board-model\board_coremark.log' 'GSIM compact board CoreMark: PASS ticks='
$ddrText = Require-Log $shortRoot 'board-model\ddr_bench_app.log' 'GSIM DDR benchmark application: PASS'
$coremarkMatch = [regex]::Match($coremarkText, 'GSIM compact board CoreMark: PASS ticks=(\d+)')
if (-not $coremarkMatch.Success -or [long]$coremarkMatch.Groups[1].Value -ne $short.coremark_single_iteration_ticks -or
    $short.coremark_sha256 -cne (Hash-File (Join-Path $shortRoot 'firmware\coremark_board.bin')) -or
    $short.coremark_sha256 -cne 'ae05e5be6d30bb8ec111e4734d41407ac31e9de200dd25ac7fef3ee92739e821' -or
    $short.generated_board_models -ne 1) {
    throw 'Same-binary one-model board CoreMark cycle evidence differs'
}
$ddrTicks = @([regex]::Matches($ddrText,
    '(?m)^(?:READ\(cold-start\)|WRITE\(\+flush\)|COPY\(payload,\+flush\)|CHASE working_set).*?ticks=(\d+)') |
    ForEach-Object { [long]$_.Groups[1].Value })
if ($ddrTicks.Count -ne 4 -or @($short.ddr_4k_read_write_copy_chase_ticks).Count -ne 4) {
    throw 'Four DDR cycle measurements are required'
}
for ($index = 0; $index -lt 4; $index++) {
    if ($ddrTicks[$index] -le 0 -or $ddrTicks[$index] -ne $short.ddr_4k_read_write_copy_chase_ticks[$index]) {
        throw 'Raw DDR cycle measurements differ from the report'
    }
}
$bootHash = Hash-File (Join-Path $shortRoot 'boot-firmware\bootrom.bin')
if ($bootHash -cne 'e801fec10610204be32cc6688d63728cb1307c604636abb1b270bcc825556554') {
    throw 'Boot firmware differs from the short-tested 100 MHz frozen ROM'
}
$expectedKeys = @('throughput_independent_alu|1', 'throughput_dependent_alu|1',
    'throughput_dual_dependency|1', 'throughput_not_taken_mixed|1', 'throughput_direct_jumps|1',
    'throughput_taken_loop|1', 'throughput_load_use|1', 'throughput_load_use|12',
    'throughput_memory_alu_mix|1', 'throughput_memory_alu_mix|12',
    'throughput_compiled_sum|1', 'throughput_compiled_sum|12')
$measured = @{}
$inputHashes = [Collections.Generic.List[object]]::new()
function Record-Input([string]$kind, [string]$path, [string]$expected, [switch]$HashOnly) {
    if (-not $HashOnly -and $expected -notmatch '^[0-9a-f]{64}$') { throw ('Missing input SHA256: ' + $kind) }
    $hash = Hash-File $path
    if ($expected -and $expected -cne $hash) { throw ('Input hash differs: ' + $path) }
    $inputHashes.Add([ordered]@{kind=$kind; source_path=$path; bytes=(Get-Item -LiteralPath $path).Length; sha256=$hash})
}
$feedbackManifest = 'simulator/gsim/config/throughput_feedback_inputs.json'
$feedbackPaths = @($feedbackManifest) + @(Get-Content -LiteralPath (Join-Path $repo $feedbackManifest) -Raw | ConvertFrom-Json)
function Assert-FeedbackSnapshot {
    if ($null -eq $short.feedback_inputs_sha256) { throw 'Fresh affected wrapper/harness/contract/runner hashes are required' }
    Assert-SameSet $short.feedback_inputs_sha256.PSObject.Properties.Name $feedbackPaths 'exact affected test-input paths'
    foreach ($relative in $feedbackPaths) {
        if ($relative -cnotmatch '^(src/test/scala/ooo|simulator/gsim)/[A-Za-z0-9_./-]+$' -or
            @($relative.Split('/') | Where-Object { $_ -in @('', '.', '..') }).Count -gt 0) { throw 'Invalid feedback input path' }
        $expected = $short.feedback_inputs_sha256.PSObject.Properties[$relative].Value
        if ($expected -cnotmatch '^[0-9a-f]{64}$' -or $expected -cne (Hash-File (Join-Path $repo $relative))) {
            throw ('Affected test input changed after short acceptance: ' + $relative)
        }
    }
}
Assert-FeedbackSnapshot
foreach ($relative in $feedbackPaths) {
    Record-Input 'feedback-short-input' (Join-Path $repo $relative) $short.feedback_inputs_sha256.PSObject.Properties[$relative].Value
}
Record-Input 'NEMU' (Join-Path $repo 'build\gsim\nemu-src\build\riscv64-nemu-interpreter-so') $performance.reference_sha256
Record-Input 'independent-harness' (Join-Path $repo 'simulator\gsim\harness\core.cpp') $performance.harness_sha256
if (@($performance.payload_sha256.PSObject.Properties).Count -ne 3) { throw 'Three independent NEMU program payload hashes are required' }
foreach ($payload in $performance.payload_sha256.PSObject.Properties) {
    Record-Input 'NEMU-program' (Evidence-Path $payload.Name) $payload.Value
}
foreach ($profile in $profiles) {
    $metadata = $performance.profiles.PSObject.Properties[$profile].Value
    if ($metadata.status -ne 'passed') { throw ('Profile failed: ' + $profile) }
    $root = Join-Path $performanceRoot $profile
    $text = Require-Log $root 'throughput.log' 'GSIM short two-issue throughput + NEMU: PASS programs=12 '
    $timing = Require-Log $root 'timing-smoke.log' 'GSIM control/memory timing + NEMU: PASS rob=16 physical=48 slots=2 predictor=32 trainingDelay=1 programs=50 '
    [void](Require-Log $root 'negative.log' 'NEMU register mismatch' -Negative)
    $rows = @($text -split '\r?\n' | Where-Object { $_.StartsWith('IPC ') } |
        ForEach-Object { $_.Substring(4) | ConvertFrom-Json })
    Assert-SameSet @($rows | ForEach-Object { $_.name + '|' + $_.memory_latency }) $expectedKeys ($profile + ' raw workloads')
    Assert-SameSet @($metadata.measurements | ForEach-Object { $_.name + '|' + $_.memory_latency }) $expectedKeys ($profile + ' reported workloads')
    $measured[$profile] = @{}
    foreach ($row in $rows) {
        $key = $row.name + '|' + $row.memory_latency
        $reported = @($metadata.measurements | Where-Object { ($_.name + '|' + $_.memory_latency) -ceq $key })[0]
        if ($row.rob -ne 16 -or $row.physical -ne 48 -or $row.memory_entries -ne 2 -or
            $row.cycles -le 0 -or $row.retired -le 0 -or $row.cycles -ne [long]$row.cycles -or
            $row.retired -ne [long]$row.retired) { throw ('Invalid raw measurement geometry/count: ' + $key) }
        foreach ($property in $row.PSObject.Properties) {
            if ($null -eq $reported.PSObject.Properties[$property.Name] -or
                $reported.PSObject.Properties[$property.Name].Value -cne $property.Value) {
                throw ('Raw IPC row differs from JSON: ' + $profile + '/' + $key + '/' + $property.Name)
            }
        }
        foreach ($stage in @('commit', 'issue', 'rename')) {
            $counts = @('zero', 'single', 'dual') | ForEach-Object { $row.PSObject.Properties[$_ + '_' + $stage + '_cycles'].Value }
            if (@($counts | Where-Object { $null -eq $_ -or $_ -lt 0 -or $_ -ne [long]$_ }).Count -gt 0 -or
                ($counts | Measure-Object -Sum).Sum -ne $row.cycles) {
                throw ('Invalid cycle histogram: ' + $profile + '/' + $key + '/' + $stage)
            }
        }
        if ($row.single_commit_cycles + 2 * $row.dual_commit_cycles -ne $row.retired -or
            $row.single_issue_cycles + 2 * $row.dual_issue_cycles -ne $row.issued) { throw ('Instruction accounting mismatch: ' + $key) }
        Assert-Close $row.ipc ($row.retired / [double]$row.cycles) ($key + ' IPC')
        Assert-Close $reported.dual_issue_fraction ($row.dual_issue_cycles / [double]$row.cycles) ($key + ' dual issue')
        Assert-Close $reported.dual_commit_fraction ($row.dual_commit_cycles / [double]$row.cycles) ($key + ' dual commit')
        Assert-Close $reported.average_rob_occupancy ($row.rob_occupancy_sum / [double]$row.cycles) ($key + ' ROB occupancy')
        $measured[$profile][$key] = $reported
    }
    $model = Evidence-Path $metadata.model_directory
    Record-Input ($profile + '/model-fir') (Join-Path $model 'IntegerCoreGsim.fir') $metadata.model_fir_sha256
    Record-Input ($profile + '/model-header') (Join-Path $model 'IntegerCoreGsim.h') '' -HashOnly
    $sources = @(Get-ChildItem -LiteralPath $model -File -Filter 'IntegerCoreGsim*.cpp' | Where-Object Name -Match '^IntegerCoreGsim\d+\.cpp$')
    if ($sources.Count -eq 0) { throw ('Model sources missing: ' + $profile) }
    Assert-SameSet $metadata.model_sources_sha256.PSObject.Properties.Name $sources.Name ($profile + ' model sources')
    foreach ($source in $sources) {
        Record-Input ($profile + '/model-source') $source.FullName $metadata.model_sources_sha256.PSObject.Properties[$source.Name].Value
    }
    Record-Input ($profile + '/tested-executable') (Join-Path $root 'run') $metadata.executable_sha256
}
$recoveryText = Require-Log (Join-Path $performanceRoot 'staged-throughput') 'pipeline-recovery.log' 'GSIM pipeline recovery + NEMU: PASS '
$recoveryMatch = [regex]::Match($recoveryText,
    'GSIM pipeline recovery \+ NEMU: PASS .*slot0HeldLane1Progress=(\d+) olderLane0BranchResolution=(\d+) aluForwardingHits=(\d+)')
$witnessNames = @('slot0_held_lane1_progress', 'older_lane0_branch_resolution', 'alu_forwarding_hits')
if (-not $recoveryMatch.Success -or $null -eq $performance.pipeline_recovery_witnesses) {
    throw 'Actual pipeline writeback/branch/forwarding recovery evidence is required'
}
Assert-SameSet $performance.pipeline_recovery_witnesses.PSObject.Properties.Name $witnessNames 'pipeline recovery witnesses'
for ($index = 0; $index -lt $witnessNames.Count; $index++) {
    $actual = [long]$recoveryMatch.Groups[$index + 1].Value
    if ($actual -le 0 -or $performance.pipeline_recovery_witnesses.PSObject.Properties[$witnessNames[$index]].Value -ne $actual) {
        throw ('Missing or mismatched actual pipeline witness: ' + $witnessNames[$index])
    }
}
Assert-SameSet @($performance.comparisons | ForEach-Object { $_.name + '|' + $_.memory_latency }) $expectedKeys 'A/B comparisons'
$logSpeedupSum = 0.0
$regressions = @()
foreach ($comparison in $performance.comparisons) {
    $key = $comparison.name + '|' + $comparison.memory_latency
    $old = $measured[$profiles[0]][$key]
    $new = $measured[$profiles[1]][$key]
    if ($old.retired -ne $new.retired -or $comparison.baseline_cycles -ne $old.cycles -or
        $comparison.candidate_cycles -ne $new.cycles) { throw ('A/B instruction/cycle streams differ: ' + $key) }
    $speedup = $old.cycles / [double]$new.cycles
    Assert-Close $comparison.same_clock_speedup $speedup ($key + ' speedup')
    Assert-Close $comparison.candidate_clock_ratio_to_break_even (1 / $speedup) ($key + ' break-even clock')
    foreach ($side in @('baseline', 'candidate')) {
        $row = if ($side -eq 'baseline') { $old } else { $new }
        foreach ($field in @('ipc', 'dual_issue_fraction', 'dual_commit_fraction')) {
            Assert-Close $comparison.PSObject.Properties[$side + '_' + $field].Value $row.PSObject.Properties[$field].Value ($key + '/' + $side + '/' + $field)
        }
    }
    $logSpeedupSum += [Math]::Log($speedup)
    if ($new.cycles -gt $old.cycles) { $regressions += $comparison }
}
Assert-Close $performance.same_clock_geomean_speedup ([Math]::Exp($logSpeedupSum / $expectedKeys.Count)) 'geometric mean'

# All checks above are read-only. Existing outputs are never overwritten; no
# generated C++ objects or executables are copied into the acceptance archive.
[void][IO.Directory]::CreateDirectory($out)
foreach ($source in @(@{root=$shortRoot; label='short'}, @{root=$performanceRoot; label='performance'})) {
    foreach ($file in (Get-ChildItem -LiteralPath $source.root -Recurse -File |
        Where-Object Extension -In @('.log', '.json', '.fir'))) {
        $relative = $file.FullName.Substring($source.root.Length + 1)
        $target = Join-Path (Join-Path $out $source.label) $relative
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
        Copy-Item -LiteralPath $file.FullName -Destination $target
        if ((Hash-File $target) -cne (Hash-File $file.FullName)) { throw ('Evidence copy differs: ' + $relative) }
    }
}
foreach ($profile in $profiles) {
    $metadata = $performance.profiles.PSObject.Properties[$profile].Value
    $model = Evidence-Path $metadata.model_directory
    $targetRoot = Join-Path $out ('performance\' + $profile + '\model-input')
    [void][IO.Directory]::CreateDirectory($targetRoot)
    Copy-Item -LiteralPath (Join-Path $model 'IntegerCoreGsim.fir') -Destination (Join-Path $targetRoot 'IntegerCoreGsim.fir')
    if ((Hash-File (Join-Path $targetRoot 'IntegerCoreGsim.fir')) -cne $metadata.model_fir_sha256) {
        throw ('Copied model FIR differs: ' + $profile)
    }
}
Copy-Item -LiteralPath (Join-Path $shortRoot 'boot-firmware') -Destination (Join-Path $out 'boot-firmware') -Recurse
if ((Hash-File (Join-Path $out 'boot-firmware\bootrom.bin')) -cne $bootHash) { throw 'Copied boot ROM differs' }
@{files=$inputHashes.ToArray()} | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath (Join-Path $out 'input-provenance.json') -Encoding utf8
Assert-HardwareSnapshot
Assert-FeedbackSnapshot
$evidenceFiles = @(Get-ChildItem -LiteralPath $out -Recurse -File | Sort-Object FullName | ForEach-Object {
    [ordered]@{path=$_.FullName.Substring($out.Length + 1).Replace('\', '/'); bytes=$_.Length; sha256=(Hash-File $_.FullName)}
})
@{files=$evidenceFiles} | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath (Join-Path $out 'evidence-files.json') -Encoding utf8
$combined = [ordered]@{
    status='passed'; profile='staged-throughput'; issue_width=2; cpu_hz=100000000; uart_baud=460800
    rob_entries=16; physical_registers=48; memory_entries=2; branch_predictor_entries=32; checks_requested=$checks
    performance_verified=$true; pipeline_oracles_verified=$true
    side_issue_oracles_verified=$true
    side_store_oracle_verified=$true; side_store_counts=$short.side_store_counts
    raw_fault_oracles_verified=$true; raw_fault_counts=$short.raw_fault_counts
    instruction_permission_oracles_verified=$true
    frontend_feedback_oracles_verified=$true; head_trap_ledger_oracle_verified=$true; head_trap_machine_oracle_verified=$true
    head_trap_machine_scope='DIRECT-IRQ/SystemModel; not production registered IMSIC'
    shared_physical_oracles_verified=$true; shared_physical_counts=$short.shared_physical_counts
    head_system_ledger_oracle_verified=$true; head_system_ledger_counts=$short.head_system_ledger_counts
    authorization_machine_oracle_verified=$true; authorization_machine_cycles_equal=$true
    authorization_machine_counts=$short.authorization_machine_counts
    authorization_machine_cases=$short.authorization_machine_cases
    authorization_machine_scope='Legal external FENCE.I backpressure; independent SystemModel; DIRECT-IRQ; not production registered IMSIC'
    feedback_inputs_sha256=$short.feedback_inputs_sha256
    performance_verification_scope='Raw A/B cycle, retirement and issue/rename histograms plus independent NEMU positive/negative checks verified'
    performance_improvement_claimed=$false; engineering_review_required=($regressions.Count -gt 0)
    performance_regressions=@($regressions); comparisons=@($performance.comparisons)
    same_clock_geomean_speedup=$performance.same_clock_geomean_speedup
    clock_assumption=$performance.clock_assumption
    pipeline_recovery_witnesses=$performance.pipeline_recovery_witnesses
    hardware_source_sha256=$short.hardware_source_sha256
    coremark_single_iteration_ticks=$short.coremark_single_iteration_ticks; coremark_sha256=$short.coremark_sha256
    ddr_4k_read_write_copy_chase_ticks=@($short.ddr_4k_read_write_copy_chase_ticks); generated_board_models=1
    not_a_coremark_score_or_fpga_bandwidth=$true; same_binary_application_reporting_timebase_hz=50000000
    uart_protocol_retested=($short.uart_protocol_retested -eq $true)
    routed_timing_verified=$false; on_board_verified=$false
    evidence_roots=@($shortRoot, $performanceRoot); evidence_hash_manifest='evidence-files.json'
    bootrom_sha256=$bootHash
}
$combined | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath (Join-Path $out 'results.json') -Encoding utf8
Write-Output ('THROUGHPUT_ACCEPTANCE: PASS ' + $out)
Write-Output ('PERFORMANCE_REVIEW_REQUIRED: ' + $combined.engineering_review_required)
