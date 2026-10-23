#!/usr/bin/env python3
"""Independent, read-only CommonMachinePlatform Linux contract audit.

Input DTS may be source or dtc-decompiled DTB. Full delivery mode additionally
checks the actual uncompressed newc initramfs, kernel config and module bytes.
No result from this script is evidence of booting or exercising the board.
"""
import argparse
import codecs
import hashlib
import json
from pathlib import Path
import re
import struct

RAM_BASE, RAM_BYTES, RAM_END = 0x80200000, 0x80000000, 0x100200000
MODULES = ('valence_soc', 'valence_aia', 'valence_clockmon', 'valence_cmu',
           'valence_dma', 'valence_gmac')


def require(value, message):
    if not value:
        raise RuntimeError(message)


def clean(text):
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)


def node(text, name):
    found = list(re.finditer(r'(?<![\w@,-])' + re.escape(name) + r'\s*\{', text))
    require(len(found) == 1, 'missing/duplicate node: ' + name)
    start = found[0].end()
    depth = 1
    for i in range(start, len(text)):
        depth += (text[i] == '{') - (text[i] == '}')
        if not depth:
            return text[start:i]
    raise RuntimeError('unclosed node: ' + name)


def property_value(body, name):
    # Exclude child nodes: a CPU property must never be supplied by its intc.
    while re.search(r'[^;{}]+\{[^{}]*\}\s*;', body):
        body = re.sub(r'[^;{}]+\{[^{}]*\}\s*;', '', body)
    matches = re.findall(r'(?<![\w,#-])' + re.escape(name) + r'\s*=\s*([^;]+);', body)
    require(len(matches) == 1, 'missing/duplicate property: ' + name)
    return matches[0].strip()


def cells(body, name):
    value = property_value(body, name)
    groups = re.findall(r'<([^>]+)>', value)
    if groups:
        return [word if word.startswith('&') else int(word, 0)
                for group in groups for word in group.split()]
    # dtc heuristically prints numeric bytes as strings when they end in NUL.
    # current-speed 0x00070800 is commonly emitted as "", "\\a\\b".
    strings = re.findall(r'"((?:\\.|[^"\\])*)"', value)
    require(bool(strings), 'cell representation: ' + name)
    raw = b''.join(codecs.decode(v, 'unicode_escape').encode('latin1') + b'\0' for v in strings)
    require(len(raw) % 4 == 0, 'cell byte width: ' + name)
    return [int.from_bytes(raw[i:i+4], 'big') for i in range(0, len(raw), 4)]


def u64_property(body, name):
    values = cells(body, name)
    require(len(values) in (1, 2), '64-bit property shape: ' + name)
    return values[0] if len(values) == 1 else (values[0] << 32) | values[1]


def irq_ref(text, target, label):
    body = node(text, target)
    if re.search(r'\bphandle\s*=', body):
        return cells(body, 'phandle')[0]
    require(re.search(re.escape(label) + r'\s*:\s*' + re.escape(target) + r'\s*\{', text),
            'interrupt controller label missing')
    return '&' + label


def audit_dts(text, cpu, console='sbi'):
    text = clean(text)
    require(cpu in ('i1', 'a1'), 'unsupported CPU')
    require(console in ('sbi', 'uart-irq'), 'unsupported console')
    for forbidden in ('riscv,plic0', 'sifive,plic', 'riscv,imsics', 'riscv,clint0',
                      'riscv,aclint-mswi', 'riscv,aclint-sswi'):
        require(forbidden not in text, 'wrong interrupt/timer architecture: ' + forbidden)
    require(not re.search(r'\b(?:gpio|i2c|spi|mmc|sdhci|usb|pcie|nvme|rtc|watchdog)(?:[-\w]*)?@', text),
            'unimplemented peripheral node')
    require(cells(node(text, 'cpus'), 'timebase-frequency') == [250000000], 'TIME must be fixed250MHz')
    cpu_body = node(text, 'cpu@0')
    require(cells(cpu_body, 'clock-frequency') == [50000000], 'CPU boot clock must be50MHz')
    require('"riscv,sv39"' in property_value(cpu_body, 'mmu-type'), 'Sv39 missing')
    identity = 'openion,valence-i1' if cpu == 'i1' else 'openion,orbital-a1'
    require(identity in property_value(cpu_body, 'compatible'), 'CPU identity mismatch')
    require(property_value(cpu_body, 'riscv,isa') == '"rv64imafdc_zicsr_zifencei_svade"', 'ISA mismatch')
    extensions = re.findall(r'"([^"\n]*)"', property_value(cpu_body, 'riscv,isa-extensions'))
    extensions = [part for value in extensions for part in value.split(r'\0')]
    require(set(extensions) == {'i','m','a','f','d','c','zicsr','zifencei','svade'}, 'ISA extension list mismatch')
    require(cells(node(text, 'memory@80200000'), 'reg') == [0,RAM_BASE,0,RAM_BYTES], 'DDR physical aperture mismatch')
    for name, address, size in [('dtb@80300000',0x80300000,0x10000),
                               ('diagnostics@fff78000',0xfff78000,0x80000),
                               ('monitor@ffff8000',0xffff8000,0x4000)]:
        body = node(text, name)
        require(cells(body, 'reg') == [0,address,0,size], 'reservation mismatch: ' + name)
        if not name.startswith('dtb'):
            require('no-map;' in body, 'reservation must be no-map: ' + name)
    # Resolve either source labels or numeric dtc phandles independently.
    cpu_intc = irq_ref(text, 'interrupt-controller', 'cpu0_intc')
    aia = irq_ref(text, 'interrupt-controller@c000000', 'valence_aia')
    controller = node(text, 'interrupt-controller@c000000')
    require('openion,valence-aia-csr-v1' in controller, 'CSR-only AIA compatible')
    require(cells(controller,'reg') == [0,0xc000000,0,0x4000,0,0xc004000,0,0x4000], 'APLIC apertures')
    require(cells(controller,'interrupts-extended') == [cpu_intc,9], 'AIA supervisor interrupt')
    require(cells(controller,'#interrupt-cells') == [2], 'AIA two-cell domain')
    timer = node(text,'timer@200bff8')
    require('riscv,aclint-mtimer' in timer, 'mtime compatible')
    require(cells(timer,'reg') == [0,0x200bff8,0,8,0,0x2004000,0,8], 'mtime/mtimecmp addresses')
    require(cells(timer,'interrupts-extended') == [cpu_intc,7], 'machine timer cause')
    uart = node(text,'serial@10000000')
    for prop, expected in [('reg',[0,0x10000000,0,8]),('clock-frequency',[7372800]),
                           ('current-speed',[460800]),('reg-shift',[0]),('reg-io-width',[1])]:
        require(cells(uart,prop) == expected, 'UART ' + prop)
    args = property_value(node(text,'chosen'),'bootargs')
    if console == 'uart-irq':
        require(cells(uart,'interrupts-extended') == [aia,3,4] and cells(uart,'fifo-size') == [16], 'UART IRQ/FIFO')
        require('console=ttyS0,460800n8' in args and 'console=hvc' not in args, 'native console ownership')
    else:
        require('interrupts-extended' not in uart and 'console=hvc0' in args, 'SBI console ownership')
    mac = node(text,'ethernet@10040000')
    require(cells(mac,'reg') == [0,0x10040000,0,0x1000,0,0x10002000,0,0x100], 'MAC/packet DMA windows')
    require(cells(mac,'interrupts-extended') == [aia,6,4], 'packet DMA IRQ6')
    dma = node(text,'dma-controller@10001000')
    require(cells(dma,'reg') in ([0,0x10001000,0,0x28],[0,0x10001000,0,0x1000]), 'memcpy DMA window')
    require(cells(dma,'interrupts-extended') == [aia,4,4], 'memcpy DMA IRQ4')
    for body in (dma, mac):
        require('dma-coherent;' in body, 'coherent DMA discovery missing')
        require(u64_property(body,'openion,ram-base') == RAM_BASE and u64_property(body,'openion,ram-bytes') == RAM_BYTES, 'DMA RAM aperture')
    cmu = node(text,'clock-controller@10080000')
    require(cells(cmu,'reg') == [0,0x10080000,0,0x800], 'CMU must not overlap clockmon')
    require('openion,valence-cmu-v1' in cmu, 'CMU compatible')
    # The monitor owns rate and performance subwindows in one platform driver.
    clockmon_matches = re.findall(r'([\w,-]+@10080800)\s*\{',text)
    require(len(clockmon_matches)==1, 'clock monitor node missing/duplicate')
    monitor = node(text,clockmon_matches[0])
    if cpu == 'a1':
        require(property_value(monitor,'status') == '"disabled"', 'A1 has no dynamic/perf hardware; clockmon must be disabled')
    else:
        require('status' not in monitor or property_value(monitor,'status') == '"okay"', 'I1 dynamic monitor must be enabled')
    if cpu == 'i1':
        provider = irq_ref(text,clockmon_matches[0],'clockmon0')
        require(cells(monitor,'#clock-cells') == [1], 'clockmon provider cells')
        require(cells(cmu,'clocks') == [provider,0] and property_value(cmu,'clock-names') == '"cpu-rate"', 'CMU live CPU rate parent')
    else:
        require('cpu-rate' not in cmu, 'A1 cannot depend on absent clockmon')
    require('openion,valence-clock-monitor-v1' in property_value(monitor,'compatible'), 'clockmon compatible')
    names = property_value(monitor,'reg-names')
    require(re.findall(r'"([^"]+)"', names) in (['rate','perf'], [r'rate\0perf']), 'clockmon resource names')
    require(cells(monitor,'reg') == [0,0x10080800,0,0x100,0,0x10080900,0,0x200], 'clockmon resource windows')
    return dict(cpu=cpu, ram_base=hex(RAM_BASE),ram_bytes=RAM_BYTES,ram_end_exclusive=hex(RAM_END),
                timebase_hz=250000000,board_verified=False)


def audit_config(text, console):
    lines = set(text.splitlines())
    required = ('64BIT','MMU','RISCV_SBI','FPU','MODULES','IRQ_DOMAIN','OF_IRQ',
                'SERIAL_8250','SERIAL_OF_PLATFORM','NET','INET','PHYLIB','OF_MDIO',
                'REALTEK_PHY','COMMON_CLK','DMA_ENGINE','DMA_VIRTUAL_CHANNELS','DMA_OF',
                'VALENCE_CMU','VALENCE_DMA','BLK_DEV_INITRD','DEVTMPFS','PROC_FS','SYSFS')
    for name in required:
        require('CONFIG_'+name+'=y' in lines,'kernel feature missing: '+name)
    for name in ('SMP','RISCV_ISA_V','RISCV_ISA_ZICBOM','MODULE_UNLOAD'):
        require('CONFIG_'+name+'=y' not in lines,'unqualified kernel feature: '+name)
    require('CONFIG_VALENCE_SOC=m' in lines,'SoC module config missing')
    if console == 'uart-irq':
        require('# CONFIG_HVC_RISCV_SBI is not set' in lines,'HVC conflicts with native UART')
        require(any('console=ttyS0,460800n8' in v for v in lines if v.startswith('CONFIG_CMDLINE=')), 'native kernel console')
    else:
        require('CONFIG_HVC_RISCV_SBI=y' in lines,'SBI recovery console missing')


def audit_modules(entries, kernel_release, autoload):
    """entries maps archive path to actual bytes; no modinfo host dependency."""
    # The rootfs may use one checked ordered list and a generic insmod loop.
    if 'etc/valence/modules.load' in entries:
        order = entries['etc/valence/modules.load'].decode().splitlines()
        require(order == list(MODULES), 'packed module load order mismatch')
        init = entries.get('init', b'').decode()
        require('done < /etc/valence/modules.load' in init and
                'insmod "/lib/modules/$release/extra/$module.ko"' in init and
                'sha256sum -c /etc/valence/modules.sha256' in init,
                'module list is not consumed by checked boot loader')
        require('compatible_enabled openion,valence-clock-monitor-v1' in init and
                'SKIP_UNSUPPORTED' in init, 'clockmon requires enabled live DT gate')
        hashes = entries.get('etc/valence/modules.sha256', b'').decode().splitlines()
        require(len(hashes) == len(MODULES), 'packed module hash inventory')
        for line in hashes:
            expected, path = line.split()
            path = path.lstrip('/')
            require(path in entries and hashlib.sha256(entries[path]).hexdigest() == expected,
                    'boot module integrity manifest mismatch')
        autoload = '\n'.join('modprobe '+name for name in order)
    modules = {}
    positions = {}
    autoload = '\n'.join(line for line in autoload.splitlines() if not line.lstrip().startswith('#'))
    for name in MODULES:
        matches = [p for p in entries if p.endswith('/'+name+'.ko')]
        require(len(matches)==1,'module absent/duplicate: '+name)
        path = matches[0]
        require('/modules/'+kernel_release+'/' in path,'module release directory: '+name)
        data = entries[path]
        require(data[:6] == b'\x7fELF\x02\x01' and len(data)>=64 and struct.unpack_from('<H',data,18)[0]==243,
                'module not ELF64 RISC-V: '+name)
        values = re.findall(rb'(?:^|\x00)vermagic=([^\x00]+)\x00',data)
        require(len(values)==1 and values[0].decode().split()[0]==kernel_release,'module vermagic: '+name)
        require(not {'SMP','mod_unload'}.intersection(values[0].decode().split()), 'module SMP/unload configuration mismatch: '+name)
        load = re.search(r'\b(?:modprobe\s+|insmod\s+(?:[^\s]*/)?)(?:'+re.escape(name)+r')(?:\.ko)?(?:\s|$)',autoload)
        require(load, 'autoload missing: '+name)
        positions[name] = load.start()
        modules[name]=hashlib.sha256(data).hexdigest()
    require(positions['valence_aia'] < positions['valence_dma'] and
            positions['valence_aia'] < positions['valence_gmac'] and
            positions['valence_cmu'] < positions['valence_gmac'] and
            positions['valence_clockmon'] < positions['valence_cmu'], 'unsafe driver initialization order')
    return modules


def audit_image(image, firmware):
    require(len(image)>=64 and image[0x30:0x38]==b'RISCV\x00\x00\x00' and image[0x38:0x3c]==b'RSC\x05','Linux Image magic')
    offset, runtime, flags=struct.unpack_from('<QQQ',image,8)
    require(offset==0x200000 and not flags&1 and runtime>=len(image),'Linux Image header/layout')
    require(0x80400000+runtime<=0xfff78000,'Linux overlaps reserved diagnostics')
    require(firmware[0x200000:0x200000+len(image)]==image,'OpenSBI payload at80400000 mismatch')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--i1-dts',type=Path,required=True)
    p.add_argument('--a1-dts',type=Path,required=True)
    p.add_argument('--console',choices=('sbi','uart-irq'),default='sbi')
    p.add_argument('--config',type=Path)
    p.add_argument('--initramfs',type=Path,help='uncompressed newc archive')
    p.add_argument('--kernel-release')
    p.add_argument('--image',type=Path)
    p.add_argument('--firmware',type=Path)
    args=p.parse_args()
    results=[audit_dts(path.read_text(),cpu,args.console) for path,cpu in ((args.i1_dts,'i1'),(args.a1_dts,'a1'))]
    result=dict(status='static_dt_contract_passed',profiles=results,board_verified=False)
    if args.config:
        audit_config(args.config.read_text(),args.console)
        result['kernel_config']='passed'
    if args.initramfs:
        require(args.config and args.kernel_release,'packed audit requires --config and --kernel-release')
        from audit_dinit_delivery import decode_newc
        entries,links=decode_newc(args.initramfs.read_bytes())
        contents={name:data or links.get((f[7],f[8],f[0]),b'') for name,(f,data) in entries.items()}
        # Inspect actual boot scripts only, not module names in README/docs.
        script_paths=[name for name in contents if name=='init' or name.startswith(('usr/local/libexec/','etc/init.d/'))]
        autoload='\n'.join(contents[name].decode(errors='replace') for name in script_paths)
        result['modules']=audit_modules(contents,args.kernel_release,autoload)
        result['status']='static_dt_config_packed_modules_passed'
    require(bool(args.image)==bool(args.firmware),'supply both --image and --firmware')
    if args.image:
        audit_image(args.image.read_bytes(),args.firmware.read_bytes())
        result['kernel_payload_layout']='passed'
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
