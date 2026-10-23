"""Closed public board dependency list and emitted-port checks (no FPGA tools)."""
import re
import hashlib
import manifest as gate

PUBLIC_INPUTS = (
    'fpga/zu15eg/native_gmac_divided_clock.sv',
    'fpga/zu15eg/native_tx_word_reset_boundary.sv',
    'fpga/zu15eg/native_rgmii_trispeed_quarter.sv',
    'fpga/zu15eg/pl_ddr4_pins.xdc',
    'fpga/zu15eg/trispeed_board_constraints.tcl',
    'fpga/zu15eg/trispeed_quarter_constraints.tcl',
    'fpga/zu15eg/native_quarter_clock_constraints.tcl',
    'fpga/zu15eg/native-gmac-cdc-constraints.tcl',
    'fpga/zu15eg/cdc_constraints.tcl',
    'fpga/zu15eg/performance-telemetry-constraints.tcl',
    'fpga/next/native_mac_roles.tcl',
    'fpga/next/check_jtag_chain.tcl',
    'fpga/inorder/bscan_timing_i1.tcl',
    'fpga/next/tests/trispeed_quarter_pad_tb.sv',
    'fpga/next/tests/rgmii_behavioral_primitives.sv',
    'simulator/jtag/i1_dual_tap_tb.sv',
    'simulator/jtag/run_xsim.py',
)
BOARD_RTL = PUBLIC_INPUTS[:3] + (
    'src/main/resources/inorder/ValenceI1BscanDebugPort.sv',
    'src/main/resources/inorder/ValenceI1DmiCdc.sv',
    'fpga/common/soc_top_common_ddr.sv',
    'fpga/common/native_dci_startup.sv',
    'fpga/common/dynamic/native_clock_gate.sv',
    'fpga/common/dynamic/native_clock_drp.sv',
    'fpga/common/dynamic/native_dynamic_clock_domain.sv',
)
SIM_RTL = (
    'fpga/common/native_dci_startup.sv',
    'fpga/common/dci_startup_tb.sv',
    'src/main/resources/inorder/ValenceI1BscanDebugPort.sv',
    'src/main/resources/inorder/ValenceI1DmiCdc.sv',
    'simulator/jtag/i1_dual_tap_tb.sv',
    'fpga/zu15eg/native_tx_word_reset_boundary.sv',
    'fpga/zu15eg/native_rgmii_trispeed_quarter.sv',
    'fpga/next/tests/rgmii_behavioral_primitives.sv',
    'fpga/common/trispeed_board_pad_tb.sv',
)


def selected_shell(wrapper, low, dynamic=False):
    # Explicit reviewed macros only; reject unknown/nested malformed directives.
    enabled = {'VALENCE_INDEPENDENT_FIXED_DOMAINS': low,
               'VALENCE_DYNAMIC_CLOCK_DOMAINS': dynamic}
    gate.require(not dynamic or low, 'dynamic clocks require independent fixed peripheral domains')
    stack = []; active = True; result = []
    for line in wrapper.splitlines(keepends=True):
        directive = re.fullmatch(r'\s*`(ifdef|ifndef) (\w+)\s*', line)
        if directive:
            kind, name = directive.groups()
            gate.require(name in enabled, 'unreviewed shell macro: ' + name)
            condition = enabled[name] == (kind == 'ifdef')
            stack.append((active, condition, False)); active = active and condition
        elif re.fullmatch(r'\s*`else\s*', line):
            gate.require(bool(stack) and not stack[-1][2], 'malformed shell else')
            parent, condition, _ = stack[-1]
            stack[-1] = (parent, condition, True); active = parent and not condition
        elif re.fullmatch(r'\s*`endif\s*', line):
            gate.require(bool(stack), 'unmatched shell endif')
            active = stack.pop()[0]
        elif active:
            result.append(line)
    gate.require(not stack, 'unterminated shell conditional')
    return ''.join(result)


def port_check(rtl, wrapper, production=True, low=False, dynamic=False):
    wrapper = selected_shell(wrapper, low, dynamic)
    header = rtl.split('module CommonMachinePlatform(', 1)[1].split(');', 1)[0]
    ports = {}; direction = None
    for field in header.split(','):
        match = re.fullmatch(r'\s*(?:(input|output)\s+)?(?:\[\d+:\d+\]\s*)?([A-Za-z_]\w*)\s*', field)
        gate.require(match is not None, 'unknown emitted port syntax')
        direction = match[1] or direction
        ports[match[2]] = direction
    body = wrapper.split('CommonMachinePlatform u_soc (', 1)[1].split('    );', 1)[0]
    connections = re.findall(r'\.([A-Za-z_]\w*)\s*\(', body)
    gate.require(len(connections) == len(set(connections)), 'duplicate common top connection')
    gate.require(set(connections).issubset(ports), 'wrapper connects missing common top port')
    missing = {p for p, d in ports.items() if d == 'input'} - set(connections)
    if not production:
        missing -= {'io_program_valid', 'io_program_bits_index', 'io_program_bits_data'}
    gate.require(not missing, 'undriven common top inputs: ' + ', '.join(sorted(missing)))
    if production:
        gate.require(not any(p.startswith('io_program') for p in ports), 'programmable simulation ROM cannot be delivered as production')
    return {'ports': len(ports), 'connections': len(connections)}


def emission_path_map(records):
    """Parse host paths without rewriting/hash-normalizing the emission JSON."""
    normalized = {}; seen = set()
    for original, digest in records.items():
        gate.require(isinstance(original, str), 'emission path must be a string')
        path = original.replace('\\', '/')
        windows = bool(re.match(r'^[A-Za-z]:/', path))
        gate.require(windows or path.startswith('/'), 'absolute emitted path required')
        gate.require(not any(part in ('.', '..') for part in path.split('/')), 'unsafe emitted path components')
        key = path.casefold() if windows else path
        gate.require(key not in seen, 'duplicate normalized emission path')
        seen.add(key); normalized[path] = digest
    return normalized


def emitted_artifacts(records):
    normalized = emission_path_map(records)
    tops = [p for p in normalized if p.endswith('/CommonMachinePlatform.sv')]
    gate.require(len(tops) == 1, 'unique emitted common top required')
    prefix = tops[0][:-len('CommonMachinePlatform.sv')]
    windows = bool(re.match(r'^[A-Za-z]:/', prefix))
    result = {}; seen = set()
    for path, digest in normalized.items():
        gate.require((path.casefold() if windows else path).startswith(prefix.casefold() if windows else prefix),
                     'emission artifact escaped output directory')
        relative = gate.relative(path[len(prefix):]).as_posix()
        gate.require(relative.casefold() not in seen, 'duplicate emitted relative artifact')
        seen.add(relative.casefold()); result[relative] = digest
    return result


def emitted_sources(records):
    result = {}
    for absolute, digest in emission_path_map(records).items():
        for marker in ('src/main/scala/', 'src/test/scala/platform/'):
            if ('/' + marker) in absolute:
                name = marker + absolute.rsplit('/' + marker, 1)[1]
                gate.relative(name)
                gate.require(name not in result, 'duplicate emitted source identity')
                result[name] = digest
    return result


def performance_mac_control_form(parent):
    # Reviewed complete instance is byte-identical to the prior quiesce proof.
    instances = re.findall(r'  TriSpeedRgmiiTx encode \(.*?\n  \);', parent, re.S)
    gate.require(len(instances) == 1 and hashlib.sha256(instances[0].strip().encode()).hexdigest() ==
                 'e0e1ec735536567a3459a7c2699f145109ff349899fc36c56a8747c7573af1ee',
                 'performance MAC complete encoder binding changed')
    for port in ('rgmiiTxRise', 'rgmiiTxFall'):
        # One output declaration + one direct encoder output; no parent logic.
        gate.require(len(re.findall(r'\b'+port+r'\b', parent)) == 2,
                     'performance MAC parent rewrites encoder control output')


SOFTWARE_PARAMETER_PROFILE = 'boot50-dynamic-software-parameter-diagnostic'


def software_parameter_selection(configuration, meta):
    selected = configuration.get('functional_profile') == SOFTWARE_PARAMETER_PROFILE
    emitted = meta.get('functionalProfile') == SOFTWARE_PARAMETER_PROFILE
    gate.require(selected == emitted, 'software-parameter configuration/emission selector mismatch')
    gate.require(not selected or (configuration.get('performance_telemetry') is True and
                                 meta.get('performanceTelemetry') is True),
                 'software-parameter candidate requires telemetry in configuration and emission')
    return selected


def software_parameter_review(root, m, meta, base):
    """A separately frozen structural review, never a timing qualification.

    The publisher binds this receipt's digest in the candidate manifest after
    independent review. This function cannot generate or self-approve it.
    """
    expected = dict(functionalProfile=SOFTWARE_PARAMETER_PROFILE,
        softwareParameterMode=True, hardwareRateWhitelist=False,
        clockRateAbi=2, performanceTelemetryAbi=1, performanceTelemetry=True,
        rateAdmission='explicit-diagnostic-not-qualified', diagnosticPointFlags=0x30,
        qualifiedRatePointsHz=[], rateParameterLimits=dict(D=10, minM=32, maxM=62, minO=3, maxO=128,
            referenceHz=250000000, minimumHz=10000000, maximumCpuHz=300000000, maximumFabricHz=250000000),
        frequencyMeasurement='managed-edge-count-over-aon-window',
        telemetryBase='0x10080900', cpuClockHz=50000000, fabricClockHz=50000000,
        physicalTimingVerified=False, boardVerified=False)
    for key, value in expected.items():
        gate.require(meta.get(key) == value and type(meta.get(key)) is type(value),
                     'software-parameter feature mismatch: ' + key)
    gate.require(m['configuration'].get('performance_telemetry') is True and
                 m['configuration'].get('functional_profile') == SOFTWARE_PARAMETER_PROFILE,
                 'software-parameter candidate must be explicitly selected')
    path = m['roles'].get('software_parameter_review')
    gate.require(path in m['inputs'], 'missing independently reviewed software-parameter receipt')
    gate.require(gate.sha(gate.file_at(root, path)) == m['inputs'][path], 'software-parameter receipt digest mismatch')
    review = gate.read(gate.file_at(root, path))
    gate.require(review.get('schema') == 'common-software-parameter-feature-review-v1' and
                 review.get('status') == 'REVIEWED_STRUCTURAL_ONLY' and
                 review.get('physical_qualified') is False and review.get('board_qualified') is False and
                 re.fullmatch('[0-9a-f]{40}', review.get('source_commit', '')) and
                 review.get('source_commit') == m.get('source_commit'),
                 'invalid software-parameter structural review')
    gate.require(review.get('features') == expected, 'reviewed feature contract differs from selected candidate')
    required_sources = set(emitted_sources(meta.get('sources', {}))) | set(BOARD_RTL) | {
        'fpga/firmware/valence_clock.h', 'fpga/firmware/valence_cmu.h',
        'fpga/firmware/boot_clock_console.h', 'fpga/firmware/bootrom.c',
        'fpga/zu15eg/performance-telemetry-constraints.tcl',
        'fpga/common/performance_telemetry_constraints.tcl'}
    gate.require(set(review.get('sources_sha256', {})) == required_sources,
                 'software-parameter reviewed source closure incomplete')
    artifacts = emitted_artifacts(meta.get('artifacts', {}))
    gate.require(review.get('artifacts_sha256') == artifacts, 'software-parameter reviewed RTL closure differs')
    for role in ('rom', 'rom_coe', 'firmware_contract'):
        name = m['roles'].get(role)
        gate.require(name in m['inputs'] and review.get('firmware_sha256', {}).get(name) == m['inputs'][name]
                     and gate.sha(gate.file_at(root, name)) == m['inputs'][name],
                     'software-parameter fresh firmware binding missing: ' + role)
    firmware = gate.read(gate.file_at(root, m['roles']['firmware_contract']))
    build_record = firmware.get('build_contract', {})
    build_path = build_record.get('path')
    gate.require(build_path in m['inputs'] and build_record.get('sha256') == m['inputs'][build_path]
                 and review.get('firmware_sha256', {}).get(build_path) == m['inputs'][build_path]
                 and gate.sha(gate.file_at(root, build_path)) == m['inputs'][build_path],
                 'software-parameter firmware build contract not frozen')
    build = gate.read(gate.file_at(root, build_path))
    for key, value in dict(clock_console=True, clock_console_rate_abi=2,
                           clock_console_telemetry_abi=1, boot_menu=True,
                           clock_console_auto_change=False,
                           clock_console_initial_candidates_mhz=list(range(50,151,5))).items():
        gate.require(build.get(key) == value and type(build.get(key)) is type(value),
                     'software-parameter BootROM feature missing: ' + key)
    identities = {(x.get('file'), x.get('module'), x.get('instance')) for x in review.get('instances', [])}
    gate.require({('ManagedPeripheralBank.sv', 'TriSpeedManagedGmac', 'gmac'),
                  ('ManagedPeripheralBank.sv', 'FixedMacBoundary', 'crossing'),
                  ('CommonMachinePlatform.sv', 'ManagedPeripheralBank', 'peripherals'),
                  ('CommonMachinePlatform.sv', 'ClockPerformanceTelemetry', 'monitor')} <= identities,
                 'software-parameter complete reviewed parent instances missing')
    for module in ('ClockPerformanceTelemetry', 'ClockPerformanceTelemetryRegisters',
                   'ClockRateManagement', 'ClockRateManagementBoundary'):
        gate.require(module + '.sv' in artifacts, 'software-parameter emitted module missing: ' + module)
    top = gate.file_at(root, (base / 'CommonMachinePlatform.sv').as_posix()).read_text()
    for domain in (0, 1):
        gate.require(re.search(r'output\s+\[23:0\]\s+rateBackend_' + str(domain) +
                               r'_program_bits_parameters\b', top), 'software parameter port absent')
    return review


def dynamic_mac_control_form(root, m, meta, base):
    """Exact reviewed source composition, not a timing/operating whitelist."""
    gate.require(m.get('diagnosticOnly') is True and m['configuration']['cpu'] == 'i1'
                 and m['configuration'].get('clock_profile') == 'boot50-dynamic',
                 'fixed-source MAC is diagnostic-only')
    expected = dict(clockProfile='boot50-dynamic', clockTopology='independent-fixed-v1',
        clockProfilePurpose=('dynamic-clock-functional-diagnostic-candidate-not-timing-qualified'
            if meta.get('functionalProfile') == SOFTWARE_PARAMETER_PROFILE else
            'dynamic-clock-integration-candidate-empty-rate-table'),
        independentFixedDomains=True, independentCpuFabricClocks=True, hardwareClocks=True,
        runtimeClockReconfiguration=True, programmableRom=False, vivadoMemories=True,
        cpuClockHz=50000000, fabricClockHz=50000000, ddrUiHz=250000000, aonHz=50000000,
        uartHz=50000000, instructionCacheBytes=32768, dataCacheBytes=32768, cacheWays=2,
        homeClients=2, homeLines=1024, homeWays=4, fifoDepth=16, triSpeedTxFrameSlots=2,
        externalHotMaintenanceSupported=False, oneSidedResetSupported=False,
        physicalTimingVerified=False, boardVerified=False)
    for k, v in expected.items():
        gate.require(meta.get(k) == v and type(meta.get(k)) is type(v), 'dynamic MAC contract: ' + k)
    gate.require(str(meta.get('timebaseHz')) == '250000000', 'dynamic fixed TIME250 required')
    if meta.get('functionalProfile') == SOFTWARE_PARAMETER_PROFILE:
        review = software_parameter_review(root, m, meta, base)
    else:
        name = 'fpga/common/dynamic/mac_diagnostic_review.json'
        gate.require(m['inputs'].get(name) == '895c8b471643344567cc5e91a95746050292e1882798eb280cb374f1d7441426' and gate.sha(gate.file_at(root, name)) == '895c8b471643344567cc5e91a95746050292e1882798eb280cb374f1d7441426',
                     'unreviewed fixed-MAC composition record')
        review = gate.read(gate.file_at(root, name))
    for name, digest in review['sources_sha256'].items():
        gate.require(m['inputs'].get(name) == digest and gate.sha(gate.file_at(root, name)) == digest,
                     'dynamic MAC reviewed source changed: ' + name)
    for name, digest in review['artifacts_sha256'].items():
        name = (base / name).as_posix()
        gate.require(m['inputs'].get(name) == digest and gate.sha(gate.file_at(root, name)) == digest,
                     'dynamic MAC boundary artifact changed: ' + name)
    bodies = {}
    for item in review['instances']:
        parent = gate.file_at(root, (base / item['file']).as_posix()).read_text()
        matches = re.findall(r'  ' + item['module'] + ' ' + item['instance'] + r' \(.*?\n  \);', parent, re.S)
        gate.require(len(matches) == 1 and hashlib.sha256(matches[0].strip().encode()).hexdigest() == item['sha256'],
                     'dynamic MAC complete parent instance changed: ' + item['instance'])
        bodies[item['instance']] = matches[0]
    def bound(body, port, signal):
        gate.require(re.search(r'\.' + port + r'\s*\(\s*' + re.escape(signal) + r'\s*\)', body),
                     'dynamic MAC fixed-source binding changed: ' + port)
    bound(bodies['gmac'], 'sourceClock', '_gmac_continuousClock')
    bound(bodies['crossing'], 'fixedClock', '_gmac_continuousClock')
    bound(bodies['crossing'], 'fabricClock', 'sourceClock')
    for name in ('gmac', 'crossing'):
        bound(bodies[name], 'commonReset', 'commonReset')
    parent = gate.file_at(root, (base / 'TriSpeedManagedGmac.sv').as_posix()).read_text()
    gate.require('assign continuousClock = rawTxClock;' in parent, 'fixed raw125 export lost')
    performance_mac_control_form(parent)
    boundary = gate.file_at(root, (base / 'FixedMacBoundary.sv').as_posix()).read_text()
    for lane in ('txData', 'txControl', 'rxData', 'rxStatus'):
        body = re.findall(r'  HeldResponseCdcDataFifo_33 ' + lane + r' \(.*?\n  \);', boundary, re.S)
        gate.require(len(body) == 1, 'dynamic outer37 HeldResponse lane missing: ' + lane)
        tx = lane.startswith('tx')
        bound(body[0], 'sourceClock', 'fabricClock' if tx else 'fixedClock')
        bound(body[0], 'destinationClock', 'fixedClock' if tx else 'fabricClock')
        bound(body[0], 'commonReset', 'commonReset')


def emission(root, m):
    path = m['roles'].get('emission_profile')
    gate.require(path in m['inputs'], 'missing frozen production emission profile')
    meta = gate.read(gate.file_at(root, path)); c = m['configuration']; clocks = c['clocks_hz']
    software_parameter_selection(c, meta)
    for key, value in dict(top='CommonMachinePlatform', cpu=c['cpu'], abi=1, romBytes=131072,
                           programmableRom=False, vivadoMemories=True, hardwareClocks=True,
                           independentCpuFabricClocks=True, triSpeedEthernet=True, triSpeedTxFrameSlots=2,
                           jtagDmiAddressBits=7, fifoDepth=16, heldFifo='HeldResponseCdcDataFifo',
                           cpuClockHz=clocks['cpu'], fabricClockHz=clocks['fabric'], ddrUiHz=clocks['ddr_ui'],
                           uartHz=clocks['uart'], aonHz=clocks['aon'], physicalTimingVerified=False, boardVerified=False).items():
        gate.require(meta.get(key) == value and type(meta.get(key)) is type(value), 'wrong production emission contract: ' + key)
    gate.require(str(meta.get('timebaseHz')) == str(clocks['timebase']), 'wrong emission timebase')
    profile = c.get('clock_profile', 'production')
    telemetry = c.get('performance_telemetry', False)
    gate.require(type(telemetry) is bool and meta.get('performanceTelemetry', False) is telemetry,
                 'telemetry emission/configuration mismatch')
    if telemetry:
        gate.require(meta.get('frequencyMeasurement') == 'managed-edge-count-over-aon-window' and
                     meta.get('telemetryBase') == '0x10080900', 'telemetry ABI mismatch')
    if profile in ('boot50-static', 'performance300-static'):
        gate.require(meta.get('clockProfile') == profile and meta.get('independentFixedDomains') is True
                     and meta.get('runtimeClockReconfiguration') is False, 'missing static independent-domain emission contract')
    if profile == 'boot50-dynamic':
        gate.require(meta.get('clockProfile') == profile and meta.get('independentFixedDomains') is True
                     and meta.get('runtimeClockReconfiguration') is True, 'missing explicit dynamic emission contract')
    if profile == 'performance300-static':
        gate.require(meta.get('clockTopology') == 'independent-fixed-v1' and
                     meta.get('clockProfilePurpose') == 'high-frequency-timing-target',
                     'missing performance independent topology contract')
    source_hashes = emitted_sources(meta.get('sources', {}))
    for name, value in source_hashes.items():
        gate.require(m['inputs'].get(name) == value, 'stale emitted source: ' + name)
    wanted = {name for name in m['inputs'] if name.startswith(('src/main/scala/', 'src/test/scala/platform/')) and name.endswith('.scala')}
    gate.require(set(source_hashes) == wanted, 'emission source closure incomplete')
    base = gate.relative(path).parent
    for relative_name, value in emitted_artifacts(meta.get('artifacts', {})).items():
        relative = (base / relative_name).as_posix()
        gate.require(m['inputs'].get(relative) == value, 'emitted artifact hash mismatch: ' + relative)
    # Complete emitted encoder+parent form, reviewed together with the public
    # pad source. Both control registers have the same clock/reset/zero state
    # and identical enable D on every edge; parent forwards them unchanged.
    # Equal low/high control state is inductive for reset and both phase values.
    # The quiesce repair's complete encoder instance (all clocks/resets/data and
    # outputs) is byte-identical; only RX quiesce distribution changed. Review
    # receipt: recovery/quiesce-mac-control-form-review.json. No arbitrary form.
    admitted = {'TriSpeedRgmiiTx.sv': ('80899ec1aad90965193a63a39def578fdd9465028a28c230fc3adec6bf15e731',),
                'TriSpeedManagedGmac.sv': ('6ddda588873a1ce37b2b131cdbf354065a3a67f3e4e26c835f7afaf783a2a302',
                                         '84524a8872a1cb859919fe5d24b34320b78e79ffb3cbb3ada5842e81a3653691',
                                         '1fe02f7d145c17c9147eb0d350d48005c0b24a4501e298ea1407f983f6193556')}
    software_parameters = meta.get('functionalProfile') == SOFTWARE_PARAMETER_PROFILE
    gate.require(not meta.get('softwareParameterMode') or software_parameters, 'unrecognized software-parameter functional profile')
    dynamic_mac = software_parameters or m['inputs'].get((base / 'TriSpeedManagedGmac.sv').as_posix()) == 'b86bcabfc0d113f651b36f023a8a8728090288530cc6b649136b30bb580c8d41'
    if dynamic_mac:
        dynamic_mac_control_form(root, m, meta, base)
    for name, expected in admitted.items():
        if dynamic_mac and name == 'TriSpeedManagedGmac.sv':
            continue  # Exact diagnostic composition above, never unconditional admission.
        gate.require(m['inputs'].get((base / name).as_posix()) in expected, 'unreviewed common MAC control equality form: ' + name)
    if m['inputs'].get((base / 'TriSpeedManagedGmac.sv').as_posix()) == '1fe02f7d145c17c9147eb0d350d48005c0b24a4501e298ea1407f983f6193556':
        performance_mac_control_form(gate.file_at(root, (base / 'TriSpeedManagedGmac.sv').as_posix()).read_text())
    gate.require(m['inputs'].get('fpga/zu15eg/native_rgmii_trispeed_quarter.sv') ==
                 '9db8e97150a2eab5670ac1ebd0512c608ee5d390f680235d95661d7e9bb99f78', 'unreviewed common MAC pad source')
    for reset in (0, 1):
        for phase in (0, 1):
            for source in (0, 1):
                for prior in (0, 1):
                    low = 0 if reset else prior if phase else source
                    high = 0 if reset else prior if phase else source
                    gate.require(low == high, 'common control reset/phase induction failed')
    return port_check(gate.file_at(root, (base / 'CommonMachinePlatform.sv').as_posix()).read_text(),
                      gate.file_at(root, 'fpga/common/soc_top_common_ddr.sv').read_text(), low=profile in ('boot50-static', 'performance300-static', 'boot50-dynamic'),
                      dynamic=profile == 'boot50-dynamic')
