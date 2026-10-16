#!/usr/bin/env python3
"""All sequential data/enable/reset roots plus reconstructed hint; no STA claim."""
import argparse,collections,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('mapped',type=Path);p.add_argument('--classification-width',type=int,required=True);p.add_argument('--no-wide',action='store_true');a=p.parse_args()
m=json.loads(a.mapped.read_text())['modules']['ClassifiedNextLineQueue'];drivers={};roots={}
for n,v in m['ports'].items():
 if v['direction']=='input':
  for i,b in enumerate(v['bits']):roots[b]={'kind':'input','name':f'{n}[{i}]'}
seq={};comb={'LUT1','LUT2','LUT3','LUT4','LUT5','LUT6','MUXF7','MUXF8','MUXF9','CARRY4','INV'}
for name,c in m['cells'].items():
 t=c['type']
 if t=='$scopeinfo':assert not c.get('connections');continue
 assert t in comb|{'FDRE','FDSE','FDCE','FDPE'},(name,t)
 if t not in comb:seq[name]=c
 for port,bits in c['connections'].items():
  if c['port_directions'][port]=='output':
   for i,b in enumerate(bits):
    assert b not in drivers;drivers[b]=(name,c,port,i)
    if t not in comb:roots[b]={'kind':'FF_Q','name':name,'type':t}
head=m['ports']['io_headStored']['bits'];tail=m['ports']['io_tailStored']['bits']
assert len(head)==len(tail)
summary=set((head[-a.classification_width:]+tail[-a.classification_width:]) if a.classification_width else [])
groups=collections.defaultdict(list)
for n,c in seq.items():
 for port,bits in c['connections'].items():
  if c['port_directions'][port]=='input' and port!='C':
   for b in bits:
    key='all_D' if port=='D' else ('all_enable' if port in ('CE','EN','E') else 'all_reset_set')
    groups[key].append((n+'.'+port,b))
    if port=='D' and any(q in summary for q in c['connections']['Q']):groups['classification_D'].append((n+'.D',b))
groups['downstream_hint']=[('io_deq_bits_request_prefetchNextAllowed',m['ports']['io_deq_bits_request_prefetchNextAllowed']['bits'][0])]
memo={};prev={};active=set();fcache={}
def predecessors(b):
 if not isinstance(b,int) or b in roots:return []
 assert b in drivers;n,c,port,i=drivers[b];co=c['connections'];t=c['type']
 if t=='CARRY4':
  k=i+1 if port=='CO' else i;return list(dict.fromkeys(co['CI']+co['CYINIT']+co['DI'][:k]+co['S'][:k]+(co['S'][i:i+1] if port=='O' else [])))
 return list(dict.fromkeys(x for p,bs in co.items() if c['port_directions'][p]=='input' for x in bs))
def walk(b):
 if b in memo:return memo[b]
 assert b not in active;active.add(b);ps=predecessors(b)
 if not ps:v=0
 else:
  best=max(ps,key=walk);prev[b]=best;v=walk(best)+1
 active.remove(b);memo[b]=v;return v
def frontier(b):
 if b in fcache:return fcache[b]
 ps=predecessors(b)
 if not ps:r=[(0,0,0)]
 else:
  t=drivers[b][1]['type'];assert t.startswith('LUT') or t in ('CARRY4','INV')
  unit=(int(t.startswith('LUT')),int(t=='CARRY4'),int(t=='INV'));vs=set()
  for q in ps:
   for v in frontier(q):vs.add(tuple(x+y for x,y in zip(v,unit)))
  r=[]
  for v in sorted(vs,reverse=True):
   if not any(all(x>=y for x,y in zip(k,v)) for k in r):r.append(v)
 fcache[b]=r;return r
result={'mapped_sha256':hashlib.sha256(a.mapped.read_bytes()).hexdigest(),'stored_width':len(head),'FF':len(seq),'classification_D_roots':len(groups['classification_D']),'groups':{}}
for group,targets in groups.items():
 if not targets:continue
 label,b=max(targets,key=lambda x:walk(x[1]));v=walk(b);types=[];end=b
 while end in prev:types.append(drivers[end][1]['type']);end=prev[end]
 x={'roots':len(targets),'max_primitive_count':v,'witness_endpoint':label,'witness_source':roots.get(end,{'kind':'constant','value':end}),'witness_census':dict(collections.Counter(types)),'witness_sequence':list(reversed(types))}
 if a.no_wide:
  vs={v for _,b in targets for v in frontier(b)};r=[]
  for v in sorted(vs,reverse=True):
   if not any(all(x>=y for x,y in zip(k,v)) for k in r):r.append(v)
  x['all_path_frontier_LUT_CARRY4_INV']=r
 result['groups'][group]=x
result['semantics']='Unweighted conservative primitive connectivity. All FF data/enable/reset/set roots included; clocks excluded. LUT35..165ps, CARRY4 and INV remain symbolic;77ps launch only where independently justified as FF_Q. No finite route/WNS/Fmax bound.'
a.mapped.with_suffix('.analysis.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
