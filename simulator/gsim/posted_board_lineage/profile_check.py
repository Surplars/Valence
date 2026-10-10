"""Independent DMA4 constructor/geometry gate; no elaboration or simulator calls.

Inputs are parsed summary dictionaries and CHIRRTL text (or a pathlib.Path).
Failures raise ValueError. Successful calls return small JSON-serializable evidence.
The expected constructor was prepared independently of the summary emitter.
"""
import copy
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
EXPECTED_PATH = HERE / 'expected-profile.json'
EXPECTED = json.loads(EXPECTED_PATH.read_text())


def _require(condition, message):
    if not condition:
        raise ValueError('posted DMA4 profile: ' + message)


def _equal(actual, expected, path):
    # Python bool == int must not silently admit wrongly typed JSON.
    _require(type(actual) is type(expected), path + ': type differs')
    if isinstance(expected, dict):
        _require(set(actual) == set(expected), path + ': keys differ; missing=' +
                 str(sorted(set(expected) - set(actual))) + ' extra=' + str(sorted(set(actual) - set(expected))))
        for key in expected:
            _equal(actual[key], expected[key], path + '.' + key)
    elif isinstance(expected, list):
        _require(len(actual) == len(expected), path + ': length differs')
        for index, value in enumerate(expected):
            _equal(actual[index], value, path + '[' + str(index) + ']')
    else:
        _require(actual == expected, path + ': expected ' + repr(expected) + ', got ' + repr(actual))


def _at(summary, path):
    value = summary
    for key in path.split('.'):
        _require(isinstance(value, dict) and key in value, 'missing ' + path)
        value = value[key]
    return value


# Explicit mapping: these are expected-model names, not guessed Scala labels.
DERIVED_PATHS = {
    'isa': 'derived.isaProfile', 'issueWidth': 'derived.issueWidth',
    'instructionCacheLines': 'derived.instructionCacheLines', 'dataCacheLines': 'derived.dataCacheLines',
    'cacheWays': 'derived.cacheWays', 'cacheLineBytes': 'derived.cacheLineBytes',
    'instructionTranslationEntries': 'derived.instructionTranslationEntries',
    'dataTranslationEntries': 'derived.dataTranslationEntries', 'pteCacheEntries': 'derived.pteCacheEntries',
    'readMshrs': 'cache.readMshrs', 'responseEntries': 'cache.responseEntries',
    'writebackEntries': 'cache.writebackEntries', 'axiReadOutstanding': 'ddr.maxOutstanding',
    'axiWriteOutstanding': 'ddr.maxOutstandingWrites', 'maxBurstBeats': 'ddr.maxBurstBeats',
    'axiIdBits': 'ddr.axiIdWidth', 'unorderedResponses': 'ddr.unorderedResponses',
    'cpuHz': 'derived.cpuHz', 'uartBaud': 'derived.uartBaud', 'romBase': 'derived.romBase',
    'romBytes': 'derived.romBytes', 'ramBase': 'derived.ramBase', 'ramBytes': 'derived.ddrBytes',
}
CORE_KEYS = set('''renameWidth commitWidth completionWidth robEntries physicalRegs tagBits speculativeRamBase speculativeRamBytes memoryEntries branchPredictorEntries bufferedRamStores registeredLocalStoreResponses registeredImsicInterrupts registeredMemoryRequests registeredStoreResponseOwners registeredBranchRedirect registeredMemoryAddress registeredRobRetirement registeredLoadReplay loadOrderOlderRetire parallelRenameAdmission stableFetchFaultMetadata precompleteMispredictedBranch earlyRankedOperands pcDerivedReturnLinks earlyRenameDestinations parallelPrfReadyUpdates stablePredictionMetadata balancedBranchCompare separateBranchRetireFault parallelReturnStackControl earlyRedirectCapture parallelMemoryPreparation alignedFetchPmp parallelIssuePayload rawFetchPresence oneHotPhysicalOperands registeredTranslatedResponses translatedResponseEmptyFlow directMemoryResponse parallelFetchAddresses prefixTileLinkDecode rawTileLinkResponseMetadata bufferedRomReplies parallelPredictionQualification parallelRecoveryAdmission parallelRedirectTokens parallelIssueRanks parallelAluResults parallelCompletionPayload parallelFetchTagLookup parallelFrontendControl parallelAuipcQualification parallelPredictionSources parallelAddressSums bufferedFetchRequests parallelFetchAlignment parallelDecodeLegality flowThroughFetchRequests parallelMinMaxResults parallelBitLegality parallelRenameRanks parallelMinMaxWordResults parallelArchitecturalDestinations parallelAluWordResults independentFetchCapture parallelHomeQualification registeredFabricBoundary registeredTranslationHeads fetchReplyTurnover fetchIdentityTranslation registeredPredictionTraining parallelMemoryPayload parallelPacketPmp registeredIssueExecute registeredFetchPacket wordSpanPacketPmp parallelFetchValidation fetchHintEntries balancedPacketPmp compactMemoryOperandSelect parallelMemoryAddressSum capturedFetchPermission splitFetchCursor registeredFetchWindow fastHeadTrapRecovery fastHeadSystemRecovery tentativeRenameSources sharedPhysicalSourceDecode ownerLocalOperandReady earlyStorePreparation parallelMulDivDispatch registeredMulDivOperands registeredIssueHeadMask unconditionalMemoryPayloadCapture earlyRecoveryIssueBlock fastBufferedStoreRetire fastHeadLoadRetire loadCompletionBypass registeredLoadIssueForwarding mulWordPreviewBypass moveAlias flowTileLinkResponse storeBufferEntries machineSystem experimentalFloatingPoint floatingPoint advertiseFloatingPoint atomicMemory pmpEntries virtualMemoryLevels compressedInstructions instructionCacheSets returnStackEntries indirectTargetEntries recoveryWidth identityDataRequestFlow precheckedDataRequestFlow physicalLoadIngressFlow bankedRobPayload sharedStoreOperandReads lvtPhysicalRegisterFile dataNextLinePrefetch dataStoreNextLinePrefetch virtualRamLoadPrecheck bankedIssuePayload bankedFetchHints independentFetchPayloadCapture ownerLocalIssueReady sharedFetchPmpRelations shareProtectedHeadPayload fetchPreviousPacket preparedStoreLookahead postedStoreMerge postedPrefetchHeadOffer'''.split())
CORE_REQUIRED = {
    'postedPrefetchHeadOffer': False, 'fastBufferedStoreRetire': False, 'memoryEntries': 4, 'robEntries': 16,
    'renameWidth': 2, 'commitWidth': 2, 'completionWidth': 2, 'tagBits': 64,
    'physicalRegs': 48, 'storeBufferEntries': 2,
    'precheckedDataRequestFlow': False, 'translatedResponseEmptyFlow': False,
    'physicalLoadIngressFlow': True, 'loadOrderOlderRetire': True,
    'fetchPreviousPacket': True, 'prefixTileLinkDecode': True,
    'virtualRamLoadPrecheck': True, 'preparedStoreLookahead': True,
    'bufferedRamStores': True, 'registeredMemoryRequests': True,
    'registeredMemoryAddress': True, 'registeredTranslationHeads': True,
    'identityDataRequestFlow': True, 'registeredTranslatedResponses': True,
    'registeredLoadIssueForwarding': True, 'registeredFetchWindow': True,
    'dataNextLinePrefetch': True, 'dataStoreNextLinePrefetch': True,
    'machineSystem': True, 'atomicMemory': True, 'compressedInstructions': True,
    'pmpEntries': 16, 'virtualMemoryLevels': 3, 'advertiseFloatingPoint': True,
    'speculativeRamBase': 0x80200000, 'speculativeRamBytes': 0x80000000,
}
STORAGE = {key: True for key in ('bankedRobPayload', 'sharedStoreOperandReads',
    'lvtPhysicalRegisterFile', 'bankedIssuePayload', 'bankedFetchHints', 'shareProtectedHeadPayload')}
FP_RESOURCES = {key: True for key in ('committedStateMemory', 'sharedFormatRounders', 'sharedMultiplyFused')}
FP = {key: True for key in ('f', 'd', 'addSubtract', 'multiply', 'divide', 'squareRoot',
    'fusedMultiplyAdd', 'compareMinMax', 'signClassMove', 'conversions', 'memory')}
FP['resources'] = FP_RESOURCES


def verify_profile(summary, mode):
    _require(mode in ('off', 'on'), 'mode must be off or on')
    _require(isinstance(summary, dict), 'summary must be an object')
    _require(set(summary) == {'schema', 'profile', 'core', 'cache', 'ddr', 'storage',
        'tags', 'floatingPointResources', 'network', 'derived'}, 'summary keys differ')
    _equal(summary['schema'], 'posted-board-full-profile-v1', 'schema')
    _equal(summary['profile'], EXPECTED['fpga_next_config'][mode], 'profile')
    _require(set(DERIVED_PATHS) == set(EXPECTED['derived']), 'incomplete expected geometry mapping')
    for name, path in DERIVED_PATHS.items():
        _equal(_at(summary, path), EXPECTED['derived'][name], path)
    derived = {path.split('.')[1]: EXPECTED['derived'][name] for name, path in DERIVED_PATHS.items()
               if path.startswith('derived.')}
    derived.update(timingProfile='staged-fetch-turnover-mlp4', identityDataFlow=True,
        loadIssueForwarding=True, instructionPrefetch=True, coherentSourceBits=3,
        coherentSinkBits=1, axiAddressBits=32)
    _equal(summary['derived'], derived, 'derived')
    _equal(summary['cache'], dict(readMshrs=2, responseEntries=2, writebackEntries=2,
        overlapWritebackRefill=True, nextLinePrefetch=True, prefetchCandidateCycles=1,
        prefetchBreakOnStore=False, storeNextLinePrefetch=True, storePrefetchMruInsertion=True,
        postedPrefetchCoexistence=False), 'cache')
    _equal(summary['ddr'], dict(maxOutstanding=4, maxBurstBeats=16, axiIdWidth=4,
        maxOutstandingWrites=2, unorderedResponses=True), 'ddr')
    _equal(summary['storage'], STORAGE, 'storage')
    _equal(summary['tags'], dict(compact=True, bankedStorage=True), 'tags')
    _equal(summary['floatingPointResources'], FP_RESOURCES, 'floatingPointResources')
    _equal(summary['network'], dict(maxFrameBytes=2048, macRxSlots=4, postedRxSlots=4,
        memoryCredits=4, postedTxSlots=4), 'network')
    core = summary['core']
    _require(isinstance(core, dict) and set(core) == CORE_KEYS, 'complete core constructor keys differ')
    for name, expected in dict(CORE_REQUIRED, **STORAGE, floatingPoint=FP,
                              postedStoreMerge=(mode == 'on')).items():
        _equal(core[name], expected, 'core.' + name)
    for name in ('independentFetchPayloadCapture', 'ownerLocalIssueReady', 'sharedFetchPmpRelations'):
        _equal(core[name], True, 'core.' + name)
    return {'mode': mode, 'profile_fields': len(summary['profile']), 'core_fields': len(core),
            'expected_sha256': hashlib.sha256(EXPECTED_PATH.read_bytes()).hexdigest(),
            'native_reference': EXPECTED['native_reference']}


def verify_profile_pair(off, on):
    verify_profile(off, 'off')
    verify_profile(on, 'on')
    normalized = copy.deepcopy(on)
    normalized['profile']['postedStoreMerge'] = False
    normalized['core']['postedStoreMerge'] = False
    _equal(off, normalized, 'OFF/ON full summary')
    return {'only_differences': ['profile.postedStoreMerge', 'core.postedStoreMerge']}


def _modules(fir):
    text = fir.read_text() if isinstance(fir, Path) else fir
    _require(isinstance(text, str), 'FIR must be text or Path')
    starts = list(re.finditer(r'^  (?:public )?module ([A-Za-z_][A-Za-z_0-9]*)\s*:', text, re.M))
    _require(bool(starts), 'no FIR modules')
    result = {}
    for index, match in enumerate(starts):
        _require(match[1] not in result, 'duplicate FIR module ' + match[1])
        result[match[1]] = text[match.end():starts[index + 1].start() if index + 1 < len(starts) else len(text)]
    return result


def _family(modules, name):
    return {key: value for key, value in modules.items() if re.fullmatch(re.escape(name) + r'(?:_\d+)?', key)}


def _bundle(text, name):
    match = re.search(r'\b' + re.escape(name) + r'\s*:\s*\{', text)
    _require(match is not None, 'FIR missing bundle ' + name)
    start, depth = match.end(), 1
    for end in range(start, len(text)):
        depth += (text[end] == '{') - (text[end] == '}')
        if depth == 0:
            return text[start:end]
    raise ValueError('posted DMA4 profile: malformed FIR bundle ' + name)


def verify_fir(fir):
    modules = _modules(fir)
    homes = _family(modules, 'MixedCoherentLineHome')
    _require(len(homes) == 1, 'FIR requires exactly one MixedCoherentLineHome')
    home = next(iter(homes.values()))
    owners = re.findall(r'^    regreset ownedLines\s*:\s*UInt<1>\[(\d+)\],', home, re.M)
    _require(owners == ['4'], 'FIR MixedCoherentLineHome actual ownedLines must be UInt<1>[4]')
    tlbs = []
    for body in _family(modules, 'SvTranslationService').values():
        found = re.findall(r'^    regreset tlb\s*:\s*[^\n]*\}\[(\d+)\], clock,', body, re.M)
        _require(len(found) == 1, 'FIR translation service actual tlb declaration absent/ambiguous')
        tlbs.append(int(found[0]))
    _require(sorted(tlbs) == [8, 16], 'FIR actual instruction/data TLB dimensions differ')
    ptes = []
    for body in _family(modules, 'SvPteDataBridge').values():
        found = re.findall(r'^    regreset cache\s*:\s*[^\n]*\}\[(\d+)\], clock,', body, re.M)
        _require(len(found) == 1, 'FIR PTE bridge actual cache declaration absent/ambiguous')
        ptes.append(int(found[0]))
    _require(ptes == [4, 4], 'FIR actual PTE cache dimensions differ')
    _require('BoardSocGsim' in modules, 'FIR top BoardSocGsim missing')
    ports = re.findall(r'^    output io\s*:\s*(.*)$', modules['BoardSocGsim'], re.M)
    _require(len(ports) == 1, 'FIR top io declaration absent/ambiguous')
    axi = _bundle(ports[0], 'ddrAxi')
    for channel in ('ar', 'aw', 'r', 'b'):
        bits = _bundle(_bundle(axi, channel), 'bits')
        _require(re.search(r'\bid\s*:\s*UInt<4>(?:\s*[,}])', bits + '}') is not None,
                 'FIR top DDR ' + channel + ' ID must be 4 bits')
        if channel in ('ar', 'aw'):
            _require(re.search(r'\baddr\s*:\s*UInt<32>(?:\s*[,}])', bits + '}') is not None,
                     'FIR top DDR ' + channel + ' address must be 32 bits')
    return {'dma_owned_lines': 4, 'translation_entries': sorted(tlbs),
            'pte_cache_entries': ptes, 'axi_id_bits': 4, 'axi_address_bits': 32}
