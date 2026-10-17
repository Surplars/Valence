"""Read-only verification of committed small evidence; no model execution."""
from pathlib import Path
import csv, json, hashlib, collections
O=Path(__file__).resolve().parent
v=json.loads((O/'verification.json').read_text())
for name,h in v['artifact_sha256'].items():
 p=O/name
 if p.is_file(): assert hashlib.sha256(p.read_bytes()).hexdigest()==h,name
read=lambda n:[{k:int(x) for k,x in r.items()} for r in csv.DictReader((O/n).open())]
ps=read('copy-pairs.csv');rs=read('waiting.csv');by={r['cycle']:r for r in rs}
assert len(ps)==32
for p in ps:
 w=[r for r in rs if r['ordinal']==p['ordinal']]
 assert [r['cycle'] for r in w]==list(range(p['store_prepared'],p['q_first']))
 assert all((r['store_index'],r['store_tag'])==(p['store_index'],p['store_tag']) for r in w)
w=[r for r in rs if (r['head_index'],r['head_tag'])!=(r['store_index'],r['store_tag'])]
a=[r for r in w if not r['eligible_mask']&~((1<<r['q_index'] if r['q_live'] else 0)|(1<<r['s_index'] if r['s_live'] else 0))]
assert len(rs)==780 and len(w)==748 and len(a)==105 and len({r['cycle'] for r in a})==37
for r in a:
 assert r['q_live'] and r['s_live'] and not r['start_valid']
 assert r['q_tag']>r['store_tag'] and r['s_tag']>r['store_tag']
 n=by[r['cycle']+1]
 assert not (n['s_live'] and (n['s_index'],n['s_tag'])==(r['q_index'],r['q_tag']))
print('PASS: 32 full-token pairs; 780 waiting pair-cycles; A has zero free-Q opportunities in 37 unique candidate cycles')
