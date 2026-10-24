#!/usr/bin/env python3
"""Fail-closed input/stage/report checks for a reviewed common-platform package."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import sys
import cpu_identity

SCHEMA = 'valence-common-local-v1'
CLOCKS = ('cpu', 'fabric', 'timebase', 'ddr_ui', 'uart', 'aon')
STAGES = ('simulation', 'synthesis', 'implementation')
TOOLS = {'simulation': ('xvlog', 'xelab', 'xsim'), 'synthesis': ('synth_design',),
         'implementation': ('opt_design', 'place_design', 'phys_opt_design', 'route_design')}
COVERAGE = ('no_clock', 'unconstrained_internal_endpoints', 'multiple_clock',
            'generated_clocks', 'loops', 'latch_loops')
IO_COVERAGE = ('no_input_delay', 'partial_input_delay', 'no_output_delay', 'partial_output_delay')
BOARD_REPORTS = ('rom-netlist.json', 'rom-mapping.json', 'reset-structure.tcllist',
                 'held-payload-mapping.tcllist', 'common-cdc-scopes.tcllist', 'common-bus-skew.rpt',
                 'board-cdc.rpt', 'io-coverage.rpt', 'io-allowances.tcllist')
REPORTS = ('timing.rpt', 'coverage.rpt', 'route.rpt', 'bus_skew.rpt', 'drc.rpt',
           'cdc.rpt', 'clocks.rpt', 'facts.json', 'board-audit.json')
ROOTS = ('src/main/scala', 'src/main/resources', 'src/test/scala/platform', 'fpga/common')
RUNTIME_CPU_FIELDS = ('runtime_cpu_hz_source', 'runtime_cpu_hz_resource_index',
                      'runtime_cpu_hz_address', 'profile_cpu_hz', 'build_contract', 'unpadded_rom')
CMU_CPU_SOURCE = 'CMU resource 1 nominalHz'
TIMEBASE_SOURCE = 'MachineTimer.timeValue -> TIME CSR; ticks in configured timebase domain'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key: ' + key)
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('non-finite JSON number: ' + value)
    return json.loads(Path(path).read_text(encoding='utf-8-sig'),
                      object_pairs_hook=unique, parse_constant=invalid_constant)


def relative(value):
    require(isinstance(value, str) and value, 'missing package-relative path')
    p = PurePosixPath(value)
    require(not p.is_absolute() and not PureWindowsPath(value).drive and '\\' not in value and
            str(p) == value and all(x not in ('.', '..') and x.rstrip(' .') == x and
            not re.search(r'[:<>"|?*\x00-\x1f]', x) and
            not re.fullmatch(r'(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', x)
            for x in p.parts), 'unsafe/nonportable relative path: ' + value)
    return p


def no_links(path):
    for p in (path, *path.parents):
        if p.exists() or p.is_symlink():
            info = p.lstat()
            require(not p.is_symlink() and not
                    (getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT),
                    'symlink/junction/reparse point forbidden: ' + str(p))


def local_windows_path(value):
    p = PureWindowsPath(value)
    require(bool(re.fullmatch(r'[A-Za-z]:', p.drive)) and p.is_absolute() and
            not str(value).startswith(('\\\\', '//', '/mnt/', '/home/')),
            'native local Windows drive path required: ' + str(value))


def file_at(root, value):
    p = root.joinpath(*relative(value).parts)
    no_links(p)
    require(p.is_file(), 'missing input/evidence file: ' + value)
    return p


def output_at(root, value):
    p = root.joinpath(*relative(value).parts)
    no_links(p)
    return p


def reviewed_board_clocks(cpu, profile='production'):
    require(cpu in ('i1', 'a1'), 'unreviewed CPU')
    require(profile in ('production', 'boot50-static', 'performance300-static', 'boot50-dynamic'), 'unreviewed board clock profile')
    require(profile != 'performance300-static' or cpu == 'i1', 'performance300-static is I1-only')
    low = profile in ('boot50-static', 'boot50-dynamic')
    return dict(cpu=50000000 if low else 300000000 if cpu == 'i1' else 100000000,
                fabric=50000000 if low else 250000000, timebase=250000000,
                ddr_ui=250000000, uart=50000000, aon=50000000)


def configuration(config):
    require(config.get('cpu') in ('i1', 'a1'), 'select exactly one CPU: i1 or a1')
    cpu_identity.validate_board_configuration(config)
    require(bool(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', config.get('top', ''))), 'real top name required')
    require(config.get('part') == 'xczu15eg-ffvb1156-2-i', 'unreviewed FPGA part')
    require(config.get('abi') == 1 and config.get('interrupt_abi') == 'aia', 'common ABI 1/AIA required')
    require(config.get('rom_base') == 0x80000000 and config.get('rom_bytes') == 131072,
            'common ABI ROM must be 128 KiB at 0x80000000')
    clocks = config.get('clocks_hz', {})
    require(set(clocks) == set(CLOCKS) and all(type(v) is int and 0 < v <= 1_000_000_000
                                            for v in clocks.values()), 'explicit positive domain frequencies required')
    profile = config.get('clock_profile', 'production')
    require(profile in ('production', 'boot50-static', 'performance300-static', 'boot50-dynamic'), 'unreviewed board clock profile')
    if profile in ('boot50-static', 'performance300-static', 'boot50-dynamic'):
        require(clocks == reviewed_board_clocks(config['cpu'], profile), 'unreviewed static low-clock topology')
    else:
        require(clocks['timebase'] == clocks['fabric'], 'production timebase must equal fabric clock')
    features = config.get('features', {})
    require(set(features) == {'mac', 'network_dma'} and all(type(v) is bool for v in features.values()),
            'explicit MAC/network DMA features required')
    require(not features['network_dma'] or features['mac'], 'network DMA requires MAC')
    return digest(config)


def firmware_inputs(root, fw):
    """Collect runtime firmware dependencies before freeze inventories inputs."""
    require(isinstance(fw, dict), 'firmware contract must be an object')
    if 'cpu_hz' not in fw or fw['cpu_hz'] is not None:
        return []
    paths = []
    for name, keys in (('build_contract', {'path', 'sha256'}),
                       ('unpadded_rom', {'path', 'sha256', 'bytes'})):
        record = fw.get(name)
        require(isinstance(record, dict) and set(record) == keys,
                'runtime firmware needs explicit ' + name + ' reference')
        require(isinstance(record['sha256'], str) and re.fullmatch('[0-9a-f]{64}', record['sha256']),
                'invalid runtime firmware reference SHA256: ' + name)
        file_at(root, record['path'])
        paths.append(record['path'])
    require(len(set(paths)) == len(paths), 'runtime firmware references must be distinct')
    return paths


def firmware_contract(root, m, fw):
    c, inputs, roles = m['configuration'], m['inputs'], m['roles']
    hz = c['clocks_hz']
    require(isinstance(fw, dict) and 'cpu_hz' in fw and
            type(fw.get('fabric_hz')) is int and fw['fabric_hz'] == hz['fabric'] and
            type(fw.get('timebase_hz')) is int and fw['timebase_hz'] == hz['timebase'] and
            fw.get('rom_sha256') == inputs[roles['rom']] and
            type(fw.get('abi')) is int and fw['abi'] == c['abi'],
            'firmware ROM/CPU/fabric/timebase contract mismatch')
    if fw['cpu_hz'] is not None:
        require(type(fw['cpu_hz']) is int and fw['cpu_hz'] == hz['cpu'] and
                not any(name in fw for name in RUNTIME_CPU_FIELDS),
                'static firmware CPU contract mismatch or ambiguous runtime fields')
        return
    require(fw.get('runtime_cpu_hz_source') == CMU_CPU_SOURCE and
            type(fw.get('runtime_cpu_hz_resource_index')) is int and fw['runtime_cpu_hz_resource_index'] == 1 and
            type(fw.get('runtime_cpu_hz_address')) is int and fw['runtime_cpu_hz_address'] == 0x10080148 and
            type(fw.get('profile_cpu_hz')) is int and fw['profile_cpu_hz'] == hz['cpu'],
            'runtime CPU source must be CMU resource 1 nominalHz at 0x10080148 with matching profile CPU Hz')
    for path in firmware_inputs(root, fw):
        require(path in inputs, 'unfrozen runtime firmware input: ' + path)
    for name in ('build_contract', 'unpadded_rom'):
        record = fw[name]
        require(record['sha256'] == inputs[record['path']] == sha(file_at(root, record['path'])),
                'runtime firmware reference hash mismatch: ' + name)
    build = read(file_at(root, fw['build_contract']['path']))
    require(isinstance(build, dict) and type(build.get('schema')) is int and build['schema'] == 1 and
            'cpu_hz' in build and build['cpu_hz'] is None and build.get('cpu_clock_source') == CMU_CPU_SOURCE and
            build.get('cmu_clock_metadata') is True and
            type(build.get('fabric_hz')) is int and build['fabric_hz'] == hz['fabric'] and
            type(build.get('timebase_hz')) is int and build['timebase_hz'] == hz['timebase'] and
            build.get('timebase_source') == TIMEBASE_SOURCE and
            build.get('bootrom_sha256') == fw['unpadded_rom']['sha256'],
            'runtime firmware build contract/ROM/fabric/timebase mismatch')
    raw = fw['unpadded_rom']
    require(raw['path'] != roles['rom'] and type(raw['bytes']) is int and 0 < raw['bytes'] <= c['rom_bytes'],
            'explicit separate unpadded ROM and valid byte count required')
    original = file_at(root, raw['path']).read_bytes()
    padded = file_at(root, roles['rom']).read_bytes()
    require(len(original) == raw['bytes'] and len(padded) == c['rom_bytes'] and
            padded == original + bytes(c['rom_bytes'] - len(original)),
            'board ROM must equal original build ROM with zero padding to 128 KiB')


def preflight(manifest, windows=False):
    manifest = Path(manifest).absolute()
    no_links(manifest)
    root = manifest.parent
    if windows:
        require(os.name == 'nt', 'use Windows Python and Windows Vivado, not WSL')
        local_windows_path(str(root))
        import ctypes
        drive_type = ctypes.windll.kernel32.GetDriveTypeW
        drive_type.argtypes = [ctypes.c_wchar_p]
        drive_type.restype = ctypes.c_uint
        require(drive_type(str(PureWindowsPath(root).anchor)) == 3,
                'package must be on a local fixed Windows disk, not a mapped network drive')
    run = root / 'local-run'
    if run.exists():
        no_links(run)
        require((run / 'manifest-sha256.txt').is_file() and
                (run / 'manifest-sha256.txt').read_text().strip() == sha(manifest),
                'manifest changed after run preparation')
        require((run / 'config-sha256.txt').is_file() and
                (run / 'config-sha256.txt').read_text().strip() == sha(run / 'config.tcl'),
                'resolved Tcl configuration changed after run preparation')
    m = read(manifest)
    require(m.get('schema') == SCHEMA, 'wrong/incomplete manifest schema')
    profile = configuration(m.get('configuration', {}))
    cpu_identity.reject_experimental_board(m['configuration'])
    require(type(m.get('threads')) is int and m['threads'] >= 8, 'request at least eight threads')
    inputs = m.get('inputs', {})
    require(isinstance(inputs, dict) and inputs, 'frozen input SHA256 inventory required')
    require(len({p.casefold() for p in inputs}) == len(inputs), 'case-colliding input names')
    for name, expected in inputs.items():
        require(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected), 'invalid input SHA256: ' + name)
        require(sha(file_at(root, name)) == expected, 'input hash mismatch: ' + name)
    for fixed in ('manifest.py', 'run-local.ps1', 'stage.tcl', 'signoff.tcl'):
        require('fpga/common/' + fixed in inputs, 'runner must be frozen with package: ' + fixed)
    roots = m.get('source_roots', [])
    require(isinstance(roots, list) and set(ROOTS).issubset(roots), 'complete production/resources/common-test/tool roots required')
    for name in roots:
        path = output_at(root, name)
        require(path.is_dir(), 'missing source root: ' + name)
        for p in path.rglob('*'):
            no_links(p)
            if p.is_file() and '__pycache__' not in p.parts:
                require(p.relative_to(root).as_posix() in inputs, 'unmanifested source: ' + str(p))
    roles = m.get('roles', {})
    emission_path = roles.get('emission_profile')
    if emission_path is not None or any(key in m['configuration'] for key in cpu_identity.BOARD_KEYS):
        require(emission_path in inputs, 'missing frozen CPU identity emission profile')
        cpu_identity.reject_experimental_board(m['configuration'], read(file_at(root, emission_path)))
    for name in ('rtl_filelist', 'firmware_contract', 'functional_receipt', 'rom', 'board_audit_script'):
        require(roles.get(name) in inputs, 'missing frozen input role: ' + name)
    for name in ('constraints', 'ip'):
        require(isinstance(roles.get(name), list) and roles[name] and
                all(p in inputs for p in roles[name]), 'missing frozen input role: ' + name)
    rtl = file_at(root, roles['rtl_filelist']).read_text().splitlines()
    require(rtl and len(rtl) == len(set(rtl)), 'nonempty unique RTL filelist required')
    top = m['configuration']['top']
    for p in rtl:
        relative(p)
        require(p in inputs and p.endswith(('.v', '.sv')), 'RTL filelist must use frozen relative filenames only')
    require(any(re.search(r'\bmodule\s+' + re.escape(top) + r'\b', file_at(root, p).read_text()) for p in rtl),
            'selected top is absent from actual RTL')
    fw = read(file_at(root, roles['firmware_contract']))
    firmware_contract(root, m, fw)
    functional = read(file_at(root, roles['functional_receipt']))
    require(functional.get('status') == 'PASS' and functional.get('scope') == 'common-platform-affected-short' and
            functional.get('profile_sha256') == profile and functional.get('physical_qualified') is False,
            'fresh matching common-platform functional receipt required; old no-MAC/CPU profile is insufficient')
    production = {name: h for name, h in inputs.items() if name.startswith(('src/main/scala/', 'src/main/resources/'))}
    require(functional.get('source_sha256') == production, 'functional receipt production/resource closure mismatch')
    require(set(m.get('stages', {})) == set(STAGES), 'all three explicit stage producers required')
    for phase in STAGES:
        s = m['stages'][phase]
        require(s.get('script') in inputs and s['script'].endswith('.tcl'), 'missing reviewed stage script: ' + phase)
        require(isinstance(s.get('outputs'), list) and s['outputs'], 'declare stage outputs: ' + phase)
        for name in s['outputs']:
            relative(name)
    require('routed.dcp' in m['stages']['implementation']['outputs'], 'implementation must produce routed.dcp')
    signoff = m.get('signoff', {})
    require(('producer' in m and signoff.get('bus_skew_checks') == 'mapped-scope') or
            type(signoff.get('bus_skew_checks')) is int and signoff['bus_skew_checks'] > 0,
            'reviewed nonzero bus-skew coverage count required')
    require(set(signoff.get('clock_pins', {})) == set(CLOCKS), 'actual endpoint pin for every clock domain required')
    require(all(isinstance(p, str) and re.fullmatch(r'[A-Za-z0-9_/$\.-]+', p)
                for p in signoff['clock_pins'].values()), 'exact non-wildcard clock endpoint names required')
    if "producer" in m:
        import producer
        producer.validate(root, m)
    return root, m, profile


def check_stage(root, m, profile, phase, out):
    require(phase in STAGES, 'unknown stage')
    no_links(out)
    r = read(file_at(out, 'stage-receipt.json'))
    require(r.get('status') == 'PASS' and r.get('phase') == phase and r.get('profile_sha256') == profile,
            'missing/mismatched stage PASS: ' + phase)
    expected = m['stages'][phase]['outputs']
    require(set(r.get('outputs_sha256', {})) == set(expected), 'incomplete stage output inventory: ' + phase)
    for name, expected_hash in r['outputs_sha256'].items():
        require(sha(file_at(out, name)) == expected_hash, 'stage output drift: ' + name)
    tools = r.get('tools', {})
    require(set(tools) == set(TOOLS[phase]), 'thread policy evidence missing for a phase tool: ' + phase)
    limitations = []
    for name, record in tools.items():
        require(record.get('requested_threads') == m['threads'], 'thread request mismatch: ' + name)
        command = record.get('command', [])
        require(isinstance(command, list) and command and all(isinstance(v, str) for v in command),
                'actual command tokens required: ' + name)
        require(not any(command[i:i+2] in (['-mt', 'off'], ['--mt', 'off']) for i in range(len(command))),
                'legacy explicit multithreading-off is forbidden: ' + name)
        evidence = record.get('evidence', {})
        require(sha(file_at(out, evidence.get('path'))) == evidence.get('sha256'), 'thread evidence hash mismatch: ' + name)
        effective = record.get('effective_thread_limit')
        if record.get('status') == 'configured':
            require(type(effective) is int and effective >= m['threads'], 'effective thread limit below request: ' + name)
        else:
            require(record.get('status') == 'unsupported' and isinstance(record.get('reason'), str) and
                    record['reason'].strip() and (effective is None or type(effective) is int and effective > 0),
                    'unsupported threading needs explicit reason and tool evidence: ' + name)
            limitations.append(name + ': ' + record['reason'])
    return limitations


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def timing_checks(reports, m):
    timing = file_at(reports, 'timing.rpt').read_text()
    require('All user specified timing constraints are met.' in timing, 'full timing PASS marker missing')
    rows = re.findall(r'(?m)^[ \t]*((?:-?\d+\.\d+[ \t]+){2}\d+[ \t]+\d+[ \t]+'
                      r'(?:-?\d+\.\d+[ \t]+){2}\d+[ \t]+\d+[ \t]+'
                      r'(?:-?\d+\.\d+[ \t]+){2}\d+[ \t]+\d+)[ \t]*$', timing)
    require(len(rows) == 1, 'unknown/ambiguous timing-summary format; adapt and test parser before release')
    n = [float(v) for v in rows[0].split()]
    require(all(n[i] >= 0 for i in (0, 4, 8)) and all(n[i] == 0 for i in (1, 2, 5, 6, 9, 10)),
            'setup/hold/pulse-width violation')
    coverage = file_at(reports, 'coverage.rpt').read_text()
    for key in COVERAGE:
        counts = re.findall(r'checking\s+' + key + r'\s+\((\d+)\)', coverage, re.I)
        require(counts == ['0'], 'missing/nonzero/ambiguous timing coverage: ' + key)
    if '_io_coverage_counts' in m:
        for key, expected in m['_io_coverage_counts'].items():
            counts = re.findall(r'checking\s+' + key + r'\s+\((\d+)\)', coverage, re.I)
            require(counts == [str(expected)], 'I/O coverage differs from exact audited endpoint scope: ' + key)
    route = file_at(reports, 'route.rpt').read_text()
    counts = []
    for key in ('routable nets', 'fully routed nets', 'nets with routing errors'):
        found = re.findall(r'# of ' + key + r'\.+\s*:\s*(\d+)\b', route)
        require(len(found) == 1, 'unknown/ambiguous route report: ' + key)
        counts.append(int(found[0]))
    require(counts[0] > 0 and counts[0] == counts[1] and counts[2] == 0, 'incomplete/invalid routing')
    skew = file_at(reports, 'bus_skew.rpt').read_text()
    slacks = re.findall(r'Slack\s+\((MET|VIOLATED)\)\s*:\s*(-?[\d.]+)ns', skew)
    require(len(slacks) == m['signoff']['bus_skew_checks'] and
            all(state == 'MET' and float(value) >= 0 for state, value in slacks),
            'bus-skew violation or missing coverage')
    return {'setup_ns': n[0], 'hold_ns': n[4], 'pulse_ns': n[8], 'routed_nets': counts[0],
            'bus_skew_checks': len(slacks)}


def signoff(manifest, reports, dcp, expected_dcp_hash):
    root, m, profile = preflight(manifest, windows=True)
    require(m['configuration'].get('clock_profile') != 'boot50-dynamic',
            'dynamic native DRP/CDC/RDC and CPU300/fabric250 scenarios are not qualified; no bitstream')
    reports, dcp = Path(reports).absolute(), Path(dcp).absolute()
    no_links(reports); no_links(dcp)
    require(reports == root / 'local-run' / 'signoff' and dcp == root / 'local-run' / 'implementation' / 'routed.dcp',
            'only this fresh run/final checkpoint may be signed off')
    limitations = []
    for phase in STAGES:
        limitations += check_stage(root, m, profile, phase, root / 'local-run' / phase)
    require(sha(dcp) == expected_dcp_hash, 'final DCP changed after implementation')
    for name in REPORTS:
        file_at(reports, name)
    facts = read(reports / 'facts.json')
    c = m['configuration']
    require(facts.get('profile_sha256') == profile and facts.get('part', '').lower() == c['part'] and
            facts.get('top') == c['top'] and facts.get('dcp_sha256') == expected_dcp_hash and
            facts.get('critical_drc') == 0 and type(facts.get('critical_drc')) is int and
            facts.get('blackboxes') == 0 and type(facts.get('blackboxes')) is int and
            facts.get('requested_threads') == m['threads'] and facts.get('effective_thread_limit') >= m['threads'],
            'final checkpoint/DRC/blackbox/thread facts mismatch')
    require(set(facts.get('domains', {})) == set(CLOCKS), 'domain timing evidence missing')
    for name in CLOCKS:
        row = facts['domains'][name]
        require(all(finite(row.get(k)) for k in ('period_ns', 'setup_ns', 'hold_ns')) and
                abs(row['period_ns'] - 1e9 / c['clocks_hz'][name]) <= 0.002 and
                row['setup_ns'] >= 0 and row['hold_ns'] >= 0, 'domain frequency/timing mismatch: ' + name)
    audit = read(reports / 'board-audit.json')
    require(audit.get('status') == 'PASS' and audit.get('profile_sha256') == profile and
            audit.get('dcp_sha256') == expected_dcp_hash and audit.get('unreviewed_critical_cdc') == 0 and type(audit.get('unreviewed_critical_cdc')) is int and
            isinstance(audit.get('cdc_review_scope'), str) and audit['cdc_review_scope'].strip() and
            audit.get('checks') == {'rom_content_and_mapping': 'PASS', 'reset_cdc': 'PASS', 'cpu_selection': 'PASS'},
            'same-checkpoint ROM/reset/CDC/CPU audit missing or incomplete')
    checked = m
    audit_hashes = {}
    if 'producer' in m:
        scope = read(file_at(root / 'local-run' / 'implementation', 'bus-skew-scope.json'))
        require(scope.get('profile_sha256') == profile and scope.get('phase') == 'implementation' and
                isinstance(scope.get('scopes'), list) and scope['scopes'], 'missing mapped bus-skew scope')
        require(len({digest(row) for row in scope['scopes']}) == len(scope['scopes']), 'duplicate mapped skew scopes')
        for row in scope['scopes']:
            require(finite(row.get('budget_ns')) and 0 < row['budget_ns'] <= 8 and
                    all(isinstance(row.get(k), list) and row[k] and all(isinstance(p, str) and p for p in row[k]) for k in ('from', 'to')),
                    'invalid actual bus-skew endpoint scope')
        audit_hashes = {name: sha(file_at(reports, name)) for name in BOARD_REPORTS}
        io_counts = {}
        io_report = (reports / 'io-coverage.rpt').read_text()
        for key in IO_COVERAGE:
            counts = re.findall(r'checking\s+' + key + r'\s+\((\d+)\)', io_report, re.I)
            require(len(counts) == 1, 'unknown actual I/O coverage report: ' + key)
            io_counts[key] = int(counts[0])
            require(not key.startswith('partial_') or io_counts[key] == 0, 'partial I/O delays forbidden')
        checked = {**m, '_io_coverage_counts': io_counts,
                   'signoff': {**m['signoff'], 'bus_skew_checks': len(scope['scopes'])}}
    metrics = timing_checks(reports, checked)
    media_hashes = {}
    if 'producer' in m:
        for rate in (10, 100, 1000):
            directory = reports / ('media-' + str(rate))
            meta = read(file_at(directory, 'scenario.json'))
            require(meta.get('rate_mbps') == rate and meta.get('profile_sha256') == profile and
                    meta.get('dcp_sha256') == expected_dcp_hash and meta.get('critical_drc') == 0 and
                    type(meta.get('critical_drc')) is int and
                    meta.get('periods_ns') == dict.fromkeys(('phy_rx', 'phy_rx_launch', 'phy_tx_capture'), {1000: 8.0, 100: 40.0, 10: 400.0}[rate]) and
                    all(meta.get(k) == v for k, v in {'rx_min_ns': -1.050, 'rx_max_ns': 1.050, 'tx_min_ns': -1.250, 'tx_max_ns': 1.250}.items()),
                    'missing/mismatched complete three-speed same-DCP media scenario')
            timing_checks(directory, checked)
            for name in ('timing.rpt', 'coverage.rpt', 'route.rpt', 'bus_skew.rpt', 'drc.rpt', 'scenario.json'):
                media_hashes[f'media-{rate}/{name}'] = sha(file_at(directory, name))
    result = dict(schema=SCHEMA, status='PASS_REPORT_CONTRACT', profile_sha256=profile,
                  dcp_sha256=expected_dcp_hash, reports_sha256={**{p: sha(reports / p) for p in REPORTS}, **media_hashes, **audit_hashes},
                  threading_limitations=limitations, board_tested=False, full_cdc_signoff=False, **metrics)
    (reports / 'signoff-result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def tcl(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('[', '\\[').replace(']', '\\]').replace('\n', '\\n').replace('\r', '\\r') + '"'


def prepare(manifest):
    root, m, profile = preflight(manifest, windows=True)
    run = output_at(root, 'local-run')
    require(not run.exists(), 'fresh local-run required; preserve earlier evidence')
    run.mkdir()
    pairs = dict(root=str(root), manifest=str(Path(manifest).absolute()), threads=m['threads'],
                 profile_sha256=profile, top=m['configuration']['top'], part=m['configuration']['part'],
                 audit_script=str(root / m['roles']['board_audit_script']))
    for phase in STAGES:
        pairs['script_' + phase] = str(root / m['stages'][phase]['script'])
    for name in CLOCKS:
        pairs['hz_' + name] = m['configuration']['clocks_hz'][name]
        pairs['pin_' + name] = m['signoff']['clock_pins'][name]
    if 'producer' in m:
        for name in ('rtl_filelist', 'simulation_filelist', 'post_synth_constraints', 'post_opt_constraints', 'media_scenarios', 'rom_coe'):
            pairs[name] = str(root / m['roles'][name])
        pairs['mig_xci'] = str(root / m['roles']['ip'][0])
        pairs['cpu'] = m['configuration']['cpu']
        pairs['clock_profile'] = m['configuration'].get('clock_profile', 'production')
        pairs['control_lemma'] = 1
        pairs['simulation_suite'] = m['producer']['simulation_suite']
        pairs['rom'] = str(root / m['roles']['rom'])
        pairs['constraints'] = ' '.join(tcl(str(root / p)) for p in m['roles']['constraints'])
    config = '\n'.join('set valence(' + k + ') ' + tcl(v) for k, v in pairs.items()) + '\n'
    (run / 'config.tcl').write_text(config)
    (run / 'manifest-sha256.txt').write_text(sha(manifest) + '\n')
    (run / 'config-sha256.txt').write_text(sha(run / 'config.tcl') + '\n')
    return {'status': 'INPUTS_VERIFIED_NOT_PHYSICALLY_QUALIFIED', 'profile_sha256': profile}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('check', 'prepare', 'stage', 'signoff'))
    p.add_argument('--manifest', required=True, type=Path)
    p.add_argument('--windows', action='store_true')
    p.add_argument('--phase', choices=STAGES)
    p.add_argument('--reports', type=Path)
    p.add_argument('--dcp', type=Path)
    p.add_argument('--dcp-sha256')
    a = p.parse_args()
    if a.action == 'prepare':
        result = prepare(a.manifest)
    elif a.action == 'signoff':
        result = signoff(a.manifest, a.reports, a.dcp, a.dcp_sha256)
    else:
        root, m, profile = preflight(a.manifest, windows=a.windows)
        if a.action == 'stage':
            result = {'status': 'PASS_STAGE_CONTRACT', 'threading_limitations':
                      check_stage(root, m, profile, a.phase, root / 'local-run' / a.phase)}
        else:
            result = {'status': 'INPUTS_VERIFIED_NOT_PHYSICALLY_QUALIFIED', 'profile_sha256': profile}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        print('COMMON_HANDOFF_BLOCKED: ' + str(error), file=sys.stderr)
        sys.exit(1)
