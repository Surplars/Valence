"""Freeze the real original-project implementation order, excluding OOC blocks."""
import argparse
import hashlib
import json
import re
import tkinter
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('inspection', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
repo = Path(__file__).resolve().parents[1]
t = tkinter.Tcl()
rows = {}
for line in (a.inspection/'ip-constraint-properties.tcllist').read_text().splitlines():
    v = t.splitlist(line)
    d = dict(zip(v[::2], v[1::2]))
    rows[d['path'].lower()] = d
part = (a.inspection/'implementation-constraint-order.rpt').read_text().split('Compile Order for Out-of-Context')[0]
ordered, evidence = [], []
for line in part.splitlines():
    if not re.match(r'^\d+\s', line):
        continue
    path = re.search(r'[Ee]:/.*$', line)[0]
    d = rows[path.lower()]
    assert d['IS_ENABLED'] == d['USED_IN_IMPLEMENTATION'] == '1'
    f = Path(path)
    oldhash = hashlib.sha256(f.read_bytes()).hexdigest()
    if not d['SCOPED_TO_REF']:
        assert f.name in ('board_pins.xdc', 'pl_ddr4_pins.xdc')
        new = repo/('fpga/common/board_pins.xdc' if f.name == 'board_pins.xdc' else 'fpga/zu15eg/pl_ddr4_pins.xdc')
        assert new.read_text() == f.read_text(), 'board constraint semantics differ'
        f = new
    row = [str(f).replace('\\', '/'), d['SCOPED_TO_REF'], d['SCOPED_TO_CELLS'], d['PROCESSING_ORDER']]
    assert not any(c in value for value in row for c in '{}\n\r')
    ordered.append(row)
    evidence.append(dict(path=row[0], ref=row[1], cells=row[2], order=row[3],
                         sha256=hashlib.sha256(f.read_bytes()).hexdigest(), original_sha256=oldhash))
assert len(ordered) == 13, 'review changed original implementation census'
assert [row[3] for row in ordered] == ['EARLY']*9 + ['NORMAL']*2 + ['LATE']*2
assert not a.output.exists(), 'preserve prior evidence'
a.output.mkdir(parents=True)
q = lambda s: '{'+s+'}'
(a.output/'original-implementation-xdc.tcl').write_text('set recovery_ip_xdc [list '+' '.join(
    '[list '+' '.join(q(v) for v in row)+']' for row in ordered)+']\n')
(a.output/'original-implementation-xdc-hashes.json').write_text(json.dumps(evidence, indent=2)+'\n')
print('Verified 13 original implementation XDCs: scopes/order/hash frozen; OOC-only files excluded')
