import copy,json,os,tempfile
from pathlib import Path
from dmmu_trace import validate
p=Path(os.environ['ADMISSION_FIXTURE_DIR']);rows=[json.loads(l)for l in (p/'dmmu.jsonl').read_text().splitlines()];log=(p/'dmmu.log').read_text();validate(p/'dmmu.jsonl',log)
cases={
'request_id':lambda x:next(r for r in x if r.get('request')).update(id=4),
'walk_va':lambda x:next(r for r in x if r.get('walk_start')).update(va=5),
'walk_id':lambda x:next(r for r in x if r.get('walk_start')).update(id=6),
'reply_va':lambda x:next(r for r in x if r.get('response')and not r.get('request')).update(va=8),
'reply_id':lambda x:next(r for r in x if r.get('response')and not r.get('request')).update(id=9),
'reply_state':lambda x:next(r for r in x if r.get('response')and not r.get('request')).update(service=1),
'invalid_pa':lambda x:next(r for r in x if r.get('walk_start')).update(pa=2),
'prechecked_demand':lambda x:next(r for r in x if r.get('request')).update(prechecked_ingress=1),
'missing_request':lambda x:x.pop(next(i for i,r in enumerate(x)if r.get('request'))),
'missing_walk':lambda x:x.pop(next(i for i,r in enumerate(x)if r.get('walk_start'))),
'missing_response':lambda x:x.pop(next(i for i,r in enumerate(x)if r.get('response')and not r.get('request'))),
'duplicate_walk':lambda x:x.insert(2,copy.deepcopy(next(r for r in x if r.get('walk_start')))),
}
rejected=[]
with tempfile.TemporaryDirectory()as td:
 q=Path(td)/'p.jsonl'
 for n,mut in cases.items():
  bad=copy.deepcopy(rows);mut(bad);q.write_text(''.join(json.dumps(r)+'\n'for r in bad))
  try:validate(q,log)
  except (ValueError,KeyError,TypeError):rejected.append(n)
  else:raise AssertionError('escaped '+n)
print(json.dumps({'status':'PASS_D_TRANSLATION_INDEPENDENT_CORRUPTION_CONTROLS','rejected':rejected},indent=2))
