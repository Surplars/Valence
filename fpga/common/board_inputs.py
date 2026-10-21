"""Closed public board dependency list and emitted-port checks (no FPGA tools)."""
import re
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


def selected_shell(wrapper, low):
    # Only this reviewed switch is accepted. Do not ignore arbitrary preprocessor logic.
    pattern = r'`(ifdef|ifndef) VALENCE_INDEPENDENT_FIXED_DOMAINS\n(.*?)`endif'
    return re.sub(pattern, lambda m: m[2] if (m[1] == 'ifdef') == low else '', wrapper, flags=re.S)


def port_check(rtl, wrapper, production=True, low=False):
    wrapper = selected_shell(wrapper, low)
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


def emission(root, m):
    path = m['roles'].get('emission_profile')
    gate.require(path in m['inputs'], 'missing frozen production emission profile')
    meta = gate.read(gate.file_at(root, path)); c = m['configuration']; clocks = c['clocks_hz']
    for key, value in dict(top='CommonMachinePlatform', cpu=c['cpu'], abi=1, romBytes=131072,
                           programmableRom=False, vivadoMemories=True, hardwareClocks=True,
                           independentCpuFabricClocks=True, triSpeedEthernet=True, triSpeedTxFrameSlots=2,
                           jtagDmiAddressBits=7, fifoDepth=16, heldFifo='HeldResponseCdcDataFifo',
                           cpuClockHz=clocks['cpu'], fabricClockHz=clocks['fabric'], ddrUiHz=clocks['ddr_ui'],
                           uartHz=clocks['uart'], aonHz=clocks['aon'], physicalTimingVerified=False, boardVerified=False).items():
        gate.require(meta.get(key) == value and type(meta.get(key)) is type(value), 'wrong production emission contract: ' + key)
    gate.require(str(meta.get('timebaseHz')) == str(clocks['timebase']), 'wrong emission timebase')
    profile = c.get('clock_profile', 'production')
    if profile in ('boot50-static', 'performance300-static'):
        gate.require(meta.get('clockProfile') == profile and meta.get('independentFixedDomains') is True
                     and meta.get('runtimeClockReconfiguration') is False, 'missing static independent-domain emission contract')
    if profile == 'performance300-static':
        gate.require(meta.get('clockTopology') == 'independent-fixed-v1' and
                     meta.get('clockProfilePurpose') == 'high-frequency-timing-target',
                     'missing performance independent topology contract')
    source_hashes = {}
    for absolute, value in meta.get('sources', {}).items():
        for marker in ('src/main/scala/', 'src/test/scala/platform/'):
            if ('/' + marker) in absolute:
                name = marker + absolute.split('/' + marker, 1)[1]
                gate.require(m['inputs'].get(name) == value, 'stale emitted source: ' + name)
                source_hashes[name] = value
    wanted = {name for name in m['inputs'] if name.startswith(('src/main/scala/', 'src/test/scala/platform/')) and name.endswith('.scala')}
    gate.require(set(source_hashes) == wanted, 'emission source closure incomplete')
    top = [name for name in meta.get('artifacts', {}) if name.endswith('/CommonMachinePlatform.sv')]
    gate.require(len(top) == 1, 'unique emitted common top required')
    prefix = top[0][:-len('CommonMachinePlatform.sv')]
    base = gate.relative(path).parent
    for absolute, value in meta['artifacts'].items():
        gate.require(absolute.startswith(prefix), 'emission artifact escaped output directory')
        relative = (base / absolute[len(prefix):]).as_posix()
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
                                         '84524a8872a1cb859919fe5d24b34320b78e79ffb3cbb3ada5842e81a3653691')}
    for name, expected in admitted.items():
        gate.require(m['inputs'].get((base / name).as_posix()) in expected, 'unreviewed common MAC control equality form: ' + name)
    gate.require(m['inputs'].get('fpga/zu15eg/native_rgmii_trispeed_quarter.sv') ==
                 '32b96761f2019806b6e03d9d885595449d2b057a30b6bb9ca204a34162ce96fc', 'unreviewed common MAC pad source')
    for reset in (0, 1):
        for phase in (0, 1):
            for source in (0, 1):
                for prior in (0, 1):
                    low = 0 if reset else prior if phase else source
                    high = 0 if reset else prior if phase else source
                    gate.require(low == high, 'common control reset/phase induction failed')
    return port_check(gate.file_at(root, (base / 'CommonMachinePlatform.sv').as_posix()).read_text(),
                      gate.file_at(root, 'fpga/common/soc_top_common_ddr.sv').read_text(), low=profile in ('boot50-static', 'performance300-static'))
