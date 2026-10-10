import copy,json,tempfile,os
from pathlib import Path
from unissued_trace import validate
P=Path(os.environ.get("UNISSUED_FIXTURE_DIR",Path(__file__).resolve().parent))
rows=[json.loads(x)for x in (P/'fixture.jsonl').read_text().splitlines()]
text=(P/'fixture.log').read_text()
validate(P/'fixture.jsonl',text,{'mode':1,'roi':{'cycles':11}})
controls=[]
def attempt(name,fn):
 mutated=copy.deepcopy(rows);changes=fn(mutated);assert changes>0,name
 with tempfile.TemporaryDirectory()as d:
  p=Path(d)/'bad.jsonl';p.write_text(''.join(json.dumps(x)+'\n'for x in mutated))
  try:validate(p,text,{'mode':1,'roi':{'cycles':11}})
  except (RuntimeError,KeyError,TypeError,ValueError)as e:controls.append({'name':name,'mutations':changes,'rejected':True,'reason':str(e)})
  else:raise AssertionError('negative escaped '+name)
def store_mut(key,fn):
 def change(rr):
  for x in rr:
   if x['event']=='span' and x['state']['stores']:
    q=x['state']['stores'][0]
    if key in q and q[key]is not None:q[key]=fn(q[key]);return 1
  raise AssertionError('no mutable store')
 return change
attempt('wrong_full_generation_store_token',store_mut('token',lambda t:[t[0],t[1]^(1<<48)]))
attempt('wrong_store_index_token',store_mut('token',lambda t:[(t[0]+1)%16,t[1]]))
attempt('registered_readiness_corruption',store_mut('registered_ready2',lambda x:1-x))
attempt('omitted_event',lambda r:(r.pop(2),1)[1])
attempt('duplicated_event',lambda r:(r.insert(2,copy.deepcopy(r[2])),1)[1])
def span_change(rr,key,fn):
 for x in rr:
  if x['event']=='span':x['state'][key]=fn(x['state'][key]);return 1
attempt('mode_classification_corruption',lambda r:span_change(r,'satp',lambda v:0))
attempt('exclusive_readiness_bin_corruption',lambda r:span_change(r,'bin',lambda v:(v+1)%10))
attempt('duplicate_roi_cycle',lambda r:next((x.update(begin=x['begin']-1),1)[1]for x in r if x['event']=='span'))
attempt('omitted_roi_cycle',lambda r:next((x.update(end=x['end']+1),1)[1]for x in r if x['event']=='span'))
attempt('unknown_va_fabrication',store_mut('address_known',lambda v:1-v))
attempt('issued_without_start_generation',store_mut('accepted_start',lambda v:1))
print(json.dumps({'status':'PASS_NONZERO_PARSER_NEGATIVES','controls':controls},indent=2))
