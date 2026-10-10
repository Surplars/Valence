"""Full-token passive CPU window and demand-load-line proof; preparation is not acceptance."""
import json
from collections import Counter
from pathlib import Path
from contract import require,sha,HERE
from copy_lineage import correlate

def token(x,r):
 require(isinstance(x,(list,tuple)) and len(x)==2 and all(type(v)is int for v in x) and 0<=x[0]<r and 0<=x[1]<2**64,'window full-token/index range');return tuple(x)
def validate(window_path,canonical_path,text,result,rob_entries,physical_regs):
 rows=[json.loads(l.split(' ',1)[1])for l in text.splitlines()if l.startswith('ROB_WINDOW ')];require(len(rows)==1,'window summary absent/duplicated');s=rows[0];roi=result['roi'];a,b=roi['begin_offer'],roi['end_offer'];n=b-a
 require((s['rob_entries'],s['physical_regs'],s['lsu_entries'])==(rob_entries,physical_regs,4) and s['roi_first']==a and s['roi_end']==b and s['cycles']==n,'window exact profile/ROI mismatch')
 for key,size in [('rob_occupancy',rob_entries+1),('free_physical',physical_regs+1),('ordinary_loads_live',rob_entries+1)]:require(len(s[key])==size and all(type(v)is int and v>=0 for v in s[key]) and sum(s[key])==n,'window histogram conservation '+key)
 require(s['rename_known_cycles']in (0,n),'partial rename authority');require(0<=s['rename_accepted_lanes']<=s['rename_offered_lanes']<=2*n,'rename lane conservation')
 if not s['rename_known_cycles']:require(all(s[k]==0 for k in ('rename_accepted_lanes','rename_offered_lanes','rename_stalled_cycles')),'invented rename evidence')
 for k in ('prepared_live_cycles','stalled_with_prf_shortage','rename_stalled_cycles','stalled_with_rob_full','stalled_with_prf_empty','stalled_with_dispatch_block','stalled_with_recovery','stalled_with_tag_exhausted'):require(0<=s[k]<=n,'window bounded cycle count '+k)
 lives={};live_index={};seq=0;terminal=None;last=-1
 with open(window_path)as f:
  for line in f:
   x=json.loads(line);require(terminal is None and x['sequence']==seq,'window sequence/terminal');
   if x['event']=='terminal':terminal=x;continue
   seq+=1;t=token(x['token'],rob_entries);require(x['cycle']>=last and x['first_seen']<=x['cycle'],'window lifecycle chronology');last=x['cycle']
   if x['event']=='load_live':require(t not in lives and t[0]not in live_index,'duplicate live token/index');lives[t]={**x,'left_rob':None};live_index[t[0]]=t
   else:
    require(x['event']=='left_rob' and t in lives and live_index.get(t[0])==t and lives[t]['left_rob']is None,'departure wrong token/tag reuse')
    require(x['first_seen']==lives[t]['first_seen'] and x['pc']==lives[t]['pc'],'departure owner payload changed');lives[t]['left_rob']=x['cycle'];del live_index[t[0]]
 require(terminal is not None and terminal['events']==seq and terminal['roi_first']==a and terminal['roi_end']==b and terminal['roi_cycles']==n,'window terminal conservation')
 prepared={};accepted={};outstanding_ordinary={};visible={};responses={};starts={};unknown_cache=0;last=-1;cache_order=[];peak_lines=0;peak_owners=0;witnesses=[];witness_count=0;adjacent_miss_count=0;entered_roi=False
 with open(canonical_path)as f:
  for line in f:
   x=json.loads(line);cycle=x['cycle'];require(type(cycle)is int and cycle>=last,'canonical chronological order');last=cycle;e=x['event'];known=bool(x['known']);t=token([x.get('token_index'),x.get('token_tag')],rob_entries)if known else None
   if known:require(0<=x['epoch']<2**32,'epoch width');
   if not entered_roi and cycle>=a:
    entered_roi=True;carry=list(outstanding_ordinary.values());peak_owners=max(peak_owners,len(carry));peak_lines=max(peak_lines,len({z['pa']//64 for z in carry}))
   if e=='load_prepared' and known and x['prechecked']:
    require(not x['store'] and x['size']in range(4),'ordinary prepared load shape');k=(t,x['epoch']);prepared.setdefault(k,[]).append({'cycle':cycle,'va':x['va'],'pa':x['pa']})
   if e=='lsu_start' and known:
    require(t not in starts,'duplicate LSU start full token');starts[t]=x
   if e=='cache_accept':
    cache_order.append((t,x))
    if not known:unknown_cache+=a<=cycle<b;continue
    require(t in starts,'cache accept lacks exact LSU start');require(t not in accepted,'duplicate accepted token');require(starts[t]['epoch']==x['epoch'],'cache/start epoch changed')
    ordinary=not x['store'] and not x['atomic'] and x.get('cache_ordinary')==1
    accepted[t]={**x,'ordinary':ordinary,'miss':ordinary and not x['cache_request_found'],'first_response_visible':None,'response_accepted':None}
    if ordinary and a<=cycle<b:
     older=[(ot,z)for ot,z in outstanding_ordinary.items()if ot!=t and z['miss'] and z['cycle']<cycle and (z['pa']//64)!=(x['pa']//64)]
     for ot,z in older:
      witness_count+=1;adjacent_miss_count+=accepted[t]['miss'] and (x['pa']&~63)==(z['pa']&~63)+64
      if len(witnesses)<32:witnesses.append({'first_token':list(ot),'next_token':list(t),'first_line':z['pa']&~63,'next_line':x['pa']&~63,'first_cache_accept':z['cycle'],'next_cache_accept':cycle,'next_is_demand_miss':accepted[t]['miss'],'adjacent_next_line':(x['pa']&~63)==(z['pa']&~63)+64,'first_response_visible':None})
    if ordinary:outstanding_ordinary[t]=accepted[t]
    live=list(outstanding_ordinary.values());peak_owners=max(peak_owners,len(live))if a<=cycle<b else peak_owners;peak_lines=max(peak_lines,len({z['pa']//64 for z in live}))if a<=cycle<b else peak_lines
   if e=='cache_response_visible':
    require(cache_order and cache_order[0][0]==t,'first-visible response order/full token mismatch')
    if known:
     require(t in accepted and accepted[t]['first_response_visible']is None and cycle>=accepted[t]['cycle'],'response visibility chronology');accepted[t]['first_response_visible']=cycle;visible[t]=cycle;outstanding_ordinary.pop(t,None)
   if e=='cache_response':
    require(cache_order and cache_order[0][0]==t,'response acceptance order/full token mismatch');cache_order.pop(0)
    if known:require(t in visible and cycle>=visible[t],'accepted response lacks prior visible edge');accepted[t]['response_accepted']=cycle;responses[t]=cycle
 require(not cache_order,'cache accepted owners did not terminally drain')
 for w in witnesses:
  v=visible[tuple(w['first_token'])];require(w['next_cache_accept']<v,'not before first visible response');w['first_response_visible']=v
 ordinary={t:z for t,z in accepted.items()if z['ordinary'] and a<=z['cycle']<b}
 for t,z in ordinary.items():require(t in lives and lives[t]['first_seen']<=z['cycle'] and (lives[t]['left_rob']is None or z['cycle']<lives[t]['left_rob']),'accepted load lacks full ROB lifetime')
 by_token={}
 for (pt,ep),rows in prepared.items():by_token.setdefault(pt,[]).extend({"epoch":ep,**v}for v in rows)
 stage_report=correlate(lives,accepted,starts,prepared,a,b,result.get('case'),HERE/'guest.bin')
 lifetimes=[]
 for t,l in lives.items():
  z=accepted.get(t);lifetimes.append({**l,'token':list(t),'prepared':by_token.get(t,[]),'lsu_start':starts.get(t),'cache_accept':z,'first_cache_response_visible':visible.get(t),'cache_response_accepted':responses.get(t)})
 lifetime_path=Path(str(window_path)+'.lifetimes.jsonl');contents=''.join(json.dumps(x,sort_keys=True)+'\n'for x in lifetimes)
 if lifetime_path.exists():require(lifetime_path.read_text()==contents,'existing full-token lifetime artifact differs')
 else:lifetime_path.write_text(contents)
 return {'status':'PASS_PASSIVE_WINDOW_AND_LOAD_LINE_AUDIT','summary':s,'prepared_distinct_lines':len({x['pa']//64 for entries in prepared.values()for x in entries if a<=x['cycle']<b}),'accepted_ordinary_distinct_lines':len({z['pa']//64 for z in ordinary.values()}),'accepted_ordinary_loads':len(ordinary),'accepted_demand_misses':sum(z['miss']for z in ordinary.values()),'peak_distinct_ordinary_lines_before_response_visible':peak_lines,'peak_ordinary_owners_before_response_visible':peak_owners,'unknown_cache_acceptances_in_roi':unknown_cache,'next_line_before_first_miss_response_witnesses':witnesses,'distinct_line_before_first_miss_response_pair_count':witness_count,'adjacent_next_demand_miss_witness_count':adjacent_miss_count,'copy_stage_lineage':stage_report,'no_unknown_address_inferred':True,'prepared_is_not_accepted':True,'load_lifetimes':{'path':str(lifetime_path),'sha256':sha(lifetime_path),'owners':len(lifetimes)},'files':{str(window_path):sha(window_path),str(canonical_path):sha(canonical_path)}}
