"""Fail-closed CPU/configuration identity checks shared by emit and board gates.

These are provenance checks, not functional or physical qualification. In
particular, a CPU-leaf PASS never admits an experimental CPU to a board run.
Legacy public records may omit identity; explicitly selected candidates may not.
"""
import hashlib
import json
import re

PUBLIC = {'a1': 'selected', 'i1': 'public-i1'}
EXPERIMENTAL = frozenset(('full-r1', 'full-r1-m3'))
PUBLIC_QUALIFICATION = 'PUBLIC_UNCHANGED_NOT_TIMING_QUALIFIED'
EXPERIMENTAL_QUALIFICATION = 'EXPERIMENTAL_NOT_TIMING_QUALIFIED'
IDENTITY_KEYS = frozenset(('schema', 'cpuFamily', 'microarchitectureProfile', 'qualification',
                           'effectiveConfig', 'effectiveCore', 'memoryProfile', 'boundary',
                           'sharedFabricConfig', 'clockProfile', 'nominalClocks', 'runtimeMode', 'identitySha256'))
BOARD_KEYS = ('cpu_microarchitecture_profile', 'cpu_microarchitecture_sha256')
PROFILE_KEYS = ('microarchitectureProfile', 'cpuMicroarchitectureProfile',
                'cpu_microarchitecture_profile', 'a1MicroarchitectureProfile')
PUBLIC_BACKEND = dict(completionTopology='legacy', branchResolutionTopology='writeback-coupled',
                      circularFetchPayload='false', completedCanonicalStoreForwarding='false',
                      registeredDataTranslation='false')
CANDIDATE_BACKEND = dict(completionTopology='dual-owner', branchResolutionTopology='execution-mailbox',
                         circularFetchPayload='true', registeredDataTranslation='false')
CPU_PRIVATE_DELTAS = frozenset(('virtualRamLoadPrecheck', 'lsuEntries', 'dataTranslationEntries',
                                'canonicalVirtualStoreOverlap', 'independentDemandAdmission',
                                'translationHitFlow', 'dataTlbWriteReadReuse', 'loadOrderOlderRetire',
                                'completionTopology', 'branchResolutionTopology', 'fetchTransactionSlots',
                                'alignedFetchSinglePage', 'circularFetchPayload',
                                'completedCanonicalStoreForwarding'))
EMISSION_CLOCK_KEYS = dict(cpuHz='cpuClockHz', fabricHz='fabricClockHz', timebaseHz='timebaseHz',
                           ddrUiHz='ddrUiHz', aonHz='aonHz', uartHz='uartHz')


def _require(ok, message):
    if not ok:
        raise ValueError('CPU identity: ' + message)


def _profile(cpu_family, expected_profile):
    _require(isinstance(cpu_family, str) and cpu_family in PUBLIC, 'unknown CPU family')
    result = PUBLIC[cpu_family] if expected_profile is None else expected_profile
    _require(isinstance(result, str) and (result == PUBLIC[cpu_family] or
             cpu_family == 'a1' and result in EXPERIMENTAL),
             'unknown or wrong-family microarchitecture profile: ' + str(result))
    return result


def canonical(value):
    """Canonical UTF-8 JSON; Scala emits primitive configuration leaves as strings."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def identity_sha256(identity):
    _require(isinstance(identity, dict), 'identity must be an object')
    return hashlib.sha256(canonical({k: v for k, v in identity.items() if k != 'identitySha256'})).hexdigest()


def _product(value, path):
    if isinstance(value, dict):
        _require(all(isinstance(k, str) and k for k in value), path + ' has a non-string/empty key')
        for key, child in value.items():
            _product(child, path + '.' + key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _product(child, path + '[' + str(index) + ']')
    else:
        _require(value is None or isinstance(value, str), path + ' must use string/null scalar leaves')


def _fields(value, expected, path):
    for key, wanted in expected.items():
        _require(value.get(key) == wanted, path + '.' + key + ' disagrees with selector')


def nominal_clocks(cpu_family, clock_profile):
    """Actual CommonCpuProfile clocks, not the FpgaNextConfig template clocks."""
    _profile(cpu_family, None)
    _require(clock_profile in ('production', 'boot50-static', 'performance300-static', 'boot50-dynamic'),
             'unknown clock profile')
    _require(cpu_family == 'i1' or clock_profile in ('production', 'boot50-static'),
             'performance300-static and boot50-dynamic remain I1-only')
    low = clock_profile in ('boot50-static', 'boot50-dynamic')
    return dict(cpuHz='50000000' if low else '300000000' if cpu_family == 'i1' else '100000000',
                fabricHz='50000000' if low else '250000000', timebaseHz='250000000',
                ddrUiHz='250000000', aonHz='50000000', uartHz='50000000')


def _shared_fabric(config, shared, candidate):
    """The selected CPU may change only its explicit CPU-private parameter set."""
    _require(set(config) == set(shared), 'CPU/shared fabric product shapes differ')
    for key in config:
        if candidate and key in CPU_PRIVATE_DELTAS:
            continue
        if candidate and key == '_derived':
            left, right = config[key], shared[key]
            _require(isinstance(left, dict) and isinstance(right, dict) and set(left) == set(right),
                     'CPU/shared derived product shapes differ')
            for name in left:
                if name == 'cache':
                    a, b = left[name], right[name]
                    _require(isinstance(a, dict) and isinstance(b, dict) and set(a) == set(b),
                             'CPU/shared cache product shapes differ')
                    _require({k: v for k, v in a.items() if k != 'independentDemandAdmission'} ==
                             {k: v for k, v in b.items() if k != 'independentDemandAdmission'},
                             'candidate changed cache geometry or non-admission policy')
                else:
                    _require(left[name] == right[name], 'candidate changed shared derived configuration: ' + name)
        else:
            _require(config[key] == shared[key], 'candidate changed shared configuration: ' + key)
    _fields(shared, PUBLIC_BACKEND, 'sharedFabricConfig')
    _fields(shared, dict(fetchTransactionSlots='1', lsuEntries='2', dataTranslationEntries='8'), 'sharedFabricConfig')


def _candidate_claims(value, cpu_family):
    """Find explicit candidate claims even when an identity was accidentally dropped."""
    if not isinstance(value, dict):
        return False
    for key, child in value.items():
        if key in PROFILE_KEYS and child != PUBLIC.get(cpu_family):
            return True
        if key in ('qualification', 'cpuQualification') and child == EXPERIMENTAL_QUALIFICATION:
            return True
        if key == 'runtimeMode' and child == 'experimental-a1-runtime':
            return True
        if key in ('completionTopology', 'branchResolutionTopology') and child != PUBLIC_BACKEND[key]:
            return True
        if key in ('circularFetchPayload', 'completedCanonicalStoreForwarding', 'registeredDataTranslation'):
            if child not in (False, 'false'):
                return True
        if cpu_family == 'a1' and key in ('lsuEntries', 'memoryEntries', 'fetchTransactionSlots',
                                         'dataTranslationEntries', 'tlbEntries'):
            public = dict(lsuEntries='2', memoryEntries='2', fetchTransactionSlots='1',
                          dataTranslationEntries='8', tlbEntries='8')
            if str(child) != public[key]:
                return True
        if key == 'memoryProfile' and child is not None:
            return True
        if isinstance(child, dict) and _candidate_claims(child, cpu_family):
            return True
        if isinstance(child, list) and any(_candidate_claims(item, cpu_family) for item in child):
            return True
    return False


def validate(identity, cpu_family, expected_profile):
    """Validate one complete identity, or an explicitly public legacy absence.

    Returns the original object (or None) without changing it. Call
    validate_emission for old records, which also checks candidate claims outside
    the nested identity. A candidate must never substitute source hashes alone.
    """
    profile = _profile(cpu_family, expected_profile)
    if identity is None:
        _require(expected_profile is not None and profile == PUBLIC[cpu_family],
                 'missing identity for requested profile: ' + profile)
        return None
    _require(isinstance(identity, dict) and set(identity) == IDENTITY_KEYS, 'incomplete/unknown identity fields')
    _require(type(identity['schema']) is int and identity['schema'] == 1, 'unsupported schema')
    _require(identity['cpuFamily'] == cpu_family, 'CPU family mismatch')
    _require(identity['microarchitectureProfile'] == profile, 'microarchitecture selector mismatch')
    candidate = profile in EXPERIMENTAL
    _require(identity['qualification'] == (EXPERIMENTAL_QUALIFICATION if candidate else PUBLIC_QUALIFICATION),
             'qualification must remain explicitly not timing qualified')
    for key in ('effectiveConfig', 'effectiveCore', 'boundary', 'sharedFabricConfig', 'nominalClocks'):
        _require(isinstance(identity[key], dict) and identity[key], key + ' must be a nonempty product')
        _product(identity[key], key)
    sha = identity['identitySha256']
    _require(isinstance(sha, str) and re.fullmatch('[0-9a-f]{64}', sha), 'invalid SHA256')
    _require(sha == identity_sha256(identity), 'digest mismatch; effective configuration changed')
    _require(identity['nominalClocks'] == nominal_clocks(cpu_family, identity['clockProfile']),
             'nominalClocks must match the complete selected CPU/clock profile tuple')
    _require(identity['runtimeMode'] in ('static', 'experimental-a1-runtime', 'public-i1-runtime'), 'unknown runtime mode')
    _require(identity['runtimeMode'] != 'experimental-a1-runtime' or
             cpu_family == 'a1' and identity['clockProfile'] == 'boot50-static',
             'experimental A1 runtime requires A1 boot50-static')
    _require(identity['runtimeMode'] != 'public-i1-runtime' or
             cpu_family == 'i1' and identity['clockProfile'] == 'boot50-dynamic',
             'public I1 runtime requires I1 boot50-dynamic')
    config, core = identity['effectiveConfig'], identity['effectiveCore']
    if cpu_family == 'a1':
        backend = dict(CANDIDATE_BACKEND, completedCanonicalStoreForwarding=str(profile == 'full-r1-m3').lower()) \
            if candidate else PUBLIC_BACKEND
        _fields(config, backend, 'effectiveConfig')
        _fields(core, backend, 'effectiveCore')
        _fields(config, dict(fetchTransactionSlots='2' if candidate else '1',
                             lsuEntries='4' if candidate else '2',
                             dataTranslationEntries='16' if candidate else '8'), 'effectiveConfig')
        _fields(core, dict(memoryEntries='4' if candidate else '2'), 'effectiveCore')
        _shared_fabric(config, identity['sharedFabricConfig'], candidate)
        if candidate:
            runtime = str(identity['runtimeMode'] == 'experimental-a1-runtime').lower()
            _fields(identity['boundary'], dict(runtimeMaintenance=runtime, runtimeCancellation=runtime,
                                               runtimeInterruptHold=runtime), 'boundary')
            _fields(config, dict(alignedFetchSinglePage='true', translationHitFlow='true'), 'effectiveConfig')
            _fields(core, dict(robEntries='16', physicalRegs='48', renameWidth='2', commitWidth='2',
                               completionWidth='2', pmpEntries='16', virtualMemoryLevels='3',
                               compressedInstructions='true'), 'effectiveCore')
    else:
        _require(not _candidate_claims(config, cpu_family) and not _candidate_claims(core, cpu_family),
                 'I1 identity carries an A1 candidate configuration')
    _require(identity['memoryProfile'] == ('experimental-memory-parallel' if candidate else None),
             'memory profile disagrees with selector')
    return identity


def validate_emission(emission, expected_profile=None):
    """Validate nested identity against the actual emission and caller selection."""
    _require(isinstance(emission, dict), 'emission must be an object')
    cpu = emission.get('cpu')
    identity = emission.get('cpuMicroarchitecture')
    _require('cpuMicroarchitecture' not in emission or isinstance(identity, dict),
             'present cpuMicroarchitecture must be an object, not null')
    declared = identity.get('microarchitectureProfile') if isinstance(identity, dict) else None
    profile = _profile(cpu, expected_profile if expected_profile is not None else declared)
    if identity is None:
        _require(not _candidate_claims(emission, cpu), 'candidate claims require cpuMicroarchitecture identity')
    result = validate(identity, cpu, profile)
    for key in PROFILE_KEYS:
        if key in emission:
            _require(emission[key] == profile, 'emission selector mismatch: ' + key)
    if identity is not None:
        if 'cpuQualification' in emission:
            _require(emission['cpuQualification'] == identity['qualification'], 'emission qualification mismatch')
        _require(identity['clockProfile'] == emission.get('clockProfile', 'production'), 'emission clock profile mismatch')
        for key, outer in EMISSION_CLOCK_KEYS.items():
            if outer in emission:
                _require(str(emission[outer]) == identity['nominalClocks'][key],
                         'emission nominal clock mismatch: ' + outer)
        for key in ('effectiveConfig', 'effectiveCore', 'memoryProfile', 'boundary', 'sharedFabricConfig',
                    'nominalClocks', 'runtimeMode'):
            if key in emission:
                _require(emission[key] == identity[key], 'emission/identity mismatch: ' + key)
        if 'tlbEntries' in emission:
            product = identity['effectiveConfig'] if cpu == 'a1' else identity['effectiveCore']
            key = 'dataTranslationEntries' if cpu == 'a1' else 'tlbEntries'
            _require(str(emission['tlbEntries']) == product.get(key), 'emission TLB geometry mismatch')
        if 'issueWidth' in emission:
            _require(type(emission['issueWidth']) is int and emission['issueWidth'] == (2 if cpu == 'a1' else 1),
                     'emission issue width mismatch')
    return result


def check_reuse(expected, cached):
    """Require complete matching identity before any cached model/result reuse."""
    if expected is None or cached is None:
        _require(expected is None and cached is None, 'cached identity missing; legacy/candidate reuse forbidden')
        return None
    _require(isinstance(expected, dict) and isinstance(cached, dict), 'cached identity must be an object')
    for identity in (expected, cached):
        validate(identity, identity.get('cpuFamily'), identity.get('microarchitectureProfile'))
    _require(canonical(expected) == canonical(cached), 'cached effective identity differs from requested identity')
    return expected['identitySha256']


def validate_board_configuration(config):
    """Validate optional digest binding without altering historic public digests."""
    _require(isinstance(config, dict), 'board configuration must be an object')
    present = [key in config for key in BOARD_KEYS]
    _require(all(present) or not any(present), 'board profile and identity SHA256 must be bound together')
    if all(present):
        _profile(config.get('cpu'), config[BOARD_KEYS[0]])
        sha = config[BOARD_KEYS[1]]
        _require(isinstance(sha, str) and re.fullmatch('[0-9a-f]{64}', sha), 'invalid board identity SHA256')


def bind_board_configuration(config, emission):
    """Return a copy bound to the emission; reject existing inconsistent bindings."""
    validate_board_configuration(config)
    identity = validate_emission(emission, config.get(BOARD_KEYS[0]))
    _require(config.get('cpu') == emission.get('cpu'), 'board/emission CPU family mismatch')
    result = dict(config)
    if identity is not None:
        values = (identity['microarchitectureProfile'], identity['identitySha256'])
        for key, value in zip(BOARD_KEYS, values):
            _require(key not in config or config[key] == value, 'board/emission binding mismatch: ' + key)
            result[key] = value
    else:
        _require(not any(key in config for key in BOARD_KEYS), 'board binding has no emission identity')
    return result


def reject_experimental_board(config, emission=None):
    """Production board admission never accepts experimental or CHIRRTL evidence."""
    validate_board_configuration(config)
    _require(config.get(BOARD_KEYS[0]) not in EXPERIMENTAL and not _candidate_claims(config, config.get('cpu')),
             EXPERIMENTAL_QUALIFICATION + ': experimental CPU board admission is blocked')
    if emission is not None:
        bound = bind_board_configuration(config, emission)
        _require(bound == config, 'board configuration omits emitted CPU identity binding')
        identity = validate_emission(emission, config.get(BOARD_KEYS[0]))
        _require(identity is None or identity['microarchitectureProfile'] not in EXPERIMENTAL and
                 identity['runtimeMode'] != 'experimental-a1-runtime',
                 EXPERIMENTAL_QUALIFICATION + ': experimental CPU board admission is blocked')
        _require(emission.get('rtlFormat', 'SystemVerilog') == 'SystemVerilog',
                 'board admission requires SystemVerilog, not diagnostic CHIRRTL')
    return config
