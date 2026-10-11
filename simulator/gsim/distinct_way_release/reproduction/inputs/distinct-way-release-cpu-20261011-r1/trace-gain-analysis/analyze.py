#!/usr/bin/env python3
"""Read-only analysis of frozen originals. Never extracts archive members or runs a DUT."""
import collections, hashlib, json, pathlib, statistics, tarfile, resource, bisect

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
ARCHIVE = HERE.parent / 'distinct-way-release-case19-on-20261011-r1.tar.gz'
ARCHIVE_SHA = '07b773b388402e60632961c8dccde5c92982081cbb9bb55178b789eb0ed908c2'
BASE = ROOT / 'same-set-prefetch-admission-observer-20261011-r1/case19-on-r1'
BASE_RECEIPT = ROOT / 'posted-preparation-priority-cpu-host-r2/case19-on-r1/receipt.json'
ON_RECEIPT = HERE.parent / 'case19/qualification.json'
NAMES = ('lru', 'proof', 'canonical', 'owners', 'admission')
EVENTS = {
 'lru': {'allocation','refill','tl_c','tl_d','axi_aw','touch'},
 'proof': {'pf_alloc','demand_alloc','tl_a','axi_ar','refill'},
 'canonical': {'lsu_start','upstream_accept','cache_accept','physical_accept'},
 'admission': {'decision'},
}

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
 return h.hexdigest()

def read_stream(f, kind, first, end):
 rows=[]; h=hashlib.sha256(); count=0; size=0; kinds=collections.Counter(); cburst=[]
 for raw in f:
  h.update(raw);size+=len(raw);count+=1
  d=json.loads(raw);r=d.get('owner',d);e=r.get('event');kinds[str(e)]+=1
  c=r.get('cycle',r.get('edge',0))
  if kind=='lru' and e=='tl_c':
   cburst.append(d);head=cburst[0];n=8 if head['opcode'] in (5,7) else 1
   assert all(d[k]==head[k] for k in ('opcode','source','pa','size','param')) and not d['corrupt']
   if len(cburst)==n:
    if first-512<=head['cycle']<end+512:rows.append({'event':'tl_c_message','first':head['cycle'],'last':d['cycle'],'source':head['source'],'pa':head['pa'],'opcode':head['opcode'],'size':head['size'],'beats':n,'sequences':[head['sequence'],d['sequence']]})
    cburst=[]
   continue
  if not first-512<=c<end+512 or kind=='owners' or e not in EVENTS[kind]:continue
  if kind=='canonical':
   if not d.get('known') or d.get('store') or d.get('atomic'):continue
   d={k:d[k] for k in ('event','cycle','known','token_index','token_tag','epoch','pa','va','store','atomic','cache_ordinary','cache_request_found') if k in d}
  elif kind=='admission':
   if not d.get('allocate'):continue
   d={k:d[k] for k in ('event','edge','candidate_address','store','slot','index','id','source_seq','source_address')}
  elif kind=='lru':
   if e=='touch' and d['kind']!='install':continue
   d={k:v for k,v in d.items() if k not in ('data',)}
  rows.append(d)
 assert not cburst
 return rows,{'sha256':h.hexdigest(),'bytes':size,'rows':count,'event_counts':dict(kinds)}

def load(side, receipt):
 first=receipt['result']['roi']['begin_offer'];end=receipt['result']['roi']['end_offer']
 data={}; hashes={}
 if side=='on':
  assert sha(ARCHIVE)==ARCHIVE_SHA
  manifest=json.loads((HERE.parent/'case19-on-archive-manifest.json').read_text())['members']
  with tarfile.open(ARCHIVE,'r|gz') as t:
   for m in t:
    kind=next((k for k in NAMES if m.name.endswith('/positive.'+k+'.jsonl')),None)
    if kind is None:continue
    data[kind],hashes[kind]=read_stream(t.extractfile(m),kind,first,end)
    assert hashes[kind]['sha256']==manifest[m.name]['sha256']
    assert hashes[kind]['bytes']==manifest[m.name]['bytes']
 else:
  for kind in NAMES:
   p=BASE/('positive.'+kind+'.jsonl')
   with p.open('rb') as f:data[kind],hashes[kind]=read_stream(f,kind,first,end)
   assert hashes[kind]['sha256']==receipt['artifacts'][p.name]
 assert set(data)==set(NAMES)
 return data,hashes

def only(xs, label):
 assert len(xs)==1,(label,len(xs),xs[:2])
 return xs[0]

def stat(xs):
 return {'count':len(xs),'sum':sum(xs),'min':min(xs),'max':max(xs),'mean':statistics.mean(xs),'histogram':dict(sorted(collections.Counter(xs).items()))}

def index(rows,key):
 out=collections.defaultdict(list)
 for r in rows:out[key(r)].append(r)
 return out

def analyze(data,receipt):
 lru=data['lru'];proof=data['proof'];first=receipt['result']['roi']['begin_offer'];end=receipt['result']['roi']['end_offer']
 pf=[r for r in lru if r['event']=='allocation' and first<=r['offer_cycle']<end]
 demands=[r for r in proof if r['event']=='demand_alloc']
 allocs=[r for r in proof if r['event'] in ('demand_alloc','pf_alloc')]
 pfs=[r for r in proof if r['event']=='pf_alloc']
 aa=[r for r in proof if r['event']=='tl_a']
 ar=[r for r in proof if r['event']=='axi_ar']
 refill=[r for r in lru if r['event']=='refill']
 grant=[r for r in lru if r['event']=='tl_d' and r['opcode']==5]
 canon=collections.defaultdict(list)
 for r in data['canonical']:canon[(r['event'],r['cycle'])].append(r)
 token_events=collections.defaultdict(dict)
 for r in data['canonical']:
  if r.get('known'):token_events[(r['token_index'],r['token_tag'],r['epoch'])][r['event']]=r
 # Full C bursts were verified as a stream, before ROI filtering.
 messages=[r for r in lru if r['event']=='tl_c_message']
 demand_ix=index(demands,lambda r:(r['pa']>>6)&255)
 refill_ix=index(refill,lambda r:r['pa'])
 aa_ix=index(aa,lambda r:r['pa'])
 ar_ix=index(ar,lambda r:r['pa'])
 pf_ix=index(pfs,lambda r:r['accepted_cycle'])
 c_ix=index(messages,lambda r:r['pa'])
 grant_ix=index(grant,lambda r:r['source'])
 grant_cycles={k:[r['cycle'] for r in rs] for k,rs in grant_ix.items()}
 touch_ix=index([r for r in lru if r['event']=='touch'],lambda r:r['index'])
 ack_ix=index([r for r in lru if r['event']=='tl_d' and r['opcode']==6],lambda r:r['source'])
 aw_ix=index([r for r in lru if r['event']=='axi_aw'],lambda r:r['pa'])
 dec_ix=index(data['admission'],lambda r:r['edge'])
 groups=[]
 for num,p in enumerate(pf):
  pc=p['cycle'];pa=p['address'];s=p['slot'];setid=p['set'];vw=p['victim_way'];other=1-vw
  nxt=pf[num+1]['cycle'] if num+1<len(pf) else end+1
  assert p['store']==1
  pr=only([r for r in refill_ix[pa] if r['slot']==s and r['prefetch'] and pc<=r['cycle']<nxt],'PF refill')
  pal=only([r for r in pf_ix[pc] if r['slot']==s and r['pa']==pa],'PF allocation')
  a=only([r for r in aa_ix[pa] if pc<=r['accepted_cycle']<=pr['cycle']],'PF A')
  # Cache MSHR tag and engine A source are independently recorded and may differ.
  assert a['mshr_pf']&(1<<s) and a['mshr_pa'][s]==pa
  gc=grant_cycles[a['source']]
  ds=grant_ix[a['source']][bisect.bisect_left(gc,a['accepted_cycle']):bisect.bisect_right(gc,pr['cycle'])]
  assert len(ds)==8 and all(r['denied']==r['corrupt']==0 for r in ds)
  dm=only([r for r in demand_ix[setid] if (r['pa']&~63)!=pa and pc<=r['accepted_cycle']<nxt],'ordinary same-set demand')
  dr=only([r for r in refill_ix[dm['pa']] if r['slot']==dm['slot'] and not r['prefetch'] and dm['accepted_cycle']<=r['cycle']<nxt],'demand refill')
  assert dr['index']==setid+other*256 and pr['index']==p['victim_index']
  ca=only([r for r in canon[('cache_accept',dm['offer_cycle'])] if r['pa']==dm['pa']],'full demand cache owner')
  assert ca['known'] and ca['cache_ordinary'] and not ca['store'] and not ca['atomic'] and not ca['cache_request_found']
  token=(ca['token_index'],ca['token_tag'],ca['epoch']); stages=token_events[token]
  assert all(e in stages for e in ('lsu_start','upstream_accept','cache_accept','physical_accept'))
  assert stages['cache_accept']['cycle']==stages['physical_accept']['cycle']==dm['offer_cycle']
  assert stages['lsu_start']['cycle']<=stages['upstream_accept']['cycle']<=dm['offer_cycle']
  v=p['ways'][other];assert v['valid'] and v['dirty'] and v['pa']!=pa
  c=only([r for r in c_ix[v['pa']] if r['opcode']==7 and dm['accepted_cycle']<=r['first']<=dr['cycle']],'ordinary dirty C')
  assert not any(pc<r['cycle']<=c['last'] for r in touch_ix[dr['index']])
  da=only([r for r in aa_ix[dm['pa']&~63] if dm['accepted_cycle']<=r['accepted_cycle']<=dr['cycle']],'demand A')
  assert not (da['mshr_pf']&(1<<dm['slot'])) and da['mshr_pa'][dm['slot']]==dm['pa']
  dar=only([r for r in ar_ix[dm['pa']&~63] if da['accepted_cycle']<=r['accepted_cycle']<=dr['cycle']],'demand AR')
  par=only([r for r in ar_ix[pa] if a['accepted_cycle']<=r['accepted_cycle']<=pr['cycle']],'PF AR')
  dec=only([r for r in dec_ix[pc] if r['candidate_address']==pa],'PF admission')
  assert dec['store'] and dec['slot']==s and dec['index']==p['victim_index']
  ack=only([r for r in ack_ix[c['source']] if c['last']<r['cycle']<=dr['cycle']],'dirty ReleaseAck')
  aw=only([r for r in aw_ix[c['pa']] if c['last']<r['cycle']<=ack['cycle']],'dirty AW')
  g={'pf_line':pa,'set':setid,'pf_way':vw,'pf_mshr':s,'pf_engine_source':a['source'],'pf_candidate_id':dec['id'],'pf_source_sequence':dec['source_seq'],'pf_source_address':dec['source_address'],'pf_allocation_edge':pc,'pf_A_edge':a['accepted_cycle'],'pf_AR_edge':par['accepted_cycle'],'pf_D_first':ds[0]['cycle'],'pf_D_last':ds[-1]['cycle'],'pf_refill_edge':pr['cycle'],'demand_token':list(token),'demand_line':dm['pa']&~63,'demand_way':other,'demand_mshr':dm['slot'],'demand_engine_source':da['source'],'demand_lsu_start_offer':stages['lsu_start']['cycle'],'demand_upstream_offer':stages['upstream_accept']['cycle'],'demand_accept_edge':dm['accepted_cycle'],'demand_refill_edge':dr['cycle'],'demand_A_edge':da['accepted_cycle'],'demand_AR_edge':dar['accepted_cycle'],'victim_line':v['pa'],'C_first':c['first'],'C_last':c['last'],'C_source':c['source'],'C_beats':c['beats'],'C_sequences':c['sequences'],'dirty_AW_edge':aw['cycle'],'dirty_ReleaseAck_edge':ack['cycle'],'next_pf_or_roi_end':nxt,'full_demand_owner_bound':True,'different_way_bound':True,'C_before_PF_final_D':c['last']<ds[-1]['cycle'],'C_before_PF_first_D':c['last']<ds[0]['cycle'],'PF_E_direct':'UNKNOWN_NO_E_EVENT'}
  groups.append(g)
 assert len(groups)==2015
 metrics={}
 for name,a,b in [('demand_accept_minus_pf_allocation','demand_accept_edge','pf_allocation_edge'),('C_first_minus_pf_A','C_first','pf_A_edge'),('C_last_minus_pf_D_last','C_last','pf_D_last'),('dirty_AW_minus_pf_D_last','dirty_AW_edge','pf_D_last'),('demand_AR_minus_pf_AR','demand_AR_edge','pf_AR_edge'),('demand_refill_minus_pf_allocation','demand_refill_edge','pf_allocation_edge'),('pf_refill_minus_pf_allocation','pf_refill_edge','pf_allocation_edge'),('group_span','next_pf_or_roi_end','pf_allocation_edge')]:metrics[name]=stat([g[a]-g[b] for g in groups])
 return groups,{'groups':len(groups),'full_demand_token_bound':len(groups),'different_way_full_line_bound':len(groups),'complete_8beat_dirty_C':len(groups),'C_last_before_PF_D_last':sum(g['C_before_PF_final_D'] for g in groups),'C_last_before_PF_D_first':sum(g['C_before_PF_first_D'] for g in groups),'demand_accept_before_PF_D_last':sum(g['demand_accept_edge']<g['pf_D_last'] for g in groups),'metrics':metrics,'witnesses':groups[:3]+groups[-1:]}

def main():
 resource.setrlimit(resource.RLIMIT_AS,(256*1024*1024,256*1024*1024))
 baseline=json.loads(BASE_RECEIPT.read_text());on=json.loads(ON_RECEIPT.read_text());out={'schema':'distinct-way-release-historical-trace-gain-v1','scope':'Fresh distinctWayRelease ON versus pinned historical baseline; no fresh current-source OFF claim. Read-only original traces; no DUT/compiler/new observer.','inputs':{},'runs':{}}
 allg={}
 for side,receipt in [('baseline',baseline),('on',on)]:
  data,hs=load(side,receipt);g,s=analyze(data,receipt);allg[side]=g;out['inputs'][side]=hs;out['runs'][side]=s
  del data
  print(side,json.dumps({k:v for k,v in s.items() if k not in ('witnesses','metrics')}),flush=True)
 bg=allg['baseline'];ng=allg['on']
 assert [(g['pf_line'],g['demand_line'],g['victim_line'],g['set'],g['pf_way'],g['demand_way'],g['demand_token']) for g in bg]==[(g['pf_line'],g['demand_line'],g['victim_line'],g['set'],g['pf_way'],g['demand_way'],g['demand_token']) for g in ng]
 out['cross_run_full_identity_equal']=True
 gain=baseline['result']['ticks']-on['result']['ticks']
 pre_b=bg[0]['pf_allocation_edge']-baseline['result']['roi']['begin_accepted'];pre_n=ng[0]['pf_allocation_edge']-on['result']['roi']['begin_accepted']
 spans=[(b['next_pf_or_roi_end']-b['pf_allocation_edge'])-(n['next_pf_or_roi_end']-n['pf_allocation_edge']) for b,n in zip(bg,ng)]
 assert pre_b-pre_n+sum(spans)==gain
 out['accounting']={'observed_kernel_gain':gain,'roi_prefix_delta':pre_b-pre_n,'nonoverlapping_group_span_delta':stat(spans),'identity':'prefix delta + sum(nonoverlapping matching PF allocation-to-next-allocation spans, final span ending at ROI accepted end) = kernel gain; all boundaries use accepted-cycle coordinates','causal_attribution':'Temporal accounting only; group span changes are not an additive prediction of saved cycles or exclusive causal proof.'}
 out['unknown']=['No TL E event, E sink, or direct E cycle in the original sidecars. C completion before matched PF final D is a sufficient bound for C-before-PF-E under the pinned acquire-engine semantics.','PF raw records carry candidate/source sequence, PA, MSHR and cache way; no independent PF CPU token or MSHR generation field. Generation reuse is disambiguated by exact allocation/A/refill episode.','C has full victim PA and release source, but no explicit causative MSHR/cohort token. Binding uses the unique ordinary-demand episode, matching dirty opposite-way snapshot, exact later refill way and absence of an intervening install.','The separate posted owner trace does not create a posted cohort for ordinary demand or store-prefetch owners.','No new DDR latency hiding/reduction conclusion: fixed-volume read service counters are unchanged.','Inherited cross-interval external ownership join remains UNKNOWN; no boundary shift is used to fabricate events.']
 out['provenance']={'archive':str(ARCHIVE),'archive_sha256':ARCHIVE_SHA,'baseline_receipt_sha256':sha(BASE_RECEIPT),'on_qualification_sha256':sha(ON_RECEIPT),'script_sha256':sha(pathlib.Path(__file__)),'source_semantics':{'acquire_engine':'distinct-way-release-implementation-20261011-r1/source/src/main/scala/ip/tilelink/TileLinkLineAcquireEngine.scala:56,98-147 (non-flow acknowledgement queue enqueued on final accepted D; E thereafter)','lru_observer':'store-prefetch-lru-victim-cpu-host-r1/lru_victim_observer.hpp (accepted-cycle equals offer+1)','canonical_and_proof':'canonical cycle and proof offer_cycle are offers; join on exact offer then report explicit accepted_cycle'}}
 out['resources']={'address_space_limit_bytes':256*1024*1024,'peak_RSS_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
 (HERE/'analysis.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
 print(json.dumps(out['accounting']),flush=True)

if __name__=='__main__':main()
