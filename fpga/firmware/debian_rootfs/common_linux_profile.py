"""CommonMachinePlatform software profiles, not hardware qualification.

One UP RV64GC kernel/rootfs, explicit I1/A1 DT boot identities. No automatic
frequency changes; the boot clock is 50MHz and reference time stays 250MHz.
"""
import re
import codecs

PROFILE = 'common-boot50'
CPUS = ('i1', 'a1')
CONTRACT = dict(platform=PROFILE, cpu_profiles=list(CPUS), cpu_hz=50000000,
                fabric_hz=50000000, timebase_hz=250000000, ddr_ui_hz=250000000,
                uart_reference_hz=7372800, uart_baud=460800,
                memory_bytes=0x80000000, isa='rv64imafdc_zicsr_zifencei_svade',
                abi='lp64d', smp=False, automatic_frequency_change=False,
                linux_board_verified={'i1': False, 'a1': False})


def check_record(record):
    if record.get('common_platform') != CONTRACT:
        raise RuntimeError('Common kernel profile missing or drifted; prepare a new kernel stage')


def device_tree(net, cpu, bootargs, console='sbi'):
    if cpu not in CPUS:
        raise RuntimeError('Unknown CommonMachinePlatform CPU')
    text = net.network_dts(0x80000000, platform_drivers=True,
                           bootargs=bootargs, console_profile=console)
    replacements = {
        'timebase-frequency = <100000000>;': 'timebase-frequency = <250000000>;',
        'clock-frequency = <100000000>;': 'clock-frequency = <50000000>;',
        'riscv,isa = "rv64imafdc_zicsr_zifencei";':
            'riscv,isa = "rv64imafdc_zicsr_zifencei_svade";',
        '"zifencei";': '"zifencei", "svade";',
        'model = "OpenIon Valence VL100 / Orbital-A1 / rv64gc 100MHz";':
            f'model = "Valence CommonMachinePlatform / {cpu.upper()} / boot50";',
        'compatible = "openion,orbital-a1", "riscv";':
            f'compatible = "openion,{"valence-i1" if cpu == "i1" else "orbital-a1"}", "riscv";',
    }
    for old, new in replacements.items():
        if text.count(old) != 1:
            raise RuntimeError('Common DT template drift: ' + old)
        text = text.replace(old, new)
    # Nonoverlapping MMIO ownership: legacy leaf-gate CMU and new read-only monitor.
    old = 'reg = <0x0 0x10080000 0x0 0x1000>;'
    if text.count(old) != 1:
        raise RuntimeError('CMU resource template drift')
    text = text.replace(old, 'reg = <0x0 0x10080000 0x0 0x800>;')
    text = text.replace('        cmu0: clock-controller@10080000 {', '''        clockmon0: clock-monitor@10080800 {
            compatible = "openion,valence-clock-monitor-v1";
            #clock-cells = <1>;
            reg = <0x0 0x10080800 0x0 0x100>, <0x0 0x10080900 0x0 0x200>;
            reg-names = "rate", "perf";
            status = "okay";
        };
        cmu0: clock-controller@10080000 {''')
    if cpu == 'i1':
        text = text.replace('compatible = \"openion,valence-cmu-v1\";',
                            'compatible = \"openion,valence-cmu-v1\";\n            clocks = <&clockmon0 0>;\n            clock-names = \"cpu-rate\";')
    if cpu == 'a1':
        # Current A1 hardware does not elaborate runtimeRateControl/perf.
        text = text.replace('reg-names = "rate", "perf";\n            status = "okay";',
                            'reg-names = "rate", "perf";\n            status = "disabled";')
    validate(text, cpu)
    return text


def validate(text, cpu):
    if cpu not in CPUS:
        raise RuntimeError('Unknown CPU profile')
    # DTS and dtc-decoded cells may be decimal or hexadecimal.
    def prop(body, name):
        match = re.search(r'\b' + re.escape(name) + r'\s*=\s*<([^>]+)>;', body)
        if match:
            return [int(v, 0) for v in match[1].split()]
        # dtc may choose string syntax for numeric cells whose bytes happen to
        # be NUL-terminated ASCII (460800 becomes "", "\\a\\b").
        match = re.search(r'\b' + re.escape(name) + r'\s*=\s*([^;]+);', body)
        if match:
            chunks = re.findall(r'"([^"\n]*)"', match[1])
            raw = b''.join(codecs.decode(v, 'unicode_escape').encode('latin1') + b'\0' for v in chunks)
            if raw and len(raw) % 4 == 0:
                return [int.from_bytes(raw[i:i+4], 'big') for i in range(0,len(raw),4)]
        return []
    def node(name):
        match = re.search(r'\b' + re.escape(name) + r'\s*\{', text)
        if not match:
            raise RuntimeError('Missing common DT node: ' + name)
        start = match.end()
        depth = 1
        for pos in range(start, len(text)):
            depth += (text[pos] == '{') - (text[pos] == '}')
            if depth == 0:
                return text[start:pos]
        raise RuntimeError('Unclosed common DT node: ' + name)
    if prop(text, 'timebase-frequency') != [250000000]:
        raise RuntimeError('Common reference clock must be250MHz')
    if prop(node('cpu@0'), 'clock-frequency') != [50000000]:
        raise RuntimeError('Common CPU must boot50MHz')
    identity = 'openion,valence-i1' if cpu == 'i1' else 'openion,orbital-a1'
    if identity not in node('cpu@0') or 'svade' not in node('cpu@0'):
        raise RuntimeError('CPU identity/ISA mismatch')
    uart = node('serial@10000000')
    if prop(uart, 'clock-frequency') != [7372800] or prop(uart, 'current-speed') != [460800]:
        raise RuntimeError('UART fixed reference mismatch')
    if prop(node('memory@80200000'), 'reg') != [0, 0x80200000, 0, 0x80000000]:
        raise RuntimeError('Common DDR must be2GiB')
    for name, start, size in [('diagnostics@fff78000',0xfff78000,0x80000),
                               ('monitor@ffff8000',0xffff8000,0x4000)]:
        body=node(name)
        if prop(body,'reg') != [0,start,0,size] or 'no-map;' not in body:
            raise RuntimeError('Common BootROM reservation mismatch')
    for name, expected in (
        ('clock-controller@10080000', [0,0x10080000,0,0x800]),
        ('clock-monitor@10080800', [0,0x10080800,0,0x100,0,0x10080900,0,0x200]),
        ('dma-controller@10001000', [0,0x10001000,0,0x1000]),
        ('ethernet@10040000', [0,0x10040000,0,0x1000,0,0x10002000,0,0x100]),
        ('interrupt-controller@c000000', [0,0xc000000,0,0x4000,0,0xc004000,0,0x4000]),
        ('timer@200bff8', [0,0x200bff8,0,8,0,0x2004000,0,8])):
        # Multiple register tuples are flattened by dtc; parse all groups.
        body=node(name)
        match=re.search(r'\breg\s*=\s*([^;]+);',body)
        actual=[int(v,0) for group in re.findall(r'<([^>]+)>',match[1]) for v in group.split()] if match else []
        if actual != expected:
            raise RuntimeError('Common MMIO extent mismatch: '+name)
    if '"riscv,imsics"' in text or 'riscv,aclint-mswi' in text:
        raise RuntimeError('No standard IMSIC MMIO or MSWI exists')
    aia=node('interrupt-controller@c000000')
    ph=prop(aia,'phandle')
    for name,irq in [('dma-controller@10001000',4),('ethernet@10040000',6)]:
        body=node(name)
        match=re.search(r'interrupts-extended\s*=\s*<([^>]+)>;',body)
        values=match[1].split() if match else []
        if len(values)!=3 or [int(v,0) for v in values[1:]] != [irq,4] or not (
            values[0]=='&valence_aia' or (ph and int(values[0],0)==ph[0])):
            raise RuntimeError('Common IRQ mapping mismatch: '+name)
    monitor = node('clock-monitor@10080800')
    expected_status = 'okay' if cpu == 'i1' else 'disabled'
    if not re.search(r'\bstatus\s*=\s*"' + expected_status + r'";', monitor):
        raise RuntimeError('Clock monitor must match actual CPU platform capability')
    cmu = node('clock-controller@10080000')
    if ('"cpu-rate"' in cmu) != (cpu == 'i1'):
        raise RuntimeError('Only I1 may reference dynamic CPU clock provider')
