#!/usr/bin/env python3
"""Independent bounded rename/free policy model, not RTL formal equivalence.
Two writable architectural registers, five physical registers, ROB3, four fresh
allocations, up to nine events. Q can hold any ready pending memory consumer.
"""
from collections import deque
import json
# State: RAT, free, ready, owner versions, ROB entries, next tag, Q(token,sources,versions)
# Entry: token, kind(writer=1,memory=0), rd,dst,old,s1,s2,done
initial=((0,1,2),(3,4),(0,1,2),(0,-1,-2,-3,-4),(),1,None)
def validate(s):
 rat,free,ready,versions,rob,nxt,q=s
 assert 0 not in free
 if q:
  token,sources,oldversions=q
  e=next((e for e in rob if e[0]==token),None)
  assert e is not None and not e[7], 'live descriptor lost owner'
  assert tuple(e[5:7])==sources,'source mapping changed'
  for source,version in zip(sources,oldversions):
   if source:
    assert source not in free,'descriptor source freed'
    assert source in ready,'descriptor source readiness lost'
    assert versions[source]==version,'descriptor physical source reallocated'
def edges(s,bad_commit=False):
 rat,free,ready,vers,rob,nxt,q=s
 def state(rat=rat,free=free,ready=ready,vers=vers,rob=rob,nxt=nxt,q=q):
  return tuple(rat),tuple(sorted(free)),tuple(sorted(ready)),tuple(vers),tuple(rob),nxt,q
 if len(rob)<3 and nxt<=4:
  for rd in (1,2):
   if free:
    dst=min(free);r=list(rat);r[rd]=dst;v=list(vers);v[dst]=nxt
    yield 'rename writer',state(rat=r,free=set(free)-{dst},ready=set(ready)-{dst},vers=v,
      rob=rob+((nxt,1,rd,dst,rat[rd],0,0,False),),nxt=nxt+1)
  yield 'rename memory',state(rob=rob+((nxt,0,0,0,0,rat[1],rat[2],False),),nxt=nxt+1)
 for i,e in enumerate(rob):
  if not e[7]:
   if e[1]:
    if q: assert e[3] not in q[1], 'ready descriptor received producer write again'
    entries=list(rob);entries[i]=e[:-1]+(True,)
    yield 'complete writer',state(ready=set(ready)|{e[3]},rob=entries)
   elif e[5] in ready and e[6] in ready:
    if q is None:
     yield 'capture Q',state(q=(e[0],tuple(e[5:7]),tuple(vers[x] for x in e[5:7])))
    entries=list(rob);entries[i]=e[:-1]+(True,)
    yield 'execute memory',state(rob=entries,q=None if q and q[0]==e[0] else q)
 for i,e in enumerate(rob):
  if (i==0 or bad_commit) and e[7]:
   yield 'commit head' if i==0 else 'NEGATIVE commit younger writer',state(
      free=set(free)|({e[4]} if e[1] else set()),rob=rob[:i]+rob[i+1:])
 for keep in range(len(rob)):
  r=list(rat);f=set(free)
  for e in reversed(rob[keep:]):
   if e[1]:r[e[2]]=e[4];f.add(e[3])
  retained=rob[:keep]
  yield 'recover suffix',state(rat=r,free=f,rob=retained,q=q if q and any(e[0]==q[0] for e in retained) else None)
def run(bad=False):
 todo=deque([(initial,0,[])]);seen={initial};transitions=active=0
 while todo:
  s,depth,path=todo.popleft();validate(s);active+=s[-1] is not None
  if depth==9:continue
  for action,t in edges(s,bad):
   transitions+=1
   try:validate(t)
   except AssertionError as e:
    if not bad:raise
    return dict(status='EXPECTED_COUNTEREXAMPLE',reason=str(e),events=path+[action],state=repr(t),states=len(seen))
   if t not in seen:seen.add(t);todo.append((t,depth+1,path+[action]))
 return dict(status='BOUNDED_POLICY_PASS',states=len(seen),transitions=transitions,active_Q_states=active)
if __name__=='__main__':
 result={'scope':'independent bounded source-lifetime policy model; not RTL formal proof','positive':run(),'negative':run(True)}
 assert result['positive']['active_Q_states']>0 and result['negative']['status']=='EXPECTED_COUNTEREXAMPLE'
 print(json.dumps(result,indent=2))
