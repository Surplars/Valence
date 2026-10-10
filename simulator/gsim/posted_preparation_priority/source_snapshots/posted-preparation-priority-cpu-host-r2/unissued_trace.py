"""Independent passive interval audit; no speculative savings calculation."""
import json
from collections import Counter
from pathlib import Path

def need(x,m):
 if not x:raise RuntimeError(m)
def token(x,rob_entries=16):
 need(isinstance(x,list) and len(x)==2 and all(type(v)is int for v in x) and 0<=x[0]<rob_entries and 0<=x[1]<2**64,'full token shape/range');return tuple(x)
def original_bin(s):
 c=s['choice']
 if not c or c['store'] or c['atomic'] or c['head']:return 0
 if s['start_fire']:return 1
 if not c['prechecked']:return 2
 if s['physical_conflict']:return 3
 if s['older_uncanonical']:return 4
 if not s['no_other_serial']:return 5
 if not s['issue_available']:return 6
 if s['older_system']:return 7
 return 8

def classification(s):
 if not s['selected']:return 0
 if not s['choice']['prechecked']:return 1
 a=s['stores']
 if not a:return 2
 p=[x for x in a if x['pending']]
 if any(not x['pending'] and x['accepted_start']is None for x in a):return 9
 if not p:return 3
 if any(not x['sources_known'] for x in p):return 9
 if any(not x['registered_ready1'] for x in p):return 4
 if any(not x['registered_ready2'] for x in p):return 5
 if any(not x['address_known'] for x in p):return 6
 if any(not x['prepared'] for x in p):return 7
 return 8

BIN_NAMES=['not_selected_younger_ordinary_load','selected_load_not_prechecked','prechecked_no_older_store','only_issued_older_stores','unissued_some_rs1_not_ready','unissued_rs1_all_ready_some_rs2_not_ready','unissued_operands_ready_some_address_not_captured','unissued_operands_address_ready_some_not_prepared','unissued_all_operands_address_prepared','unissued_identity_or_readiness_unknown']

def validate(path,text,result=None,canonical=None,rob_entries=16,physical_regs=48):
 need(rob_entries in (16,32,64) and physical_regs in (48,64),"invalid actual profile")
 token=lambda x: globals()["token"](x,rob_entries)
 summaries=[json.loads(x.split(' ',1)[1])for x in text.splitlines()if x.startswith('UNISSUED_STORES ')]
 need(len(summaries)==1,'unissued summary missing/duplicate');summary=summaries[0]
 owners={};bins=Counter();original=Counter();dimensions=Counter();n=spans=0;cursor=None;first=None;terminal=None
 pair_counts=Counter();store_counts=Counter();producer_counts=Counter();witnesses={}
 with open(path)as f:
  for line in f:
   x=json.loads(line);need(terminal is None,'event after terminal');need(x['sequence']==n,'duplicate/omitted event sequence')
   if x['event']=='terminal':terminal=x;continue
   n+=1
   if x['event']=='owner':
    t=token(x['token']);need(t not in owners,'duplicate full-token owner');need(x['first_seen']>=0 and 0<=x['pc']<2**64,'owner timing/pc')
    need(0<=x['destination']<physical_regs,'owner destination range')
    if x['sources_known']:need(all(type(x[k])is int and 0<=x[k]<physical_regs for k in ('source1','source2')),'owner source range')
    else:need(x['source1']is None and x['source2']is None,'unknown sources fabricated')
    owners[t]=x;continue
   need(x['event']=='span','unknown supplement event');spans+=1;a,b,s=x['begin'],x['end'],x['state'];need(type(a)is int and type(b)is int and b>a,'interval range')
   if cursor is None:first=a
   else:need(a==cursor,'duplicate/omitted ROI cycle')
   cursor=b;cycles=b-a;need(s['bin']==classification(s),'readiness classification corruption');need(s['canonical_bin']==original_bin(s),'canonical classification corruption');bins[s['bin']]+=cycles;original[s['canonical_bin']]+=cycles
   need(s['satp']>>60 in (0,8) and s['privilege'] in (0,1,3),'mode encoding');need(0<=s['head']<rob_entries and 0<=s['rob_count']<=rob_entries,'ROB geometry')
   if result is not None:need((s['satp']>>60)==(8 if result['mode']==1 else 0) and s['privilege']==1,'ROI mode classification corruption')
   c=s['choice'];need(bool(s['selected'])==bool(c and not c['store'] and not c['atomic'] and not c['head']),'selected class mismatch')
   if c:
    lt=token(c['token']);need(lt in owners,'choice missing exact owner');owner=owners[lt];need(owner['memory'] and owner['store']==c['store'] and owner['atomic']==c['atomic'],'choice class mismatch');need(c['age']==(lt[0]+rob_entries-s['head'])%rob_entries<s['rob_count'],'choice age/live mismatch');need(owner['first_seen']<=a,'choice predates live owner')
    if c['prechecked']:need(c['prepared_match'] and c['va']is not None and c['pa']is not None and c['size']in range(4) and s['satp']>>60==8,'load permission/VA/PA mode mismatch')
    else:need(c['va']is None and c['pa']is None and c['size']is None,'unprepared payload fabricated')
   stores=s['stores'];need(s['selected'] or not stores,'stores attributed to unselected load');seen_stores=set();waiting_load=False
   for q in stores:
    st=token(q['token']);need(st in owners and st not in seen_stores,'store wrong full-generation/duplicate token');seen_stores.add(st);owner=owners[st]
    need(owner['memory'] and owner['store'] and owner['first_seen']<=a,'store lineage/class');need(q['age']==(st[0]+rob_entries-s['head'])%rob_entries<c['age'],'older store age/order')
    need(bool(q['sources_known'])==bool(q['pending']),'pending readiness scope')
    ready_keys=('registered_ready1','registered_ready2','prf_ready1','prf_ready2','source1','source2')
    if q['sources_known']:
     need(owner['sources_known'] and q['source1']==owner['source1'] and q['source2']==owner['source2'],'source identity corruption');need(q['registered_ready1']==q['prf_ready1'] and q['registered_ready2']==q['prf_ready2'],'registered/PRF readiness corruption')
    else:need(all(q[k]is None for k in ready_keys),'inactive ready/source payload read')
    need(q['prepared']==0 or q['address_known']==1,'prepared store without address');need((q['va']is not None)==bool(q['address_known']) and (q['safe_raw_range']is not None)==bool(q['address_known']),'unknown VA/raw range fabricated')
    cert=s['certificate'];need(bool(q['certificate_match'])==bool(cert and token(cert['token'])==st),'canonical full-token match corruption')
    if q['certificate_match']:need(not q['pending'] and cert['epoch']==s['epoch'],'unissued store borrowed canonical permission')
    need(q['first_seen']==owner['first_seen'],'store allocation timing corruption')
    for k in ('first_address_known','first_prepared','first_capture','accepted_start'):
     v=q[k];need(v is None or type(v)is int and owner['first_seen']<=v<=a,'store lifecycle timing '+k)
    if q['address_known']:need(q['first_address_known']is not None,'known address lacks registered transition')
    if q['prepared']:need(q['first_prepared']is not None,'prepared lacks registered transition')
    if q['pending']:need(q['accepted_start']is None,'pending store already accepted')
    need(bool(q['is_head'])==(q['age']==0),'store head classification')
    for z in q['preceding_live_loads']:
     zt=token(z);need(zt in owners and owners[zt]['memory'] and not owners[zt]['store'] and not owners[zt]['atomic'] and (zt[0]+rob_entries-s['head'])%rob_entries<q['age'],'preceding live load full-token/order')
    if q['capture']:need(q['pending'] and not q['killed'] and q['first_capture']is not None,'capture lacks live owner')
    for p in q['data_producers']:
     pt=token(p['token']);need(q['pending'] and not q['registered_ready2'] and pt in owners,'data producer scope/identity');po=owners[pt];need(p['age']==(pt[0]+rob_entries-s['head'])%rob_entries<q['age'] and po['writes_rd'] and p['destination']==po['destination']==q['source2'],'data producer full-token/destination lineage')
     if po['memory'] and p['memory_live'] and not po['store'] and not po['atomic'] and not po['move_alias']:waiting_load=True;producer_counts[(pt,st)]+=cycles
    if c['prechecked']:
     pair_counts[(lt,st)]+=cycles;store_counts[(q['pending'],q['address_known'],q['prepared'],q['registered_ready1'],q['registered_ready2'],q['certificate_match'])]+=cycles
   if s['selected'] and c['prechecked']:
    dimensions['selected_prechecked']+=cycles;p=[q for q in stores if q['pending']]
    flags={'multiple_older_stores':len(stores)>1,'unissued_older_store':bool(p),'some_rs1_not_ready':any(q['sources_known'] and not q['registered_ready1'] for q in p),'some_rs2_not_ready':any(q['sources_known'] and not q['registered_ready2'] for q in p),'some_address_not_captured':any(not q['address_known'] for q in p),'some_store_not_prepared':any(not q['prepared'] for q in p),'some_unissued_address_known':any(q['address_known'] for q in p),'some_unissued_prepared':any(q['prepared'] for q in p),'rs2_matches_older_live_load_destination':waiting_load,'capture_inflight':any(q['capture'] for q in stores),'other_older_uncanonical_memory':bool(s['older_other_uncanonical'])}
    for k,v in flags.items():
     if v:dimensions[k]+=cycles
    if s['bin']not in witnesses and stores:witnesses[s['bin']]={'begin':a,'end':b,'state':s,'owner_metadata':{str(t):owners[t] for t in {lt,*seen_stores}}}
 need(terminal is not None,'supplement terminal missing')
 need(terminal['sequence']==n and terminal['roi_first']==first and terminal['roi_end']==cursor and terminal['roi_cycles']==cursor-first and terminal['spans']==spans and terminal['owners']==len(owners),'terminal count/interval conservation')
 need(summary['schema']==1 and summary['roi_first']==first and summary['roi_end']==cursor and summary['roi_cycles']==cursor-first and summary['spans']==spans and summary['owners']==len(owners),'summary/sidecar conservation')
 need(summary['exclusive_bins']==[bins[i]for i in range(10)] and summary['canonical_bins']==[original[i]for i in range(9)] and summary['overlapping_dimensions']==dict(dimensions),'summary classification/dimensions mismatch')
 need(summary['predicted_savings']is None,'observer cannot predict savings')
 if result is not None:need(summary['roi_cycles']==result['roi']['cycles'],'original ROI changed')
 if canonical is not None:need(summary['canonical_bins']==canonical['stalls'] and summary['samples']==canonical['samples'],'original canonical outcomes changed')
 return {'status':'PASS_EXACT_FULL_TOKEN_PASSIVE_CLASSIFICATION','summary':summary,'exclusive_bin_names':BIN_NAMES,'store_cycle_dimensions_overlap':[{ 'pending':k[0],'address_known':k[1],'prepared':k[2],'ready1':k[3],'ready2':k[4],'certificate_match':k[5],'store_cycles':v}for k,v in store_counts.items()],'unique_load_store_pairs':len(pair_counts),'unique_waiting_load_store_pairs':len(producer_counts),'witnesses':witnesses,'no_summed_predicted_savings':True,'source1_ready_does_not_authorize_translation':True,'safe_raw_range_is_not_physical_permission':True}
