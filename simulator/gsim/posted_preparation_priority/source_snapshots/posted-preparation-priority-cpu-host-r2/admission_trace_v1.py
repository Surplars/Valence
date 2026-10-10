import json
from collections import Counter
GATES=['posted_not_allowed','pf_live','pf_release','present','set_reserved','victim_pending','dirty_read_victim','no_free_mshr','demand_offered','barrier','flush_active','flush_request','bypass_busy','probe_busy','tl_b_valid','eviction_busy','queued_eviction']
GEN=['no_history','not_sequential','hint_false','posted_not_allowed','candidate_live','pf_live','pf_release','tracked_read_unconsumed','tracked_store_unconsumed','candidate_emitted']
def need(x,m):
 if not x:raise ValueError(m)
def next_address(a):return (a&~4095)|((((a>>6)+1)&63)<<6)
def flags(s):
 block=s['tracked_valid'] and s['tracked_present'] and not s['consume']
 return {'no_history':not s['last_valid'],'not_sequential':not s['sequential'],'hint_false':not s['hint'],'posted_not_allowed':not s['posted_allowed'],'candidate_live':bool(s['candidate_valid']),'pf_live':bool(s['pf_live']),'pf_release':bool(s['pf_release']),'tracked_read_unconsumed':block and not s['tracked_store'],'tracked_store_unconsumed':block and bool(s['tracked_store']),'tracked_consume':bool(s['consume']),'tracked_invalidated':s['tracked_valid'] and not s['tracked_present']}
def genbin(s):
 f=flags(s)
 for i,k in enumerate(GEN[:-1]):
  if f[k]:return i
 return 9
def check_state(s):
 need((s['address']is not None)==bool(s['cache_valid']),'invalid request payload')
 need((s['last_line']is not None)==bool(s['last_valid']),'invalid history payload')
 for k in ['tracked_address','tracked_index','tracked_store']:need((s[k]is not None)==bool(s['tracked_valid']),'invalid tracked payload '+k)
 need(s['consume']==bool(s['cache_valid'] and s['cache_ready'] and s['ordinary'] and s['tracked_valid'] and s['address']//64==s['tracked_address']//64),'consume mismatch')
 need(s['available']==bool(s['posted_allowed'] and not s['candidate_valid'] and not s['pf_live'] and not s['pf_release'] and (not s['tracked_valid'] or s['consume'] or not s['tracked_present'])),'candidateAvailable mismatch')
 for i in range(3):
  z=(s['origin']>>(2*i))&3;need(z!=3 and bool(z)==bool((s['events']>>i)&1),'event source mismatch')
def validate(path,text,result=None):
 rows=[json.loads(l)for l in open(path)];summ=[r for r in rows if r['event']=='summary'];need(len(summ)==1 and rows[-1]is summ[0],'missing/duplicate summary');summary=summ[0]
 logs=[json.loads(l.split(' ',1)[1])for l in text.splitlines()if l.startswith('READ_PREFETCH_ADMISSION ')];need(logs==summ,'trace/log summary mismatch')
 reads={};cand={};dec={};wit={};seen_seq=set();last_read=None;counts={k:{'reads':0,'candidate':[0,0],'allocate':[0,0],'generation_bins':[0]*10,'allocation_exclusive':[0]*18,'allocation_overlapping':[0]*17}for k in ['all','roi']};dims=Counter();seqdims=Counter();cross=Counter();decision_cross=Counter();last_edge=0
 for r in rows[:-1]:
  e=r['event'];need(e in ['read_accept','candidate','decision','allocation_witness','tracked_release'],'unknown event');need(r['edge']>=last_edge,'event edge reorder');last_edge=r['edge']
  if 'offer'in r:need(r['edge']==r['offer']+1,'not next accepted edge')
  if e in ['read_accept','decision']:check_state(r)
  if e=='read_accept':
   seq=r['source_seq'];need(seq>0 and seq not in seen_seq,'duplicate read source sequence');seen_seq.add(seq);reads[seq]=r
   need(r['cache_valid'] and r['cache_ready'] and r['ordinary'] and not r['write'],'not accepted ordinary read')
   sequential=bool(r['last_valid'] and r['address']//64==r['last_line']+1 and r['address']//64!=0);need(r['sequential']==sequential,'wrong sequence classification')
   if last_read is not None and r['last_valid']:need(r['last_line']==last_read['address']//64,'wrong read history full address')
   last_read=r;need(r['bin']==genbin(r),'read generation bin mismatch');need(bool(r['origin']&1)==(r['bin']==9),'read candidate omitted/added')
   for k in ['all']+(['roi']if r['roi']else []):counts[k]['reads']+=1;counts[k]['generation_bins'][r['bin']]+=1
   if r['roi']:
    ff=flags(r)
    for k,v in ff.items():dims[k]+=bool(v);seqdims[k]+=bool(v and r['sequential'] and r['hint'])
    cross[(r['bin'],bool(r['sequential']),bool(r['hint']),r['tracked_store'] if r['tracked_valid']else None)]+=1
  elif e=='candidate':
   i=r['id'];need(i==len(cand)+1 and i not in cand,'missing/duplicate/reordered candidate id');need(r['source_seq']>0,'candidate lacks source sequence');need(r['address']==next_address(r['source_address']),'candidate wrong next address');cand[i]=r
   if not r['store']:
    need(r['source_seq']in reads,'read candidate missing accepted source');q=reads[r['source_seq']];need(q['offer']==r['offer'] and q['address']==r['source_address'] and q['origin']&1,'read candidate wrong source')
   for k in ['all']+(['roi']if r['roi']else []):counts[k]['candidate'][r['store']]+=1
  elif e=='decision':
   i=r['id'];need(i in cand and i not in dec,'unknown/duplicate decision');q=cand[i];need(not q['cancelled_on_emit'],'decision for cancelled candidate');need(r['offer']==q['offer']+1 and r['emitted_offer']==q['offer'],'candidate decision not exact next offer');need(all(r[a]==q[b]for a,b in [('source_seq','source_seq'),('source_address','source_address'),('candidate_address','address'),('store','store')]),'candidate decision wrong source/address');need(r['candidate_valid'],'decision has no valid candidate')
   g=r['gates'];need(len(g)==17 and all(x in [0,1]for x in g),'gate shape');ex=next((i for i,x in enumerate(g)if x),17);need(r['exclusive']==ex and r['allocate']==(ex==17),'allocation exclusive/gates mismatch');need(bool(r['origin']&12)==bool(r['allocate']) and (not r['allocate']or bool(r['origin']&8)==bool(r['store'])),'allocation event/origin mismatch');need((r['slot']is not None)==bool(r['allocate']),'invalid allocation slot')
   need(r['index']<512 and (r['index']&255)==(r['candidate_address']//64&255),'wrong PF victim set');need(len(r['way_valid'])==len(r['way_dirty'])==len(r['way_tag'])==2,'way shape')
   for w in range(2):need((r['way_tag'][w]is not None)==bool(r['way_valid'][w]) and (r['way_valid'][w]or not r['way_dirty'][w]),'invalid candidate way payload')
   w=r['index']//256;need(r['victim_valid']==r['way_valid'][w] and r['victim_dirty']==r['way_dirty'][w],'wrong selected victim');va=(r['way_tag'][w]<<14)|((r['index']&255)<<6)if r['victim_valid']else None;need(r['victim_address']==va,'wrong victim address')
   present=0x80200000<=r['candidate_address']<0x100200000 and any(r['way_valid'][w] and r['way_tag'][w]==(r['candidate_address']>>14)&0x7ffff for w in range(2))
   need([bool(g[i])for i in [0,1,2,3,6,11,15,16]]==[not r['posted_allowed'],bool(r['pf_live']),bool(r['pf_release']),bool(present),bool(r['victim_valid'] and r['victim_dirty'] and not r['store']),bool(r['flush']),r['eviction_state']!=0,bool(r['queued_eviction'])],'allocation raw-state gates mismatch')
   need(r['victim_tracked_index_match']==bool(r['tracked_valid'] and r['tracked_index']==r['index']) and r['victim_tracked_address_match']==bool(r['tracked_valid'] and r['victim_valid'] and r['tracked_address']==va),'tracked victim relation mismatch');dec[i]=r
   for k in ['all']+(['roi']if r['roi']else []):
    counts[k]['allocate'][r['store']]+=r['allocate'];counts[k]['allocation_exclusive'][ex]+=1
    for j,v in enumerate(g):counts[k]['allocation_overlapping'][j]+=v
   if r['roi']:decision_cross[(r['store'],ex,r['victim_valid'],r['victim_dirty'],r['victim_tracked_address_match'],r['tracked_store'])]+=1
  elif e=='allocation_witness':
   i=r['id'];need(i in dec and dec[i]['allocate'] and i not in wit,'missing/duplicate allocation event');q=dec[i];need(r['edge']==q['edge'] and r['phase']in [1,2] and all(r[k]==q[k]for k in ['slot','index','store']) and r['address']==q['candidate_address'],'wrong post-edge allocation ownership');wit[i]=r
  elif e=='tracked_release':need(r['consume']or r['invalidated']or r.get('flush'),'tracked release lacks cause')
 for i,q in cand.items():need(q['cancelled_on_emit']or i in dec,'missing candidate decision')
 need(set(wit)=={i for i,q in dec.items()if q['allocate']},'missing allocation witness')
 need(sum(bool(q['origin']&1)for q in reads.values())==sum(not q['store']for q in cand.values()),'missing read candidate event')
 for k in ['all','roi']:
  for n,v in counts[k].items():need(summary[k][n]==v,'summary mismatch '+k+'.'+n)
 need(summary['predicted_savings']is None,'no predicted savings')
 if result is not None:
  r=result['roi'];need(summary['roi']['cycles']==r['cycles'],'ROI cycle mismatch')
  for n in ['candidate','allocate']:
   stem='allocated'if n=='allocate'else n;need(summary['roi'][n]==[r[stem+'_read'],r[stem+'_store']],'original PF count changed')
 return {'status':'PASS_STRICT_NEXT_EDGE_CANDIDATE_OWNERSHIP','summary':summary,'read_generation_bins':dict(zip(GEN,summary['roi']['generation_bins'])),'read_overlapping_dimensions':dict(dims),'sequential_hint_true_overlapping_dimensions':dict(seqdims),'allocation_exclusive_bins':dict(zip(GATES+['allocated'],summary['roi']['allocation_exclusive'])),'allocation_overlapping_dimensions':dict(zip(GATES,summary['roi']['allocation_overlapping'])),'generation_cross':[{'bin':GEN[k[0]],'sequential':k[1],'hint':k[2],'tracked_store':k[3],'reads':v}for k,v in cross.items()],'candidate_victim_cross':[{'store_origin':k[0],'exclusive':(GATES+['allocated'])[k[1]],'victim_valid':k[2],'victim_dirty':k[3],'victim_matches_tracked_address':k[4],'tracked_store':k[5],'candidates':v}for k,v in decision_cross.items()]}
