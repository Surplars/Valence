"""Candidate v1 decoder (independent of frozen R3 count): decode actual ROM INIT through its mapped address/output graph, read-only.

Supported cells: LUT/INV/MUX, static selector FF D expressions and RAMB36E2 without
output registers. Unknown data-graph cells and cycles fail closed. Clock/control timing is unverified.
The actual A-even/B-odd paired boundary covers all32768 logical words.
"""
if not __debug__:
    raise SystemExit('Safety checks require Python without -O')

from pathlib import Path
from collections import Counter
import hashlib
import json
import re
import struct
import sys

import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('root', type=Path)
parser.add_argument('dump', type=Path)
parser.add_argument('--rom-sha256', required=True)
parser.add_argument('--padded-sha256', required=True)
parser.add_argument('--report', type=Path, help='Optional new output; default prints only')
args=parser.parse_args()
assert re.fullmatch(r'[0-9a-f]{64}', args.rom_sha256)
assert re.fullmatch(r'[0-9a-f]{64}', args.padded_sha256)
root=args.root;dump=args.dump;graph=Path(str(dump)+'.graph.tsv')
ports={}; cells={}; types={}; drivers={}
for line in graph.read_text(encoding='utf-8').splitlines():
    a=line.split('\t'); kind=a[0]
    if kind=='PORT':
        assert a[1] not in ports, ('duplicate_port',a[1])
        ports[a[1]]=(a[2],a[3])
    elif kind=='NET':types[a[1]]=a[2]
    elif kind=='CELL':
        assert a[1] not in cells, ('duplicate_cell',a[1])
        cells[a[1]]=dict(ref=a[2],props={},pins={})
    elif kind=='PROP':
        assert a[2] not in cells[a[1]]['props'], ('duplicate_property',a[1],a[2])
        cells[a[1]]['props'][a[2]]=a[3]
    elif kind=='PIN':
        assert a[2] not in cells[a[1]]['pins'], ('duplicate_pin',a[1],a[2])
        cells[a[1]]['pins'][a[2]]=a[4]
        if a[3]=='OUT':drivers.setdefault(a[4],[]).append((a[1],a[2]))
    else:raise AssertionError(a)
def number(text):
    m=re.fullmatch(r"(\d+)'([hHbB])([0-9a-fA-F]+)",text)
    if m:return int(m.group(3),16 if m.group(2).lower()=='h' else 2)
    return int(text)
ram={}
for name,c in cells.items():
    if c['ref']=='RAMB36E2':
        p=c['props'];assert int(p['DOA_REG'])==int(p['DOB_REG'])==0
        ram[name]=(sum(number(p[f'INIT_{i:02X}'])<<(i*256) for i in range(128)),
                   sum(number(p[f'INITP_{i:02X}'])<<(i*256) for i in range(16)))
assert ram, 'Missing ROM RAM inventory'
# Enumerate all memory primitives independently in INIT dump and graph. No
# extra/unreachable/unsupported RAM is silently ignored because the ROM matches.
dumped = {}; current = None
for line in dump.read_text().splitlines():
    fields = line.split('\t')
    if fields[0] == 'CELL':
        current = fields[1]
        assert current not in dumped, ('duplicate_dump_cell', current)
        dumped[current] = dict(ref=fields[2], props={})
    else:
        assert current is not None and fields[0] not in dumped[current]['props']
        dumped[current]['props'][fields[0]] = fields[1]
assert set(dumped) == set(ram), ('dump_graph_RAM_inventory', set(dumped), set(ram))
for name, cell in cells.items():
    assert re.fullmatch(r'LUT[1-6]|INV|MUXF[789]|FDRE|FDCE|FDSE|FDPE|RAMB36E2|VCC|GND', cell['ref']), ('unsupported_ROM_inventory', name, cell['ref'])
for name, cell in dumped.items():
    assert cell['ref'] == 'RAMB36E2'
    assert cell['props'] == cells[name]['props'], ('dump_graph_RAM_properties', name)
for side in ('a', 'b'):
    for name in [f'addr{side}[{i}]' for i in range(15)] + [f'en{side}', f'clk{side}']:
        assert ports[name][0] == 'IN', ('input_port_direction', name)
    for i in range(32):
        assert ports[f'dout{side}[{i}]'][0] == 'OUT'
visited_ram = set()
raw=(root/'firmware/bootrom.bin').read_bytes()
assert 0 < len(raw) <= 131072
assert hashlib.sha256(raw).hexdigest()==args.rom_sha256
expected=raw+bytes(131072-len(raw))
expected_words=struct.unpack('<32768I',expected)
image=bytearray()
counts=Counter(c['ref'] for c in cells.values())
for row in range(16384):
    address=2*row
    inputs={};cache={};active=set()
    def assign(n,value):
        if types.get(n)=='GROUND':assert value==0,(n,value)
        elif types.get(n)=='POWER':assert value==1,(n,value)
        else:
            if n in inputs:assert inputs[n]==value,('aliased_input',n,value,inputs[n])
            inputs[n]=value
    for side,addr in (('a',address),('b',address+1)):
        for bit in range(15):assign(ports[f'addr{side}[{bit}]'][1],(addr>>bit)&1)
        assign(ports[f'en{side}'][1],1)
        assign(ports[f'clk{side}'][1],0)
    def net(n):
        if n in cache:return cache[n]
        if n in inputs:return inputs[n]
        if types.get(n)=='GROUND':return 0
        if types.get(n)=='POWER':return 1
        assert n not in active,('cycle',n)
        active.add(n)
        assert len(drivers.get(n,[]))==1,('driver',n,drivers.get(n))
        name,pin=drivers[n][0];c=cells[name];ref=c['ref'];p=c['props'];pins=c['pins']
        def v(key):return net(pins[key])
        if re.fullmatch(r'LUT[1-6]',ref):
            values=[v(f'I{i}') for i in range(int(ref[-1]))]
            unknown=[i for i,x in enumerate(values) if x is None]
            base=sum(x<<i for i,x in enumerate(values) if x is not None)
            table=number(p['INIT']); possible=set()
            for vector in range(1<<len(unknown)):
                index=base|sum(((vector>>j)&1)<<i for j,i in enumerate(unknown))
                possible.add((table>>index)&1)
            result=next(iter(possible)) if len(possible)==1 else None
        elif ref=='INV':
            value=v('I');result=None if value is None else 1-value
        elif ref in ('MUXF7','MUXF8','MUXF9'):
            select=v('S')
            if select is not None:result=v('I1' if select else 'I0')
            else:
                left=v('I0');right=v('I1');result=left if left==right else None
        elif ref in ('FDRE','FDCE','FDSE','FDPE'):
            reset={'FDRE':'R','FDCE':'CLR','FDSE':'S','FDPE':'PRE'}[ref]
            assert v(reset) in (0,1),('unknown_selector_reset',name)
            if v(reset):result=int(ref in ('FDSE','FDPE'))
            else:
                result=v('D') if v('CE')==1 else None
        elif ref=='RAMB36E2':
            visited_ram.add(name)
            m=re.fullmatch(r'(DOUTADOUT|DOUTBDOUT|DOUTPADOUTP|DOUTPBDOUTP)\[(\d+)\]',pin)
            assert m,('RAM_pin',name,pin)
            side='A' if m.group(1) in ('DOUTADOUT','DOUTPADOUTP') else 'B'
            width=int(p['READ_WIDTH_'+side]);assert width in (1,2,4,9,18,36),(name,width)
            bits={1:1,2:2,4:4,9:8,18:16,36:32}[width]
            shift=(bits.bit_length()-1)
            bus='ADDRARDADDR' if side=='A' else 'ADDRBWRADDR'
            addr=sum(v(f'{bus}[{i}]')<<i for i in range(15))>>shift
            enable='ENARDEN' if side=='A' else 'ENBWREN'
            index=int(m.group(2));data,parity=ram[name]
            if v(enable)!=1:result=None
            elif m.group(1).startswith('DOUTP'):
                parity_bits=bits//8;assert parity_bits and index<parity_bits
                result=(parity>>(addr*parity_bits+index))&1
            else:
                assert index<bits,(name,pin,width)
                result=(data>>(addr*bits+index))&1
        else:raise AssertionError(('unsupported_ROM_cell',name,ref,pin))
        active.remove(n);cache[n]=result
        return result
    for side,addr in (('a',address),('b',address+1)):
        bits=[net(ports[f'dout{side}[{bit}]'][1]) for bit in range(32)]
        assert all(v in (0,1) for v in bits),('unknown_ROM_read',side,addr)
        word=sum(value<<bit for bit,value in enumerate(bits))
        assert word==expected_words[addr],dict(side=side,address=addr,actual=hex(word),expected=hex(expected_words[addr]))
        image+=word.to_bytes(4,'little')
assert visited_ram == set(ram), ('unreachable_ROM_RAM', set(ram)-visited_ram)
digest=hashlib.sha256(image).hexdigest()
assert digest==args.padded_sha256
assert image==expected
dcp=root/'synthesis/post_synth_unconstrained.dcp'
report=dict(status='PASS_COMBINED_ACTUAL_ROM_WORDS_AND_INVENTORY_NOT_BOOT_QUALIFICATION',bytes=131072,sha256=digest,
    method='static mixed-width BRAM INIT/address/output reconstruction; FF D expressions at assumed enabled read; A-even/B-odd shared-row covers every word; aliases/constants checked',
    unverified=['clock connectivity and polarity', 'RAM reset/sleep/write controls', 'temporal read behavior', 'boot and board functionality'],
    primitive_counts=dict(counts),bram_count=len(ram),init_dump_sha256=hashlib.sha256(dump.read_bytes()).hexdigest(),
    graph_sha256=hashlib.sha256(graph.read_bytes()).hexdigest(),source_synth_dcp_sha256=hashlib.sha256(dcp.read_bytes()).hexdigest(),
    candidate_schema='combined-bandwidth-ROM-graph-v1', all_live_ram_accounted=True)
if args.report:
    with args.report.open('x') as handle:
        handle.write(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,sort_keys=True))
