"""Check the frozen native top/wrapper widths and Tcl syntax; no Vivado."""
if not __debug__:
    raise SystemExit('Safety checks require Python without -O')

from pathlib import Path
import hashlib
import json
import re
import sys
import tkinter

import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('root',type=Path)
args=parser.parse_args()
root=args.root
wrapper=(root/'export/board/soc_top_fpga_next_ddr.sv').read_text(encoding='utf-8')
top=(root/'native/FpgaNextSocTop.sv').read_text(encoding='utf-8')
def width(r):
    return abs(int(r.group(1))-int(r.group(2)))+1 if r else 1
def ports(text, module):
    body=re.search(r'\bmodule\s+'+module+r'(?:\s*#\(.*?\))?\s*\((.*?)\);',text,re.S).group(1)
    result={}; direction=None; size=None
    for part in body.split(','):
        part=re.sub(r'//[^\n]*','',part).strip()
        decl=re.match(r'(input|output|inout)\b',part)
        if decl:
            direction=decl.group(1); size=width(re.search(r'\[(\d+):(\d+)\]',part))
        name=re.findall(r'[A-Za-z_][A-Za-z0-9_$]*',part)[-1]
        assert name not in result
        result[name]=(direction,size)
    return result
tp=ports(top,'FpgaNextSocTop'); wp=ports(wrapper,'soc_top_fpga_next_ddr')
signals={k:v[1] for k,v in wp.items()}
body=wrapper[wrapper.index(');')+2:]
for match in re.finditer(r'\bwire\s*(\[\d+:\d+\])?\s+([^;]+);',body):
    size=width(re.search(r'\[(\d+):(\d+)\]',match.group(1) or ''))
    for item in match.group(2).split(','):
        name=re.match(r'\s*([A-Za-z_][A-Za-z0-9_$]*)',item)
        assert name,item
        signals[name.group(1)]=size
instance=re.search(r'\bFpgaNextSocTop\s+u_soc\s*\((.*?)\);',wrapper,re.S).group(1)
connections=re.findall(r'\.([A-Za-z_][A-Za-z0-9_$]*)\s*\(([^()]*)\)',instance)
assert len(tp)==len(connections)==76
rows=[]; empty=[]
for name,expression in connections:
    expression=expression.strip()
    if not expression:
        assert tp[name][0]=='output'
        empty.append(name);continue
    constant=re.fullmatch(r"(\d+)'[bhdBHD][0-9a-fA-F_xXzZ]+",expression)
    if constant: actual=int(constant.group(1))
    else:
        signal=re.fullmatch(r'~?([A-Za-z_][A-Za-z0-9_$]*)',expression)
        assert signal,expression
        actual=signals[signal.group(1)]
    assert tp[name][1]==actual,(name,expression,tp[name],actual)
    rows.append(dict(port=name,expression=expression,bits=actual,direction=tp[name][0]))
assert len(rows)==73
assert set(empty)=={'io_nativeGmac_txData','io_nativeGmac_txEnable','io_nativeGmac_txError'}
tcl=tkinter.Tcl()
scripts={}
for p in (root/'scripts').glob('*.tcl'):
    data=p.read_text(encoding='utf-8')
    assert int(tcl.call('info','complete',data))==1,p
    if p.name.startswith('r3_'):
        assert not re.search(r'^\s*(route_design|write_bitstream)\b',data,re.M),p
        limits=[int(x) for x in re.findall(r'general.maxThreads\s+(\d+)',data)]
        assert all(x>=1 for x in limits),p
    scripts[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
report=dict(status='PASS_STATIC_PREFLIGHT_NOT_TOOL_EXECUTION',top_ports=76,nonempty_connections=rows,allowed_unused_outputs=empty,tcl_syntax=scripts)
print(json.dumps(report,sort_keys=True))
print('PASS_STATIC_R3 ports76 connected73 widths_match scripts_complete positive_threads_tool_range_checked_at_runtime NO_ROUTE_NO_BIT')
