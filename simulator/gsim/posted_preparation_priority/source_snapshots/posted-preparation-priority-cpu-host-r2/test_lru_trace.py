import copy,json,tempfile
from pathlib import Path
from lru_trace import policy,validate
from contract import require
negative=[]
def reject(name,fn,why):
 try:fn()
 except Exception as e:require(why in str(e),'wrong negative reason '+name+': '+str(e));negative.append(dict(name=name,reason=str(e)));return
 raise AssertionError('negative escaped '+name)
def candidate():return dict(event='candidate',cycle=11,offer_cycle=10,accepted_cycle=11,roi=1,address=0x80208080,store=1,set=2,replacement=0,victim_index=2,victim_way=0,allocate=0,slot=None,ways=[dict(valid=1,dirty=1,pa=0x80200080),dict(valid=1,dirty=0,pa=0x80204080)])
h=[0]*256;c=candidate();require(policy(c,True,h)==0,'new victim');old=copy.deepcopy(c);old.update(victim_index=258,victim_way=1);require(policy(old,False,h)==1,'old victim')
reject('old_policy_victim',lambda:policy(old,True,h),'policy victim')
x=copy.deepcopy(c);x['replacement']=1;reject('wrong_replacement',lambda:policy(x,True,h),'replacement history')
x=copy.deepcopy(c);x['ways'][1]['pa']+=64;reject('wrong_full_pa',lambda:policy(x,True,h),'full PA/set')
x=copy.deepcopy(c);x['store']=0;reject('wrong_origin',lambda:policy(x,True,h),'policy victim')
x=copy.deepcopy(c);x['ways'][1]['valid']=0;reject('inactive_way_payload',lambda:policy(x,True,h),'invalid way payload')
result=dict(case=21,op='COPY',flush_tail=3,roi=dict(begin_offer=10,end_offer=20,tail_offer=23,axi_write_responses=0),tail=dict(axi_write_responses=0),axi={s:{ch:{'fire':0}for ch in ('aw','w')}for s in ('roi','flush')})
initial=dict(event='initial',sequence=0,cycle=9,policy=1,replacement=[0]*256)
touch=dict(event='touch',cycle=11,offer_cycle=10,accepted_cycle=11,roi=1,kind='cpu_hit',index=2,pa=0x80200080,prefetch=0,store_prefetch=0,posted=0,after=1)
# Output touch before candidate; candidate must use the preceding bit, not this edge's result.
fixture=[initial,touch,c,dict(event='terminal',cycle=24,policy=1,roi_first=10,roi_end=20,roi_cycles=10)]
def run(rows):
 with tempfile.TemporaryDirectory()as d:
  rows=copy.deepcopy(rows)
  for i,r in enumerate(rows):r['sequence']=i
  p=Path(d)/'raw.jsonl';p.write_text(''.join(json.dumps(r)+'\n'for r in rows))
  text=f'STORE_PF_LRU_OBSERVER cycles=10 events={len(rows)} policy=1 passive=1 actual_registered_replacement=1 accepted_next_edge=1\n'
  return validate(p,text,result,'on')
require(run(fixture)['all_candidate_history_verified'],'positive sparse edges')
x=copy.deepcopy(fixture);x[2]['replacement']=1;reject('same_edge_touch_misordered',lambda:run(x),'replacement history')
x=copy.deepcopy(fixture);x[2]['accepted_cycle']=12;reject('wrong_acceptance_edge',lambda:run(x),'following edge')
x=copy.deepcopy(fixture);x[1]['after']=0;reject('wrong_touch_transition',lambda:run(x),'touch transition')
x=copy.deepcopy(fixture);x[2]['roi']=0;reject('wrong_roi',lambda:run(x),'offer ROI')
print(json.dumps(dict(status='PASS_LRU_INDEPENDENT_HOST_CONTROLS',negative_count=len(negative),negative=negative,actual_DUT=False),sort_keys=True))
