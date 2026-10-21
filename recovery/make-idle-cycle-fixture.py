"""Build a native FPGA testbench around the unmodified emitted boundary."""
import argparse
import hashlib
import json
import re
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('emission', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
assert not a.output.exists(), 'preserve prior evidence'
top = a.emission / 'CommonCpuClockBoundary.sv'
text = top.read_text()
header = text.split('module CommonCpuClockBoundary(', 1)[1].split(');', 1)[0]
ports = {}
direction, width = None, None
for row in header.split(','):
    row = row.strip()
    m = re.fullmatch(r'(?:(input|output)\s+(?:(\[\d+:0\])\s*)?)?(\w+)', row)
    assert m, row
    if m[1]:
        direction, width = m[1], int(m[2][1:-3]) + 1 if m[2] else 1
    ports[m[3]] = (direction, width)
assert all(n in ports for n in ('cpuEmptyInFabric', 'fabricEmptyInCpu'))
assert all(re.search(r'\breg\s+' + n + r'\s*;', text) for n in ('cpuEmptySource', 'fabricEmptySource'))
lines = ['`timescale 1ps/1ps', 'module idle_cycle_tb;']
for name, (_, bits) in ports.items():
    lines.append(f"logic [{bits-1}:0] {name};")
lines += ['CommonCpuClockBoundary dut(' + ','.join(f'.{n}({n})' for n in ports) + ');',
          'integer csent=0, fsent=0, crecv=0, frecv=0, cb=0, fb=0, cf=0, ff=0;',
          'integer target=25; bit sending=0, draining=0;',
          'initial begin cpuClock=0; forever #1667 cpuClock=~cpuClock; end',
          'initial begin fabricClock=0; #719; forever #2000 fabricClock=~fabricClock; end',
          'initial begin']
for name, (direction, _) in ports.items():
    if direction == 'input' and name not in ('cpuClock', 'fabricClock'):
        lines.append(f"{name}='0;")
lines += ['commonColdReset=1; #40000; commonColdReset=0;',
          'wait(cpuLinkReady && fabricLinkReady && cpuEmptyInFabric && fabricEmptyInCpu);',
          'sending=1; wait(cb>=4 && fb>=4); draining=1;',
          'wait(csent==25 && fsent==25 && crecv==25 && frecv==25); sending=0;',
          'wait(cpuEmptyInFabric && fabricEmptyInCpu); #20000;',
          'target=26; sending=1;',
          'wait(csent==26 && fsent==26 && crecv==26 && frecv==26); sending=0;',
          'wait(cpuEmptyInFabric && fabricEmptyInCpu); #20000;',
          'if(cf<2 || ff<2) $fatal(1,"FIRST_OFFER_NOT_EXERCISED");',
          '$display("IDLE_CYCLE_PASS cpu=%0d fabric=%0d backpressure=%0d/%0d first=%0d/%0d",csent,fsent,cb,fb,cf,ff); $finish; end',
          'initial begin #10000000; $fatal(1,"IDLE_CYCLE_TIMEOUT"); end']

for tag, source, destination, clock, destclock, sent, received, blocked, first, reg in (
    ('c', 'cpu_scalar_0_request', 'fabric_scalar_0_request', 'cpuClock', 'fabricClock', 'csent', 'crecv', 'cb', 'cf', 'cpuEmptySource'),
    ('f', 'fabric_msi_request', 'cpu_msi_request', 'fabricClock', 'cpuClock', 'fsent', 'frecv', 'fb', 'ff', 'fabricEmptySource'),
):
    fields = [n[len(source+'_bits_'):] for n in ports if n.startswith(source+'_bits_')]
    assert fields
    for f in fields:
        assert ports[source+'_bits_'+f][1] == ports[destination+'_bits_'+f][1]
    def pattern(field, count):
        bits = ports[source+'_bits_'+field][1]
        return f"{bits}'(64'h123456780000 + {count}*257 + {fields.index(field)*19+3})"
    concat = '{' + ','.join(destination+'_bits_'+f for f in fields) + '}'
    total = sum(ports[source+'_bits_'+f][1] for f in fields)
    lines += [f'logic [{total-1}:0] {tag}held; bit {tag}stalled=0;',
              f'always @(negedge {clock}) begin',
              f'{source}_valid = sending && {sent}<target;']
    for f in fields:
        lines.append(f'{source}_bits_{f} = {pattern(f,sent)};')
    lines += ['end', f'always @(negedge {destclock}) {destination}_ready=draining;',
              f'always @(posedge {clock}) if(!commonColdReset) begin',
              f'if({source}_valid && !{source}_ready) {blocked}={blocked}+1;',
              f'if({source}_valid && {source}_ready) {sent}={sent}+1;',
              f'if({source}_valid && dut.{reg}) begin {first}={first}+1; #1; if(dut.{reg}!==0) $fatal(1,"FIRST_OFFER_IDLE_{tag}"); end',
              'end', f'always @(posedge {destclock}) if(!commonColdReset) begin',
              f'if({tag}stalled && ({destination}_valid!==1 || {concat}!=={tag}held)) $fatal(1,"STALLED_PAYLOAD_{tag}");',
              f'{tag}stalled={destination}_valid && !{destination}_ready; {tag}held={concat};',
              f'if({destination}_valid && {destination}_ready) begin',
              f'if({received}>={sent}) $fatal(1,"UNOWNED_OUTPUT_{tag}");']
    for f in fields:
        lines.append(f'if({destination}_bits_{f} !== {pattern(f,received)}) $fatal(1,"PAYLOAD_{tag}_{f}");')
    lines += [f'if($test$plusargs("BAD_ORACLE") && {received}==0) $fatal(1,"ORACLE_NEGATIVE_REJECT");',
              f'{received}={received}+1; end end']
lines += ['endmodule']
a.output.mkdir(parents=True)
(a.output/'idle_cycle_tb.sv').write_text('\n'.join(lines)+'\n')
sources = sorted(a.emission.glob('*.sv'))
# The standalone export contains only its real transitive modules.
(a.output/'sources.f').write_text(''.join('"'+str(f.resolve()).replace('\\','/')+'"\n' for f in sources)+'idle_cycle_tb.sv\n')
(a.output/'run.tcl').write_text('run all\nquit\n')
(a.output/'inputs.json').write_text(json.dumps({str(f.name):hashlib.sha256(f.read_bytes()).hexdigest() for f in sources},indent=2)+'\n')
print(json.dumps({'ports':len(ports),'rtl_modules':len(sources),'bench':'idle_cycle_tb.sv','qualified':False}))
