"""Independent strict event joins. Occupancy and retrospective PA never imply permission."""
import collections,json
from pathlib import Path
from contract import require,sha

def decode(line):
 def pairs(items):
  require(len({k for k,v in items})==len(items),'duplicate proof JSON key');return dict(items)
 return json.loads(line,object_pairs_hook=pairs)
def token(x):
 require(type(x['index'])is int and 0<=x['index']<64 and type(x['tag'])is int and 0<=x['tag']<2**64,'proof fulltoken index6/tag64')
 require(type(x['epoch'])is int and 0<=x['epoch']<2**32,'proof epoch32')
 return x['index'],x['tag'],x['epoch']
def identity(x):return (*token(x),x['va'],x['size'])
def validate(path,canonical_path,text,result,window):
 summaries=[decode(l.split(' ',1)[1])for l in text.splitlines()if l.startswith('MEMORY_PROOF_FRONTIER ')]
 require(len(summaries)==1,'proof summary absent/duplicate');s=summaries[0]
 a,b=result['roi']['begin_offer'],result['roi']['end_offer'];require(s['roi_first']==a and s['roi_end']==b and s['cycles']==b-a,'proof exact primary ROI')
 require(s['token_index_bits']==6 and s['token_tag_bits']==64 and s['epoch_bits']==32 and s['acceptance_confirmed_by_next_sample']is True,'proof ABI/edge contract')
 for k in ('reserved','allowed','bound','credit'):
  h=s[k+'_histogram'];require(len(h)==17 and all(type(v)is int and v>=0 for v in h) and sum(h)==b-a,'proof credit histogram '+k)
 require(sum(s['grants_selected_candidate_scan_write'][:3])<=b-a,'payload read grant cap')
 event_count=0;qhistory=collections.defaultdict(list);terminal=None;last=-1;counts=collections.Counter();queries={};proofs={};starts={};starts_by_token=collections.defaultdict(list);frontiers={};ar=[];axi_live=collections.defaultdict(collections.deque);tl=[];demands=[];rows={};unknown=[];tl_live={};other=[];other_live=collections.deque();fetch=[];pf=[];spans=[];raw_hist={k:[0]*17 for k in ('reserved','allowed','bound','credit')};raw_grants=[0]*4;stage_bits=[0]*48;backend_bits=[0]*48;stage_hist={k:collections.Counter()for k in ('occupancy','supply','capture','rename','discard','translation_phase')}
 accepted_events={'admission','query','result','frontier','start','demand_alloc','refill','tl_a','axi_ar','pf_alloc','other_request','other_response','fetch_request'}
 with Path(path).open()as f:
  for line in f:
   x=decode(line);require(terminal is None and x['sequence']==event_count,'proof sequence or data after terminal');c=x['cycle'];require(type(c)is int and c>=last,'proof chronological gap/order');last=c
   if x['event']=='terminal':terminal=x;continue
   event_count+=1;e=x['event']
   if e in accepted_events:require(x['offer_cycle']==c and x['accepted_cycle']==c+1,'acceptance must be confirmed following edge')
   if e in ('query','result','frontier','start','admission'):
    k=identity(x);require(0<=x['va']<2**64 and 0<=x['size']<=3,'query payload geometry')
   if e=='admission':require(0<=x['row']<16 and x['write']in (0,1),'admission credit/access schema')
   elif e=='query':
    queries[k]=x;qhistory[k].append(x)
    if x['roi']:counts['queries']+=1;counts['query_hits']+=bool(x['hit'])
    if x['hit']:require(x['hitepoch']==x['epoch'] and 0<=x['hitpa']<2**64,'query response identity')
   elif e=='result':
    if x['roi']:counts['results']+=1;counts['inserted']+=bool(x['inserted'])
    q=queries.get(k)
    if x['inserted']:
     require(q is not None and q['accepted_cycle']<=x['accepted_cycle'],'inserted proof missing earlier same-owner query')
     require(x['allowed'] and x['ownermatches'] and x['reservation'] and q['hit'] and q['hitpa']==x['pa'] and q['hitpbmt']==0,'inserted proof not actual positive permission')
     require(q['write']==x['write'] and (x['va']&4095)==(x['pa']&4095),'proof access/page offset changed')
     proofs[k]=x
   elif e=='frontier':
    require(x['accepted'],'frontier event not actual accepted grant');p=proofs.get(k)
    require(p is not None and p['pa']==x['pa'] and p['write']==x['write']==0 and p['accepted_cycle']<=x['accepted_cycle'],'frontier lacks same full proof')
    frontiers[(k,x['accepted_cycle'])]=x
   elif e=='start':
    require(k not in starts,'duplicate start full token/epoch');starts[k]=x;starts_by_token[k[:2]].append(x)
    if x['roi']:counts['frontier_starts'if x['frontier']else'original_starts']+=1
    if x['frontier']:
     f=frontiers.get((k,x['accepted_cycle']))
     require(f is not None and f['pa']==x['pa'] and x['parallel'] and x['prechecked'] and not x['store'] and not x['atomic'],'actual frontier/start proof tuple differs')
   elif e=='demand_alloc':demands.append(x)
   elif e=='pf_alloc':pf.append(x)
   elif e=='other_request':
    other.append({**x,'end':None});other_live.append(other[-1])
   elif e=='other_response':
    require(other_live,'other physical response without accepted request');other_live.popleft()['end']=c+1
   elif e=='fetch_request':fetch.append(x)
   elif e=='span':
    st=x['state'];require(len(st)==23 and x['begin']<x['end'],'proof span schema')
    require(not spans or spans[-1]['end']==x['begin'],'proof context sample gap/overlap');spans.append(x)
    require(st[4]+st[5]<=16 and st[6]<=st[5] and sum(st[7:10])<=1,'proof span credit/read-grant bound')
    if st[0]:
     require(a<=x['begin']<x['end']<=b,'proof span wrong ROI');n=x['end']-x['begin']
     for key,value in zip(('reserved','allowed','bound','credit'),(st[4],st[5],st[6],st[4]+st[5])):raw_hist[key][value]+=n
     for i in range(4):raw_grants[i]+=n*st[7+i]
     for i in range(48):stage_bits[i]+=n*((st[15]>>i)&1);backend_bits[i]+=n*((st[22]>>i)&1)
     for key,value in zip(stage_hist,st[16:22]):stage_hist[key][value]+=n
   elif e=='tl_a':
    require(x['source']not in tl_live,'TL acquire source reused while outstanding')
    rec={**x,'beats':0,'first_response_visible':None,'end':None};tl.append(rec);tl_live[x['source']]=rec
   elif e=='tl_d_visible':
    if x['source']in tl_live:
     owner=tl_live[x['source']];require(x['size']==owner['size'],'TL response shape mismatch')
     require(x['opcode']==(5 if owner['opcode']==6 else 4),'TL grant opcode mismatch')
     if owner['first_response_visible']is None:owner['first_response_visible']=c
     if x['ready']:
      owner['beats']+=1
      if owner['beats']==(8 if x['opcode']==5 else 1):owner['end']=c+1;del tl_live[x['source']]
    else:require(x['opcode']==6,'TL response without live acquire source')

   elif e=='axi_ar':
    require(0<=x['pa']<2**64 and 0<=x['len']<256 and 0<=x['size']<=3,'external AR geometry')
    require(x['pa']==0x80200000+x['offset'] and x['burst']==1,'external AR aperture/burst mismatch');require(not axi_live[x['id']],'external AR ID reused before last R');record={**x,'first_response_visible':None,'response_end_accepted':None,'accepted_beats':0};ar.append(record);axi_live[x['id']].append(record)
   elif e=='axi_r_visible':
    require(axi_live[x['id']],'external R lacks exact accepted ID owner');owner=axi_live[x['id']][0]
    if owner['first_response_visible']is None:owner['first_response_visible']=c
    if x['ready']:
     owner['accepted_beats']+=1;require(bool(x['last'])==(owner['accepted_beats']==owner['len']+1),'external RLAST/declared beats mismatch')
     if x['last']:owner['response_end_accepted']=c+1;axi_live[x['id']].popleft()
   elif e=='line_state':
    require(0<=x['slot']<4,'LSU line slot bound')
    if x['valid']:
     matching=starts_by_token.get((x['index'],x['tag']),[])
     require(len(matching)==1 and matching[0]['accepted_cycle']<=c and matching[0]['prechecked'] and matching[0]['pa']&~63==x['pa_line'],'LSU live line lacks accepted exact start tuple')
     # context_epoch is diagnostic; owner epoch is only the saved accepted start epoch.
   elif e=='row_state':
    require(0<=x['row']<16,'row bound')
    if x['valid']:token(x);require(x['state']in (1,2) and (not x['bound']or x['state']==2),'row state/bound');rows[x['row']]=x
    else:rows.pop(x['row'],None)
   else:require(e=='refill','unknown proof event')
 require(terminal and terminal['roi_first']==a and terminal['roi_end']==b and terminal['roi_cycles']==b-a,'proof terminal coverage')
 require(not any(axi_live.values()),'external AR owners not terminally drained')
 require(not rows,'proof rows did not terminally drain')
 require(not tl_live and not other_live,'TL/other physical owners not drained')
 for k,v in raw_hist.items():require(s[k+'_histogram']==v,'proof raw span/summary histogram mismatch '+k)
 require(raw_grants==s['grants_selected_candidate_scan_write'],'proof raw span/summary grants mismatch')
 for k in ('queries','query_hits','results','inserted','frontier_starts','original_starts'):require(s[k]==counts[k],'proof summary/event counter mismatch '+k)
 # Canonical logger supplies independent ordered start->cache-response ownership.
 # Its cache_accept cycle is a fire offer, confirmed by this new trace at c+1.
 lives=[]
 for line in Path(window['load_lifetimes']['path']).open():
  l=decode(line);ca=l.get('cache_accept');st=l.get('lsu_start')
  if not ca or not ca['ordinary'] or not ca['miss']:continue
  require(st is not None,'ordinary miss no start');k=(st['token_index'],st['token_tag'],st['epoch'],st['va'],st['size']);new=starts.get(k)
  require(new is not None and new['accepted_cycle']==st['cycle']+1,'independent canonical/start edge mismatch')
  require(new['pa']==ca['pa']if new['prechecked']else True,'cache full PA differs from start proof')
  accepted=ca['cycle']+1;visible=ca['first_response_visible'];linepa=ca['pa']&~63
  # DemandAlloc is an actual cache event on the same fire; missing/ambiguous joins remain unknown.
  ds=[z for z in demands if z['accepted_cycle']==accepted and z['pa']==ca['pa']]
  ts=[z for z in tl if z['pa']&~63==linepa and accepted<=z['accepted_cycle']<visible and z['opcode']==6 and z['size']==6]
  ars=[z for z in ar if z['pa']&~63==linepa and accepted<=z['accepted_cycle']<visible]
  if len(ds)!=1 or len(ts)!=1 or len(ars)!=1:
   unknown.append(dict(token=list(k[:3]),cache_accept=accepted,reason='external demand join missing or ambiguous',demand_matches=len(ds),tl_matches=len(ts),ar_matches=len(ars)));continue
  ext=ars[0];tr=ts[0]
  occupied=[i for i,pa in enumerate(tr['mshr_pa'])if pa is not None and pa&~63==linepa]
  interfering_other=[z for z in other if z['pa']&~63==linepa and z['accepted_cycle']<visible and (z['end']is None or z['end']>=accepted)]
  interfering_fetch=[z for z in fetch if z['pa']&~63==linepa and z['accepted_cycle']<visible]
  interfering_pf=[z for z in pf if z['pa']&~63==linepa and accepted<=z['accepted_cycle']<visible]
  # Earlier outstanding same-PA external owners or TL sources also make an address join ambiguous.
  overlapping_ar=[z for z in ar if z['pa']&~63==linepa and z['accepted_cycle']<visible and z['response_end_accepted']>=accepted]
  overlapping_tl=[z for z in tl if z['pa']&~63==linepa and z['accepted_cycle']<visible and (z['end']is None or z['end']>=accepted)]
  if occupied!=[ds[0]['slot']] or tr['mshr_pf']>>ds[0]['slot']&1 or interfering_other or interfering_fetch or interfering_pf or len(overlapping_ar)!=1 or len(overlapping_tl)!=1 or ext['len']!=7 or ext['size']!=3 or ext['pa']!=linepa or ext['accepted_beats']!=8 or tr['beats']!=8:
   unknown.append(dict(token=list(k[:3]),reason='same-PA PF/other-master/PTW, source ownership, or complete burst shape not uniquely excluded'));continue
  if not(accepted<=tr['accepted_cycle']<=ext['accepted_cycle']<visible and ext['first_response_visible']is not None):
   unknown.append(dict(token=list(k[:3]),reason='external ordering/first response unknown'));continue
  # Unique actual line transaction within this exact outstanding request interval,
  # no aggregate bus occupancy or hypothetical early translation is used.
  lives.append(dict(token=k[:3],va=new['va'],size=new['size'],pa=ca['pa'],line=linepa,start=new,cache_accept=accepted,cache_first_response_visible=visible,external=ext,tl=tr,proof=proofs.get(k)))
 witnesses=[];fallback=0;eligible=0
 for old in lives:
  if not a<=old['cache_accept']<b:continue
  scope=old['start']['prechecked'] and old['start']['parallel'] and not old['start']['ishead']
  if scope:eligible+=1
  else:fallback+=1
  if not scope:continue
  first=min(old['cache_first_response_visible'],old['external']['first_response_visible'])
  for new in lives:
   if new['token'][1]<=old['token'][1] or new['line']==old['line'] or new['token'][2]!=old['token'][2] or not new['start']['frontier']:continue
   if not(old['external']['accepted_cycle']<new['external']['accepted_cycle']<first and old['cache_accept']<new['cache_accept']<first):continue
   k=(*new['token'],new['va'],new['size']);p=new['proof'];q=queries.get(k)
   # Keep the specific proof's earlier query. Later retries cannot substitute history.
   qs=[x for x in qhistory[k] if x['accepted_cycle']<=p['accepted_cycle'] and x['hit'] and x['hitpa']==p['pa']] if p else []
   if not p or not qs:unknown.append(dict(token=list(new['token']),reason='proof query history missing'));continue
   q=max(qs,key=lambda x:x['accepted_cycle'])
   require(q['accepted_cycle']<=p['accepted_cycle']<=new['start']['accepted_cycle']<=new['cache_accept']<=new['external']['accepted_cycle']<first,'demand witness sequence')
   witnesses.append(dict(old_token=list(old['token']),new_token=list(new['token']),old_line=old['line'],new_line=new['line'],query=q['accepted_cycle'],allowed=p['accepted_cycle'],start=new['start']['accepted_cycle'],cache_accept=new['cache_accept'],external_ar=new['external']['accepted_cycle'],old_cache_accept=old['cache_accept'],old_external_ar=old['external']['accepted_cycle'],old_first_response_visible=first,old_cache_first_response_visible=old['cache_first_response_visible'],old_external_first_response_visible=old['external']['first_response_visible'],old_tl_first_response_visible=old['tl']['first_response_visible'],external_ids=[old['external']['id'],new['external']['id']],actual_external_distinct_transactions=True))
 return dict(status='STRUCTURAL_WITNESS'if witnesses else'NO_STRUCTURAL_WITNESS',structural_status='STRUCTURAL_WITNESS_PRESENT'if witnesses else'STRUCTURAL_WITNESS_ABSENT',summary=s,witness_count=len(witnesses),witnesses=witnesses,matched_misses=len(lives),eligible_prechecked_nonhead_old_misses=eligible,excluded_serial_or_head_old_misses=fallback,old_frozen_reference=dict(prechecked_windows=2015,fallback_excluded=32,total_windows=2047,cycles=197740,counts_not_imposed_on_candidate=True),unknown=unknown,external_join='unique full-PA read demand allocation, non-PF live MSHR, unique outstanding TL A source, complete eight-beat AXI AR/R shape and order; home/PTW/DMA/bypass and fetch same-PA requests excluded; any ambiguity UNKNOWN',legacy_cross_boundary_join='UNKNOWN: preserve canonical [a+1,b+1) vs window [a,b); no end sample synthesized',stage_utilization=dict(perf_event_cycles=stage_bits,backend_event_cycles=backend_bits,histograms={k:dict(v)for k,v in stage_hist.items()},bit_definitions='exact frozen wrapper perfEvents/backendEvents Seq ordering; overlapping causes are not summed'),raw={str(path):sha(path),str(canonical_path):sha(canonical_path)})
