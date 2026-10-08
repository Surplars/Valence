#!/usr/bin/env python3
"""Audit one shared initialized RAM CRC table in a linked target ROM."""
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess

VALUES = (0,0x1db71064,0x3b6e20c8,0x26d930ac,0x76dc4190,0x6b6b51f4,0x4db26158,0x5005713c,
          0xedb88320,0xf00f9344,0xd6d6a3e8,0xcb61b38c,0x9b64c2b0,0x86d3d2d4,0xa00ae278,0xbdbdf21c)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    args = parser.parse_args()
    elf = args.rom / 'bootrom.elf'
    def run(tool, *flags):
        return subprocess.check_output(['riscv64-unknown-elf-' + tool, *flags, str(elf)], text=True)
    syms = {}
    raw = run('nm', '-S', '-n')
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) in (3,4): syms[parts[-1]] = int(parts[0],16)
    assert len(re.findall(r'\bcrc32_table$', raw, re.M)) == 1
    contract=json.loads((args.rom/'bootrom-contract.json').read_text())
    table_bytes=contract['crc_table_bytes']; mode=contract['crc_mode']
    start, end = syms['__crc32_table_start'], syms['__crc32_table_end']
    assert start % 64 == 0 and end - start == table_bytes and start == syms['crc32_table']
    assert syms['__data_start'] <= start < end <= syms['__data_end']
    assert start >= syms['__app_stack_top'] >= 0x80200000
    assert syms['__bss_end'] <= syms['__boot_stack_top'] - 8192
    data = (args.rom / 'bootrom.bin').read_bytes()
    values=list(VALUES)
    if mode!='nibble':
        values=[]
        for n in range(256):
            c=n
            for _ in range(8): c=(c>>1)^(0xedb88320 if c&1 else 0)
            values.append(c)
        if mode=='slice4':
            first=values[:];previous=values[:]
            for _ in range(3):
                previous=[(v>>8)^first[v&255] for v in previous];values.extend(previous)
    expected = struct.pack('<'+str(len(values))+'I', *values)
    load = syms['__data_load'] + start - syms['__data_start']
    assert data[load - 0x80000000:load - 0x80000000 + table_bytes] == expected
    assert data.count(expected) == 1 and len(data) <= 131072
    dis = run('objdump', '-d')
    helper = re.search(r'<firmware_crc_update>:\n(.*?)(?=\n\n|\Z)', dis, re.S).group(1)
    assert len(re.findall(r'\blbu\s', helper)) == (5 if mode=='slice4' else 1)
    assert len(re.findall(r'\blw(?:u)?\s', helper)) == dict(nibble=2,byte=1,slice4=5)[mode]
    # Register/address dataflow and _start copy are reviewed in saved disassembly.
    report = dict(status='passed', crc_mode=mode, table_bytes=table_bytes, table_vma=hex(start), table_lma=hex(load),
                  globals_bytes=syms['__bss_end']-syms['__app_stack_top'],
                  reserved_stack_bytes=8192, rom_bytes=len(data),
                  target_execution=False, instruction_dataflow='manual disassembly review required')
    (args.rom / 'crc-placement-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    (args.rom / 'symbols.txt').write_text(raw)
    (args.rom / 'disassembly.txt').write_text(run('objdump','-d','-h','-s','-j','.text','-j','.data'))
    print(json.dumps(report))

if __name__ == '__main__':
    main()
