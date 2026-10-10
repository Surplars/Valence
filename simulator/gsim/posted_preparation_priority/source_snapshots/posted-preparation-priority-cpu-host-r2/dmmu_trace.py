import json
from collections import Counter
from admission_trace import need
def validate(path,text,result=None):
 rows=[json.loads(l)for l in open(path)];summ=[r for r in rows if r['event']=='summary'];need(len(summ)==1 and rows[-1]is summ[0],'D summary missing/duplicate');summary=summ[0]
 logs=[json.loads(l.split(' ',1)[1])for l in text.splitlines()if l.startswith('D_TRANSLATION_ADMISSION ')];need(logs==summ,'D log/trace summary mismatch')
 counts={'all':Counter(),'roi':Counter()};seq=0;owner=None;started=False;delays=[];contexts=Counter();last_edge=0
 for r in rows[:-1]:
  need(r['event']=='translation' and r['edge']>last_edge,'D event order/type');last_edge=r['edge']
  rq,rs,ws=r['request'],r['response'],r['walk_start']
  need((r['pa']is not None)==bool(rs),'D invalid response payload')
  need((r['va']is not None)==bool(rq or ws or (rs and not rq)),'D invalid VA payload')
  if rq:
   need(owner is None and r['id']==seq+1,'D duplicate/missing request ID');seq+=1
   need(r['service']==0 and bool(r['fast'])==bool(rs) and r['active_mode']==bool(r['mode']!=0 and r['privilege']!=3),'D request state/mode')
   if r['roi']:contexts[(r['mode'],r['privilege'])]+=1
   if not rs:need(r['active_mode'],'D inactive delayed request');owner=r;started=False
  if ws:need(owner is not None and not started and r['id']==owner['id'] and r['va']==owner['va'] and r['service']==1 and r['walker']==0,'D walk owner/state');started=True
  if rs and not rq:
   need(owner is not None and started and r['id']==owner['id'] and r['va']==owner['va'] and r['service']==2,'D reply owner/state');delays.append({'id':r['id'],'va':r['va'],'request_edge':owner['edge'],'response_edge':r['edge'],'cycles':r['edge']-owner['edge'],'request_roi':owner['roi'],'response_roi':r['roi']});owner=None;started=False
  need(not r['prechecked_ingress']or not rq,'D prechecked bypass demanded translation')
  for k in ['all']+(['roi']if r['roi']else []):
   c=counts[k];c['requests']+=rq;c['responses']+=rs;c['tlb_hits']+=bool(rq and rs and r['active_mode']);c['identity_fast']+=bool(rq and rs and not r['active_mode']);c['delayed_starts']+=bool(rq and not rs);c['delayed_replies']+=bool(rs and not rq);c['walk_starts']+=ws;c['prechecked_ingress_bypass']+=r['prechecked_ingress'];c['checked_prechecked_success']+=r['checked_prechecked_success'];c['walk_faults']+=bool(rs and (r['page_fault']or r['access_fault']))
 need(owner is None,'D final demand undrained')
 for k,c in counts.items():
  for n,v in c.items():need(summary[k][n]==v,'D counts mismatch '+k+'.'+n)
 a=summary['all'];r=summary['roi'];need(a['requests']==a['responses'] and a['delayed_starts']==a['delayed_replies']==a['walk_starts'],'D whole conservation');need(r['requests']+summary['roi_carry_in']==r['responses']+summary['roi_carry_out'],'D ROI carry conservation')
 if result:need(r['cycles']==result['roi']['cycles'],'D ROI cycles mismatch')
 latency=Counter(x['cycles']for x in delays if x['request_roi'] and x['response_roi'])
 return {'status':'PASS_D_ONLY_TRANSLATION_DEMAND_CONSERVATION','summary':summary,'roi_request_contexts':[{'mode':k[0],'privilege':k[1],'requests':v}for k,v in contexts.items()],'roi_complete_delayed_latency_histogram':dict(latency),'roi_delayed_latency_sum':sum(k*v for k,v in latency.items()),'delayed_requests':delays,'interpretation':'Demand translation handshakes, TLB hits and walk starts are D-side source-bound. Service/walker busy cycles overlap cache and processor waits and are not standalone CPI attribution. Internal prechecked ingress bypass and later checked authorization are distinct stages; no same-edge owner join. No PTE backing-read/cache-hit counters in this scope.'}
