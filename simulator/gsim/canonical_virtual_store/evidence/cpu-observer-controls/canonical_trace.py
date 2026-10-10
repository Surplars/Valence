"""Validate exact-token event-sidecar conservation. Performance witnesses are optional measurements."""
import json
from collections import Counter
from contract import require,sha
def validate(path,text,side,roi):
 lines=[x for x in text.splitlines()if x.startswith('CANONICAL_OVERLAP ')]
 require(len(lines)==1,'canonical summary absent/duplicated');s=json.loads(lines[0].split(' ',1)[1])
 require(s['roi_samples']==roi and sum(s['occupancy'])==roi and sum(s['stalls'])==roi,'canonical exclusive ROI bins do not conserve')
 for name in ('accepted_upstream_occupancy','accepted_physical_occupancy'):
  rows=s[name];require(sum(x['cycles']for x in rows)==roi and len({(x['known'],x['unknown'])for x in rows})==len(rows) and all(set(x)=={'known','unknown','cycles'} and all(type(v)is int and v>=0 for v in x.values())for x in rows),'accepted owner histogram conservation '+name)
 require(len(s['barrier_bins'])==4 and sum(s['barrier_bins'])==roi,'cache barrier bins do not conserve ROI')
 require(len(s['load_cache_barrier_relation'])==5 and s['load_cache_barrier_relation'][2]==0,'young cache acceptance crossed store miss barrier')
 require(len(s['occupancy'])==5 and len(s['stalls'])==9 and s['final_owner_queues']==0,'canonical bins/drain shape')
 counts=Counter();overlaps=Counter();certs={};usable=set();edges={};n=0
 with open(path)as f:
  for line in f:
   x=json.loads(line);n+=1;event=x['event'];counts[event]+=1
   require(event in {'lsu_start','upstream_accept','physical_accept','real_response','checked_certificate','record_usable','load_prepared','choice_selected','cache_accept','cache_response','cache_barrier_begin','cache_barrier_end'},'unknown canonical event')
   require(type(x['known'])is int and x['known']in (0,1),'known must be explicit')
   token=(x.get('token_index'),x.get('token_tag'))
   if x['known']:require(0<=token[0]<16 and 0<=token[1]<1<<64 and 0<=x['epoch']<1<<32,'full token/epoch range')
   else:require(not x['eligible_overlap'],'unknown owner cannot establish overlap')
   if event=='checked_certificate':
    require(x['known'] and x['store'],'certificate source class');certs[token]=x
   if event=='record_usable':
    require(token in certs and certs[token]['cycle']<x['cycle'] and certs[token]['epoch']==x['epoch'] and certs[token]['pa']==x['pa'] and certs[token]['va']==x['va'] and certs[token]['size']==x['size'] and certs[token]['mask']==x['mask'],'record usable without prior exact capture');usable.add(token)
   if x['eligible_overlap']:
    store=(x['store_index'],x['store_tag']);require(side=='on'and event in {'lsu_start','upstream_accept','physical_accept','cache_accept'} and store in usable,'illegal overlap witness')
    c=certs[store];require(all(x[k]==1 for k in ('store_live','store_serial','store_request_accepted_known','store_request_accepted','store_class','context_stable')) and x['store_slot']in range(4) and (x['head_index'],x['head_tag'])==store==(x['protected_index'],x['protected_tag']) and x['current_epoch']==x['epoch'],'overlap exact serial protected head facts')
    require(x['known'] and not x['store'] and x['prechecked'] and c['epoch']==x['epoch']==x['store_epoch'] and x['store_real_response_pending']==1,'overlap identity/response mismatch')
    require(c['pa']==x['store_pa']and c['mask']==x['store_mask']and((x['pa']>>3)!=(c['pa']>>3)or not(x['mask']&c['mask'])),'overlap physical alias')
    overlaps[event]+=1;edges.setdefault(token,{})[event]=x['cycle']
 require(counts['checked_certificate']==s['certificate_captures'],'certificate event count')
 for event,key in [('lsu_start','lsu_start_overlap'),('upstream_accept','upstream_overlap'),('physical_accept','physical_overlap'),('cache_accept','cache_overlap')]:require(overlaps[event]==s[key],'overlap count mismatch '+event)
 if side=='off':require(not counts['checked_certificate']and not counts['record_usable']and not sum(overlaps.values()),'OFF canonical proof observed')
 return {'schema':'canonical-overlap-events-v1','events':n,'counts':dict(counts),'overlaps':dict(overlaps),'full_three_boundary_tokens':sum({'lsu_start','upstream_accept','physical_accept'}.issubset(v)for v in edges.values()),'summary':s,'path':str(path),'sha256':sha(path),'causality':'exact full-token registered certificate, serial accepted live slot, protected head, current epoch, disjoint byte lanes, actual real response not yet visible; ordered passive FIFO correlation','timing_or_area_qualified':False}
