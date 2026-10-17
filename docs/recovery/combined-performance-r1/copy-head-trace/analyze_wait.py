from pathlib import Path
import csv,json,collections
O=Path(__file__).resolve().parent;C=O.parent
read=lambda p:[{k:int(v) for k,v in r.items()} for r in csv.DictReader(p.open())]
a=(C/'logs/stream-copy16.log').read_text();b=(O/'logs/run-r1.log').read_text().split('Traceback (most recent call last):')[0]
assert ''.join(x for x in b.splitlines(keepends=True) if not x.startswith('COPY_TRACE_PASS '))==a
assert (O/'copy-pairs.csv').read_bytes()==(C/'copy-trace/copy-pairs.csv').read_bytes()
rows=read(O/'waiting.csv');pairs=read(O/'copy-pairs.csv');out=[];classes=collections.Counter()
for p in sorted(pairs,key=lambda x:x['ordinal']):
 w=[r for r in rows if r['ordinal']==p['ordinal']]
 assert [r['cycle'] for r in w]==list(range(p['store_prepared'],p['q_first']))
 assert all((r['store_index'],r['store_tag'])==(p['store_index'],p['store_tag']) for r in w)
 ishead=lambda r:(r['head_index'],r['head_tag'])==(r['store_index'],r['store_tag'])
 eligible=lambda r:bool(r['eligible_mask']&(1<<r['store_index']))
 for r in w:classes[f"head={int(ishead(r))},eligible={int(eligible(r))},Q={r['q_live']},S={r['s_live']}"]+=1
 out.append({'ordinal':p['ordinal'],'prepared_to_Q':len(w),'at_head_cycles':sum(ishead(r) for r in w),'eligible_cycles':sum(eligible(r) for r in w),'first_head':next((r['cycle'] for r in w if ishead(r)),None),'first_eligible':next((r['cycle'] for r in w if eligible(r)),None),'Q_live_cycles':sum(r['q_live'] for r in w),'S_live_cycles':sum(r['s_live'] for r in w)})
result={'original_stdout_exact':True,'original_pairs_exact':True,'waiting_pair_cycles':len(rows),'classes':dict(classes),'pairs':out}
(O/'wait-results.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
