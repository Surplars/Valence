"""Independent registered replacement history and accepted policy/dirty-bus ledger."""
import json,re
from collections import Counter,deque
from itertools import groupby
from pathlib import Path
from contract import require,sha

def strict(line):
 def unique(pairs):
  require(len({k for k,v in pairs})==len(pairs),'LRU duplicate JSON key');return dict(pairs)
 return json.loads(line,object_pairs_hook=unique)
def policy(row,enabled,history):
 a=row['address'];s=row['set'];w=row['ways'];i=row['victim_index'];bit=row['replacement']
 require(a%64==0 and s==(a>>6)&255 and 0<=i<512 and (i&255)==s and bit in (0,1),'LRU candidate geometry')
 require(len(w)==2 and all(set(x)=={'valid','dirty','pa'}for x in w),'LRU way schema')
 for x in w:
  require(x['valid']in(0,1) and x['dirty']in(0,1),'LRU way flag width')
  require((x['pa']is not None)==bool(x['valid']) and (x['valid']or not x['dirty']),'LRU invalid way payload')
  if x['valid']:require(x['pa']%64==0 and (x['pa']>>6)&255==s,'LRU full PA/set mismatch')
 require(bit==history[s],'LRU replacement history mismatch')
 if not w[0]['valid']:expected=0
 elif not w[1]['valid']:expected=1
 elif enabled and row['store']:expected=bit
 elif not w[0]['dirty']:expected=0
 elif not w[1]['dirty']:expected=1
 else:expected=bit
 require(i>>8==row['victim_way']==expected,'LRU policy victim mismatch')
 require(row['store']in(0,1) and row['allocate']in(0,1),'LRU candidate flags')
 require((row['slot']in (0,1))if row['allocate']else row['slot']is None,'LRU allocation slot validity')
 return expected

def rows(path):
 with Path(path).open()as f:
  for line in f:yield strict(line)

def validate(path,text,result,side,admission_path=None):
 enabled=side=='on';first=result['roi']['begin_offer'];end=result['roi']['end_offer'];tail=result['roi']['tail_offer']
 history=None;last=-1;seq=0;terminal=None;counts=Counter();scopes={s:Counter()for s in ('all','roi','flush')};allocations=[];candidates={};writes=deque();waiting_b=deque();c_bursts={};c_acks={};initial=None
 for cycle,group in groupby(rows(path),lambda r:r['cycle']):
  batch=list(group);require(cycle>=last,'LRU event cycle reordered');last=cycle
  # Candidate observations precede this edge's mutations even though the
  # observer emits touch rows first. Apply accepted touches after all snapshots.
  touches=[];edge_candidate=None
  for r in batch:
   event=r['event'];require(r['sequence']==seq,'LRU event sequence gap/duplicate');seq+=1;counts[event]+=1
   require(terminal is None,'LRU events after terminal')
   if event=='initial':
    require(history is None and seq==1 and r['policy']==enabled,'LRU initial/policy');history=r['replacement'];require(len(history)==256 and all(x in(0,1)for x in history),'LRU initial replacement geometry');initial=cycle;continue
   require(history is not None,'LRU initial absent')
   if event=='terminal':
    terminal=r;require(r['policy']==enabled and (r['roi_first'],r['roi_end'],r['roi_cycles'])==(first,end,end-first),'LRU exact ROI terminal');continue
   offer=r['offer_cycle'];require(r['accepted_cycle']==cycle==offer+1,'LRU acceptance is not following edge')
   require(bool(r['roi'])==(first<=offer<end),'LRU offer ROI mismatch')
   scope=['all']+(['roi']if first<=offer<end else ['flush']if end<=offer<tail else [])
   for k in scope:scopes[k][event]+=1
   if event in ('candidate','allocation'):
    way=policy(r,enabled,history)
    if event=='candidate':require(edge_candidate is None,'LRU duplicate candidate edge');edge_candidate=r;candidates[offer]=r
    else:
     require(edge_candidate is not None and edge_candidate['allocate'],'LRU allocation without same-edge candidate')
     require({k:v for k,v in edge_candidate.items()if k not in('event','sequence')}=={k:v for k,v in r.items()if k not in('event','sequence','phase')},'LRU allocation snapshot mismatch')
     require(r['phase']in(1,2,3,4),'LRU accepted owner inactive');allocations.append(r)
     if r['ways'][way]['valid']:
      for k in scope:scopes[k]['selected_dirty'if r['ways'][way]['dirty']else 'selected_clean']+=1
   elif event=='touch':
    i=r['index'];require(0<=i<512 and (r['pa']>>6)&255==i&255,'LRU touch PA/index')
    require(r['kind']in('cpu_hit','install'),'LRU unknown touch kind')
    require(not r['store_prefetch']or r['prefetch'],'LRU store origin without PF')
    if r['kind']=='cpu_hit':require(not(r['prefetch']or r['store_prefetch']or r['posted']),'LRU CPU hit origin')
    after=(i>>8)if r['prefetch']and not r['store_prefetch']and not r['posted']else 1-(i>>8)
    require(after==r['after'],'LRU touch transition mismatch');touches.append((i&255,after))
   elif event=='refill':
    require(r['slot']in(0,1) and 0<=r['index']<512 and (r['pa']>>6)&255==r['index']&255,'LRU refill owner geometry')
    require(not r['store_prefetch']or r['prefetch'],'LRU refill origin');require(bool(r['installed'])==(not bool(r['error'])),'LRU refill install/error')
   elif event=='axi_aw':
    require(r['size']==3 and r['burst']==1 and r['len']==7 and r['pa']%64==0,'LRU external AW burst shape');writes.append(dict(id=r['id'],pa=r['pa'],beats=0,offer=offer))
   elif event=='axi_w':
    require(writes,'LRU W without actual AW');w=writes[0];w['beats']+=1
    require(r['strobe']==255 and bool(r['last'])==(w['beats']==8),'LRU W burst/strobe mismatch')
    if r['last']:waiting_b.append(writes.popleft())
   elif event=='axi_b':
    require(waiting_b and waiting_b[0]['id']==r['id'] and not r['error'],'LRU B owner/error mismatch');waiting_b.popleft()
   elif event=='tl_c':
    require(r['opcode']in(4,5,6,7) and r['size']==6 and r['pa']%64==0 and not r['corrupt'],'LRU TL C shape/error')
    require(r['opcode']in(5,7)or (r['data']==0 and r['corrupt']==0),'LRU inactive C data payload')
    src=r['source'];key=(r['opcode'],r['param'],r['size'],r['pa']);needed=8 if r['opcode']in(5,7)else 1
    if src not in c_bursts:require(src not in c_acks,'LRU TL C source reused before ReleaseAck');c_bursts[src]=[key,0]
    require(c_bursts[src][0]==key,'LRU TL C held-burst owner changed');c_bursts[src][1]+=1
    for k in scope:scopes[k]['tl_c_dirty_data_beats'if needed==8 else 'tl_c_clean_beats']+=1
    if c_bursts[src][1]==needed:
     del c_bursts[src]
     if r['opcode']in(6,7):c_acks[src]=key
   elif event=='tl_d':
    require(r['opcode']in(1,5)or (r['data']==0 and r['corrupt']==0),'LRU inactive D data payload')
    require(not(r['denied']or r['corrupt']),'LRU TL D error')
    if r['opcode']==6:require(r['source']in c_acks,'LRU ReleaseAck without completed actual C');del c_acks[r['source']]
   else:raise RuntimeError('LRU unknown event '+event)
  for s,value in touches:history[s]=value
 require(terminal is not None and not(writes or waiting_b or c_bursts or c_acks),'LRU terminal missing or undrained bus')
 marker=re.findall(r'^STORE_PF_LRU_OBSERVER cycles=(\d+) events=(\d+) policy=([01]) passive=1 actual_registered_replacement=1 accepted_next_edge=1$',text,re.M)
 require(marker==[(str(end-first),str(seq),str(int(enabled)))],'LRU log/trace terminal mismatch')
 if result['op']=='READ':
  require(result['case']in(0,6),'LRU unqualified no-flush READ case')
  require(result['flush_tail']==0 and tail==end and result['tail']['cycles']==0,'LRU READ must have empty flush interval')
  require(set(result['axi'])=={'roi'},'LRU READ AXI window schema')
  require(not any(scopes['flush'].values()),'LRU READ has flush segment events')
  require(all(result['tail'][k]==0 for k in ('axi_write_requests','axi_write_beats','axi_write_responses','axi_read_requests','axi_read_beats')),'LRU READ has nonzero flush counters')
  windows=('roi',)
 else:
  require(result['op']in('WRITE','COPY') and set(result['axi'])=={'roi','flush'},'LRU WRITE/COPY requires actual flush window')
  windows=('roi','flush')
 for s in windows:
  for channel in('aw','w'):require(scopes[s]['axi_'+channel]==result['axi'][s][channel]['fire'],'LRU actual external '+s+' '+channel+' mismatch')
  require(scopes[s]['axi_b']==result['roi'if s=='roi'else'tail']['axi_write_responses'],'LRU actual B window mismatch')
 if admission_path is not None:
  decisions={}
  for row in rows(admission_path):
   if row['event']=='decision':require(row['offer']not in decisions,'LRU duplicate original admission decision');decisions[row['offer']]=row
  require(set(decisions)==set(candidates),'LRU candidate/original admission cycle inventory')
  for cycle,c in candidates.items():
   d=decisions[cycle];require((c['address'],c['store'],c['victim_index'],bool(c['allocate']))==(d['candidate_address'],d['store'],d['index'],bool(d['allocate'])),'LRU candidate original origin/identity mismatch')
   for w in range(2):require(c['ways'][w]==dict(valid=d['way_valid'][w],dirty=d['way_dirty'][w],pa=(d['way_tag'][w]<<14)|(c['set']<<6)if d['way_valid'][w]else None),'LRU ways/original admission mismatch')
 return dict(status='PASS_ACTUAL_REGISTERED_REPLACEMENT_POLICY_AND_BUS',raw_sha256=sha(path),policy=enabled,initial_cycle=initial,events=seq,counts=dict(counts),windows={k:dict(v)for k,v in scopes.items()},allocation_count=len(allocations),candidate_count=len(candidates),all_candidate_history_verified=True,admission_identity_joined=admission_path is not None,acceptance_edge='offer+1',victim_cause_requires_full_PA_join=True)
