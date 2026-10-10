import copy,json,tempfile
from pathlib import Path
from window_trace import validate

def fixture(r,p):
 i,j=(r-2,r-1);tag=(1<<63)+55;tok=[i,tag];nexttok=[j,tag+1];s={'schema':1,'rob_entries':r,'physical_regs':p,'lsu_entries':4,'roi_first':10,'roi_end':20,'cycles':10,'rob_occupancy':[0]*(r+1),'free_physical':[0]*(p+1),'ordinary_loads_live':[0]*(r+1),'prepared_live_cycles':1,'rename_known_cycles':10,'rename_offered_lanes':2,'rename_accepted_lanes':2,'rename_stalled_cycles':0,'stalled_with_rob_full':0,'stalled_with_prf_empty':0,'stalled_with_prf_shortage':0,'rename_fresh_demand_lanes':2,'rename_prf_insufficient_offered_lanes':0,'stalled_with_dispatch_block':0,'stalled_with_recovery':0,'stalled_with_tag_exhausted':0};s['rob_occupancy'][r]=10;s['free_physical'][0]=10;s['ordinary_loads_live'][2]=10
 life=[]
 for k,t in enumerate((tok,nexttok)):life.append(dict(event='load_live',sequence=k,cycle=10,roi=1,token=t,first_seen=8,pc=4096+4*k))
 for k,t in enumerate((tok,nexttok)):life.append(dict(event='left_rob',sequence=k+2,cycle=21+k,roi=0,token=t,first_seen=8,pc=4096+4*k))
 life.append(dict(event='terminal',sequence=4,roi_first=10,roi_end=20,roi_cycles=10,events=4))
 def ev(kind,t,cyc,pa):return dict(event=kind,cycle=cyc,known=1,token_index=t[0],token_tag=t[1],epoch=7,store=0,atomic=0,prechecked=1,va=pa-0x80000000,pa=pa,size=3,cache_ordinary=1,cache_request_found=0)
 trace=[ev('load_prepared',tok,10,0x80004000),ev('lsu_start',tok,10,0x80004000),ev('cache_accept',tok,11,0x80004000),ev('load_prepared',nexttok,12,0x80004040),ev('lsu_start',nexttok,12,0x80004040),ev('cache_accept',nexttok,13,0x80004040),ev('cache_response_visible',tok,15,0x80004000),ev('cache_response',tok,16,0x80004000),ev('cache_response_visible',nexttok,17,0x80004040),ev('cache_response',nexttok,18,0x80004040)]
 return s,life,trace

def check(s,life,trace):
 with tempfile.TemporaryDirectory()as t:
  a,b=Path(t)/'life',Path(t)/'trace';a.write_text(''.join(json.dumps(x)+'\n'for x in life));b.write_text(''.join(json.dumps(x)+'\n'for x in trace));return validate(a,b,'ROB_WINDOW '+json.dumps(s),{'roi':{'begin_offer':10,'end_offer':20}},s['rob_entries'],s['physical_regs'])
negatives=0
for r,p in ((16,48),(16,64),(32,64),(64,64)):
 s,l,t=fixture(r,p);v=check(s,l,t);assert v['adjacent_next_demand_miss_witness_count']==1 and v['peak_distinct_ordinary_lines_before_response_visible']==2
 changes=[lambda a,b,c:c[5].update(token_index=r),lambda a,b,c:c[6].update(token_tag=c[6]['token_tag']+1),lambda a,b,c:c[5].update(epoch=8),lambda a,b,c:c[6].update(cycle=12),lambda a,b,c:b[2].update(token=[b[2]['token'][0],b[2]['token'][1]+99]),lambda a,b,c:a['rob_occupancy'].__setitem__(r,9)]
 for mutation in changes:
  a,b,c=copy.deepcopy((s,l,t));mutation(a,b,c)
  try:check(a,b,c)
  except (RuntimeError,KeyError,AssertionError):negatives+=1
  else:raise AssertionError('mutation escaped')
 # Same physical index, new full generation is valid only after old departure.
 a,b,c=copy.deepcopy((s,l,t));b[2]['cycle']=16;b[3]['cycle']=22;b.insert(3,dict(event='load_live',sequence=3,cycle=20,roi=0,token=[r-2,(1<<63)+90],first_seen=20,pc=8888));b.insert(5,dict(event='left_rob',sequence=5,cycle=23,roi=0,token=[r-2,(1<<63)+90],first_seen=20,pc=8888));
 for n,x in enumerate(b):x['sequence']=n
 b[-1]['events']=6;check(a,b,c)
print(json.dumps({'status':'PASS_HOST_WINDOW_CONTROLS_ONLY','profiles':4,'negative_controls':negatives,'index_boundaries':[15,16,31,32,63],'full_generation_above_signed64':True,'same_index_new_generation_valid_after_departure':True,'DUT_executed':False}))
from copy_lineage import correlate,COPY_LD_PC
from contract import HERE
s,l,t=fixture(64,64)
for x in l:
 if x['event']in('load_live','left_rob'):x['pc']=COPY_LD_PC
# Explicit stage chain: final second-line cache acceptance occurs after first response,
# while ROB visibility, preparation and LSU start occur before it.
def stages(trace,life):
 lives={tuple(x['token']):x for x in life if x['event']=='load_live'};acc={};st={};prep={}
 for x in trace:
  k=(x['token_index'],x['token_tag'])
  if x['event']=='lsu_start':st[k]=x
  if x['event']=='load_prepared':prep.setdefault((k,x['epoch']),[]).append({'cycle':x['cycle'],'pa':x['pa'],'va':x['va']})
  if x['event']=='cache_accept':acc[k]={**x,'ordinary':True,'miss':True,'first_response_visible':15 if k[0]==62 else 22}
 return correlate(lives,acc,st,prep,10,20,21,HERE/'guest.bin')
t[5]['cycle']=16
v=stages(t,l);assert v['stage_pair_counts']['visible']['adjacent_next_line']==1 and v['stage_pair_counts']['prepared']['adjacent_next_line']==1 and v['stage_pair_counts']['started']['adjacent_next_line']==1 and v['stage_pair_counts']['accepted']['adjacent_next_line']==0
for change in ('pa','token'):
 q=copy.deepcopy(t)
 if change=='pa':q[5]['pa']^=64
 else:q[5]['token_tag']+=999
 if change=='token':
  missing=stages(q,l);assert missing['unlinked_visible_full_tokens_unknown']==1 and missing['stage_pair_counts']['visible']['adjacent_next_line']==0
 else:
  try:stages(q,l)
  except RuntimeError:pass
  else:raise AssertionError('retrospective mapping mutation escaped '+change)
print(json.dumps({'status':'PASS_COPY_FOUR_STAGE_LINEAGE_CONTROLS_ONLY','visible_prepared_started_but_not_accepted':True,'wrong_actual_PA_rejected':True,'wrong_full_token_cannot_borrow_address':True,'DUT_executed':False}))
