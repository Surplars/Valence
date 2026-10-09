#!/usr/bin/env python3
"""Verify the archived whole ELF and assemble only the separate replay launcher."""
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SCHEMA = 'valence-whole-monitor-bandwidth-replay-v1'
BASE = 0xfff78000
END = 0xffff8000
ELF_SHA = '17a26a142b01c755e852876239f12b65569cb15e703a3137a0356ffd2984c1f4'
SOURCE_SHA = 'fe53442d7444aa1e8b1cf8c709d2537ad75d9fdfb109e3170d3ff7ca31c15e7f'
EXPECTED_SYMBOLS = {'_start': BASE, 'cpu_bandwidth': 0xfff782dc, 'main': 0xfff78890,
                    '__bss_start': 0xfff7e948, '__bss_end': 0xfff7f158,
                    '__app_stack_top': 0xfff98000, 'observed': 0xfff7e948}
TICKS = [0xfff783d8, 0xfff78404, 0xfff787b0, 0xfff787e4,
         0xfff784c4, 0xfff784ec, 0xfff78500, 0xfff785dc, 0xfff78618, 0xfff7862c,
         0xfff783d8, 0xfff78404, 0xfff784c4, 0xfff784ec, 0xfff78500,
         0xfff785dc, 0xfff78618, 0xfff7862c]


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def elf(data):
    require(data[:7] == b'\x7fELF\x02\x01\x01', 'ELF must be little-endian ELF64')
    h = struct.unpack_from('<HHIQQQIHHHHHH', data, 16)
    typ, machine, version, entry, phoff, shoff, flags, eh, phsz, phnum, shsz, shnum, names = h
    require((typ, machine, version, eh, phsz, shsz) == (2, 243, 1, 64, 56, 64), 'ELF ABI/header drift')
    require(phoff + phsz * phnum <= len(data) and shoff + shsz * shnum <= len(data), 'ELF table out of file')
    loads = []
    for i in range(phnum):
        pt, pf, off, va, pa, fs, ms, align = struct.unpack_from('<IIQQQQQQ', data, phoff + phsz * i)
        if pt == 1:
            require(fs <= ms and off + fs <= len(data) and va == pa, 'invalid ELF LOAD')
            loads.append(dict(address=va, offset=off, filesz=fs, memsz=ms, flags=pf, align=align))
    headers = [struct.unpack_from('<IIQQQQIIQQ', data, shoff + shsz * i) for i in range(shnum)]
    require(names < shnum, 'invalid section names')
    ns = headers[names]
    strings = data[ns[4]:ns[4] + ns[5]]
    def cstr(raw, offset):
        require(offset < len(raw), 'ELF string offset out of bounds')
        end = raw.find(b'\0', offset)
        require(end >= 0, 'unterminated ELF string')
        return raw[offset:end].decode()
    sections = []
    symbols = {}
    for s in headers:
        name, st, sf, va, off, sz, link, info, align, entsz = s
        if st != 8:
            require(off + sz <= len(data), 'ELF section out of file')
        sections.append(dict(name=cstr(strings, name), type=st, flags=sf, address=va, offset=off, size=sz))
        if st == 2:
            require(entsz == 24 and link < shnum, 'ELF symbol schema drift')
            ss = headers[link]
            symstrings = data[ss[4]:ss[4] + ss[5]]
            for n in range(0, sz, entsz):
                sn, si, so, ndx, value, size = struct.unpack_from('<IBBHQQ', data, off + n)
                if sn:
                    symbols[cstr(symstrings, sn)] = value
    return dict(entry=entry, flags=flags, loads=loads, sections=sections, symbols=symbols)


def archive_check(archive, source):
    pins = json.loads((HERE / 'pins.json').read_text())
    for name, digest in pins['archive_files'].items():
        require(sha(archive / name) == digest, 'pinned archive changed: ' + name)
    release = json.loads((archive / 'receipt.json').read_text())
    require(release['status'] == 'passed', 'archival release did not pass')
    for name, digest in release['source_sha256'].items():
        require(sha(source / name) == digest, 'archived source closure drift: ' + name)
    require(sha(source / 'fpga/firmware/monitor_diagnostics.c') == SOURCE_SHA, 'diagnostic source changed')
    contract = json.loads((archive / 'firmware/diagnostic-contract.json').read_text())
    require(contract['compiler'] == '14.2.0', 'archived guest compiler drift')
    require((contract['reserve_start'], contract['reserve_end'], contract['payload_stack_bytes']) ==
            (BASE, END, 16384), 'diagnostic reservation drift')
    for name, digest in contract['official_source_sha256'].items():
        require(sha(source / 'simulator/build/coremark-src' / name) == digest, 'official CoreMark source drift: ' + name)
    image = (archive / 'firmware/monitor-diagnostic.bin').read_bytes()
    data = (archive / 'firmware/monitor-diagnostic.elf').read_bytes()
    require(hashlib.sha256(data).hexdigest() == ELF_SHA, 'archived ELF signature drift')
    require(len(image) == contract['rom_blob_bytes'] and hashlib.sha256(image).hexdigest() == contract['rom_blob_sha256'],
            'archived binary/contract mismatch')
    e = elf(data)
    require(e['entry'] == BASE and e['flags'] == 0 and len(e['loads']) == 1, 'archived ELF entry/load/ISA drift')
    seg = e['loads'][0]
    require((seg['address'], seg['filesz'], seg['memsz']) == (BASE, len(image), 0x7158), 'archived LOAD mapping drift')
    require(data[seg['offset']:seg['offset'] + seg['filesz']] == image, 'ELF LOAD/bin byte mismatch')
    for name, address in EXPECTED_SYMBOLS.items():
        require(e['symbols'].get(name) == address, 'archived ELF symbol drift: ' + name)
    alloc = [s for s in e['sections'] if s['flags'] & 2]
    require([s['name'] for s in alloc] == ['.text', '.rodata', '.data', '.bss'], 'unexpected ELF allocated section')
    cursor = BASE
    for s in alloc:
        require(s['address'] == cursor, 'ELF allocated gap/overlap')
        require(s['address'] + s['size'] <= 0xfff94000, 'code/globals overlap reserved diagnostic stack')
        if s['type'] != 8:
            require(data[s['offset']:s['offset'] + s['size']] == image[s['address'] - BASE:s['address'] - BASE + s['size']],
                    'ELF section/bin mapping mismatch')
        cursor += s['size']
    require(cursor == EXPECTED_SYMBOLS['__bss_end'], 'ELF BSS extent drift')
    signatures = {0xfff78048: 0x00008067, 0xfff783f0: 0x0007b603, 0xfff783f4: 0x00878793,
                  0xfff783f8: 0x00c70733, 0xfff783fc: 0xfeb79ae3,
                  0xfff787d0: 0x0007b683, 0xfff787d4: 0x00878793,
                  0xfff787d8: 0x00d70733, 0xfff787dc: 0xfef59ae3}
    for pc, insn in signatures.items():
        require(struct.unpack_from('<I', image, pc - BASE)[0] == insn, 'bound instruction signature drift')
    for pc in TICKS:
        require(struct.unpack_from('<I', image, pc - BASE)[0] & 0xfffff07f == 0xc0102073, 'bound rdtime signature drift')
    return dict(elf=e, contract=contract, archive=str(archive), source=str(source),
                source_inventory=release['source_sha256'], pins=pins, tick_pcs=TICKS,
                limits=['Archived GCC14.2.0 ELF; board GCC13.2 object is unavailable and was not reproduced.',
                        'Whole diagnostic preserves its UART, cold/hot loop PCs, flushes and verification traffic.',
                        'Initial monitor cache history is not recreated by the small replay launcher.'])


def tools(prefix):
    result = {}
    for name in ('as', 'ld', 'objcopy', 'objdump', 'readelf'):
        path = shutil.which(prefix + name)
        require(path is not None, 'existing tool required: ' + prefix + name)
        result[name] = dict(path=path, sha256=sha(path), version=subprocess.check_output([path, '--version'], text=True).splitlines()[0])
    return result


def prepare(archive, source, out, prefix):
    require(not out.exists(), 'use a fresh preparation directory')
    state = archive_check(archive, source)
    state.update(schema=SCHEMA, status='PREPARING', tools=tools(prefix), fixture_sources={})
    out.mkdir(parents=True)
    for name in ('launcher.S', 'launcher.ld'):
        state['fixture_sources'][name] = sha(HERE / name)
    commands = [([state['tools']['as']['path'], '-march=rv64im_zicsr_zifencei', '-mabi=lp64', HERE/'launcher.S', '-o', out/'launcher.o'], 'assemble'),
                ([state['tools']['ld']['path'], '--no-relax', '-T', HERE/'launcher.ld', out/'launcher.o', '-o', out/'launcher.elf'], 'link-launcher'),
                ([state['tools']['objcopy']['path'], '-O', 'binary', out/'launcher.elf', out/'launcher.bin'], 'launcher-bin'),
                ([state['tools']['objdump']['path'], '-d', out/'launcher.elf'], 'launcher-disassembly'),
                ([state['tools']['objdump']['path'], '-d', archive/'firmware/monitor-diagnostic.elf'], 'diagnostic-disassembly')]
    state['commands'] = []
    for cmd, name in commands:
        with (out/(name+'.log')).open('w') as stream:
            completed = subprocess.run(list(map(str, cmd)), stdout=stream, stderr=subprocess.STDOUT, timeout=30)
        require(completed.returncode == 0, name + ' failed')
        state['commands'].append(dict(command=list(map(str, cmd)), exit=completed.returncode, log=name+'.log'))
    launcher = elf((out/'launcher.elf').read_bytes())
    state['launcher_symbols'] = {n: launcher['symbols'][n] for n in ('launcher_start', 'launcher_returned', 'launcher_done', 'launcher_fail')}
    require(launcher['entry'] == 0x80000000 and (out/'launcher.bin').stat().st_size <= 128, 'launcher outside tiny ROM contract')
    require(launcher['loads'][0]['address'] + launcher['loads'][0]['memsz'] <= 0x80200000, 'launcher overlaps RAM')
    state['artifacts'] = {p.name:sha(p) for p in out.iterdir() if p.is_file()}
    state['status'] = 'PASS_STATIC_ARCHIVE_AND_LAUNCHER'
    (out/'manifest.json').write_text(json.dumps(state, indent=2)+'\n')
    print(state['status'], out/'manifest.json')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', required=True, type=Path)
    p.add_argument('--source', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--prefix', default='riscv64-unknown-elf-')
    a = p.parse_args()
    prepare(a.archive.resolve(), a.source.resolve(), a.out.resolve(), a.prefix)
