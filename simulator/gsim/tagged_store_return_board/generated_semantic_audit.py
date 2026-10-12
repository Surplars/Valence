#!/usr/bin/env python3
"""Read-only, fail-closed binding of real ON FIR/header/CPP to the frozen host."""
import argparse,hashlib,json,re
from pathlib import Path
import legacy_temporary_binding as legacy
HERE=Path(__file__).resolve().parent
sha=legacy.sha
def check(v,why):
 if not v:raise ValueError(why)
def context(modules,path):
 m='BoardSocGsim'
 for i in path:m=modules[m]['instances'][i]
 return m
def trace(modules,sink,target):
 chain=[];seen=set()
 def walk(path,symbol):
  key=(tuple(path),symbol);check(key not in seen,('alias loop',key));seen.add(key)
  absolute='.'.join([*path,symbol]);chain.append(absolute)
  if absolute==target:return
  info=modules[context(modules,path)]
  first,sep,rest=symbol.partition('.')
  if sep and first in info['instances']:return walk(path+[first],rest)
  choices=[(l,r) for l,r,_ in info['connects'] if symbol==l or symbol.startswith(l+'.') or symbol.startswith(l+'[')]
  if choices:
   # Prefer the most-specific sink, and its final connect, retaining bulk suffix.
   length=max(len(l) for l,r in choices);l,r=[x for x in choices if len(x[0])==length][-1]
   return walk(path,r+symbol[len(l):])
  if symbol in info['nodes']:
   rhs=info['nodes'][symbol]['expression']
   if re.fullmatch(r'[A-Za-z_$][\w$]*(?:[.\[\]\w$])*',rhs):return walk(path,rhs)
  raise ValueError(('cannot establish exact passive alias',absolute,target,chain))
 walk([],sink);return chain

def audit(baseline,candidate,host):
 # Only the router's changed admission expression is replaced, by its actual
 # downstream cache request valid. Remaining six old temporary sinks are exact.
 legacy.ROOTS=[r for r in legacy.ROOTS if r[0]!='board.platform.platformRouter']
 old=legacy.binding(baseline);new=legacy.binding(candidate);preserved={}
 for field,b in old.items():
  n=new[field]
  eq={'path':b['instance_path']==n['instance_path'],'module':b['fir_module']==n['fir_module'],'sink':b['sink']==n['sink'],
      'connections':[(l,r)for l,r,_ in b['sink_connections']]==[(l,r)for l,r,_ in n['sink_connections']],
      'nodes':{k:v['expression']for k,v in b['transitive_nodes'].items()}=={k:v['expression']for k,v in n['transitive_nodes'].items()},
      'cpp':b['cpp_assignment']['expression']==n['cpp_assignment']['expression'],
      'width':b['header_declaration']==n['header_declaration']}
  check(all(eq.values()),('original temporary binding requires exact source review',field,eq))
  preserved[field]={'checks':eq,'baseline':b,'candidate':n}
 modules=legacy.fir(candidate/'BoardSocGsim.fir');header=(candidate/'BoardSocGsim.h').read_text()
 cpp='\n'.join(p.read_text() for p in sorted(candidate.glob('BoardSocGsim[0-9]*.cpp')))
 abi=json.loads((HERE/'tagged-abi.json').read_text());abi_results={}
 profile=json.loads((candidate/'profile.json').read_text())
 check(profile==json.loads((HERE/'expected-profile-on.json').read_text()),'complete ON profile changed before ABI binding')
 constants={'cpuTagged$$sbFast',*(f'cpuTagged$$slot{i}$$fastLoad' for i in range(4))}
 check(not profile['core']['fastBufferedStoreRetire'] and not profile['core']['fastHeadLoadRetire'],'constant fast-path observations require exact disabled production flags')
 for field,width in abi.items():
  declarations=re.findall(r'^([^\n]*\b'+re.escape(field)+r';) // width = (\d+),.*$',header,re.M)
  getters=re.findall(r'\bSBoardSocGsim::get_'+re.escape(field)+r'\(\)\s*\{\s*return\s+([^;]+);\s*\}',cpp)
  if not declarations and field in constants:
   check(width==1 and getters==['0x0'],('disabled fast-path getter not exact zero',field,getters))
   abi_results[field]={'bits':1,'getter':'0x0','proof':'Exact old profile keeps fastBufferedStoreRetire and fastHeadLoadRetire disabled; named FIR source alias retained below.'}
   continue
  check(len(declarations)==1 and int(declarations[0][1])==width,('real ON scalar declaration/width absent or ambiguous',field,width,declarations))
  check(getters==[field],('ON getter does not return exact named scalar',field,getters))
  abi_results[field]={'bits':width,'declaration':declarations[0][0],'getter':getters[0]}
 b='board.platform.core.core.core.backend';l=b+'.lsu';a='board.platform.core.adapter';c='board.platform.privateCache'
 ports={'queued':b+'.requests.io.enq','physical':a+'.io.physical.request','physicalReply':a+'.io.physical.response',
        'integerReply':l+'.io.memory.response','sbRequest':b+'.stores.io.memory.request','sbReply':b+'.stores.io.memory.response',
        'cache':c+'.io.upstream.request','cacheReply':c+'.io.upstream.response','backendRequest':b+'.io.memory.request','backendReply':b+'.io.memory.response'}
 aliases={}
 for n,path in ports.items():
  for f in ['valid','ready','handle']:
   aliases['cpuTagged.'+n+'.'+f]=path+('.bits.returnHandle' if f=='handle' else '.'+f)
 for n,field in [('cacheSelected','responseSelected'),('cacheOldestHit','headHitAvailable'),('cacheStoreWrite','storeWrite'),('cachePostedIntent','postedIntent')]:aliases['cpuTagged.'+n]=c+'.'+field
 for i in range(2):
  aliases['cpuTagged.cacheHandle'+str(i)]=c+'.responseHandle['+str(i)+']'
  aliases['cpuTagged.cacheKind'+str(i)]=c+'.responseKind['+str(i)+']'
 for i in range(4):
  s=l+'.slots_'+str(i)
  for out,field in [('live','io.busy'),('fastLoad','io.fastLoadRetire'),('index','io.owner.index'),('tag','io.owner.tag'),('cancel','io.cancel'),('discard','io.discarded'),('completeIndex','io.complete.bits.token.index'),('completeTag','io.complete.bits.token.tag'),('tval','io.complete.bits.tval'),('exception','io.complete.bits.exception'),('cause','io.complete.bits.cause')]:aliases['cpuTagged.slot'+str(i)+'.'+out]=s+'.'+field
 for out,field in [('startSlot','chosen'),('startVa','io.start.bits.address'),('startPa','io.start.bits.physicalAddress'),('startData','io.start.bits.data'),('startSize','io.start.bits.size')]:aliases['cpuTagged.'+out]=l+'.'+field
 aliases['cpuTagged.sbFast']=b+'.stores.fastEnqueue'
 aliases.update({'backendStartIndex':l+'.io.start.bits.token.index','backendStartTag':l+'.io.start.bits.token.tag','backendRequestIndex':l+'.io.requestOwner.bits.index','backendRequestTag':l+'.io.requestOwner.bits.tag','cpuTagged.fpIndex':b+'.systemOwner.index','cpuTagged.fpTag':b+'.systemOwner.tag','cpuTagged.fpCompleteIndex':b+'.systemComplete.bits.token.index','cpuTagged.fpCompleteTag':b+'.systemComplete.bits.token.tag'})
 proven={sink:trace(modules,sink,target) for sink,target in aliases.items()}
 platform=modules[context(modules,['board','platform'])]
 connects=[(l,r)for l,r,_ in platform['connects'] if l=='privateCache.io.upstream']
 check(connects and connects[-1]==('privateCache.io.upstream','platformRouter.io.memory'),'cache request valid is not exact actual platformRouter memory request valid')
 hostfiles={str(p.relative_to(host)):sha(p) for p in sorted((host).rglob('*')) if p.is_file()}
 frozen=json.loads((HERE/'host-manifest.json').read_text())
 for name,digest in hostfiles.items():check(frozen['files']['host/'+name]==digest,('frozen host changed before binding',name))
 boot=(host/'harness/board_boot.cpp').read_text();schedule=['ddr.drive(*dut, cycles);','fabric.drive(*dut,cycles);','dut->step();','fabric.sample(*dut,cycles);','if (observer) observer(*dut, observerContext);','ddr.sample(*dut);']
 indices=[boot.index(x)for x in schedule];check(indices==sorted(indices),'original observer sampling phase changed')
 return {'status':'PASS_TAGGED_GENERATED_BINDING','preserved_temporary_sinks':preserved,'router_alias':connects[-1],
         'abi':abi_results,'exact_source_aliases':proven,'host_sha256':hostfiles,'sampling_schedule':schedule,
         'fir_sha256':{'baseline':sha(baseline/'BoardSocGsim.fir'),'candidate':sha(candidate/'BoardSocGsim.fir')},
         'header_sha256':sha(candidate/'BoardSocGsim.h'),'limits':['Static binding only; no DUT runtime or performance claim.','Different original temporary semantics or missing new aliases requires review; never guess a generated suffix.']}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--host',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 report=audit(a.baseline,a.candidate,a.host);a.output.write_text(json.dumps(report,indent=2)+'\n');print(report['status'],len(report['abi']),'scalar fields',len(report['exact_source_aliases']),'source aliases')
