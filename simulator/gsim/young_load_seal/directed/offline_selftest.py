#!/usr/bin/env python3
"""Synthetic host-ledger mutation tests, NOT CPU evidence or DUT simulation."""
import copy,json
from pathlib import Path
from prepare_guest import authored,interpret,BASE
from analyze_trace import validate,Failure
OUT=Path(__file__).resolve().parent
manifest=json.loads((OUT/'guest-manifest.json').read_text())
code,labels=authored();trace,ops,final=interpret(code);opmap={m['pc']:m for m in ops};opmap[labels['killed_load']]=manifest['killed_load']

def synthetic():
 events=[];bound=set();cycle=1;members={};active=None;serial=10
 ordinals={e['pc']:n for n,e in enumerate(trace)}
 def token(pc):
  if pc==labels['killed_load']:return (ordinals[labels['replacement_load']]%16,5000)
  return (ordinals[pc]%16,1000+ordinals[pc])
 def emit(n,*x):events.append((n,[cycle,*x]))
 def bind(n):
  if n in bound or n>=len(trace):return
  bound.add(n);e=trace[n];idx,tag=token(e['pc']);emit('BIND',idx,tag,e['pc'],e['instruction'],idx,1,0)
 def owner(c,sealed=0,refilled=0,installed=0):emit('OWNER',*c,sealed,refilled,installed,(c[5]>>6)&255,0,0,0,0)
 def sel(pc,headpc,seal):
  t=token(pc);h=token(headpc);m=opmap[pc];emit('SELECT',*t,pc,(t[0]-h[0])%16,*h,headpc,1,1,1,seal,0,0,m['address'],1,0)
 def close():
  nonlocal cycle,active
  if active is None:return
  c=active;owner(c,1);emit('REFILL_OFFER',*c);emit('REFILL_FIRE',*c);cycle+=1
  owner(c,1,1);emit('INSTALL',*c);cycle+=1
  for t,pc,ticket in members[c]:
   owner(c,1,1,1);emit('DRAIN',*t,pc,*c[:6],ticket);cycle+=1
  owner(c,1,1,1);emit('RELEASE',*c);cycle+=1;active=None
 for n,e in enumerate(trace):
  pc=e['pc'];bind(n)
  # Bind actual nearby U/Q ahead, preserving complete tokens. Their synthetic
  # BIND windows are narrow legal snapshots, not simulator coverage.
  if pc in [labels['case0_S0'],labels['case1_S0']]:
   for k in range(n+1,min(n+8,len(trace))):bind(k)
  if e['memory']:
   m=e['intent'];t=token(pc);case=next(c for c in range(3) if (m['address']&~63)==manifest['lines'][c])
   if case<2 and pc==labels[f'case{case}_S1']:
    owner(active);sel(labels[f'case{case}_U'],pc,0);cycle+=1
   if case<2 and pc==labels[f'case{case}_U']:
    owner(active);sel(pc,pc,1)
    if case:sel(labels['case1_Q'],pc,1)
    cycle+=1;close()
   if case<2 and pc==labels[f'case{case}_V']:close()
   if pc==labels['replacement_load']:close()
   emit('START',*t,pc,0,m['address'],m['data'],3,int(m['store']),*t,int(active is not None));cycle+=1
   if m['store']:emit('LOCAL',*t,pc,0)
   emit('REPLY',*t,pc,0 if m['store'] else m['expected'],0);cycle+=1
   emit('COMPLETE',*t,pc);emit('RETIRE',*t,pc,0);cycle+=1
   if m['store']:
    new=active is None
    if new:
     active=(0,serial,0,serial,0,m['address']&~63,0);serial+=1;members[active]=[]
    c=active;ticket=len(members[c])%2
    emit('OFFER',*t,pc,1,1,m['address']);emit('MEMBER',*t,pc,*c,ticket,int(new));members[c].append((t,pc,ticket));cycle+=1
    owner(c);emit('ACK',*t,pc,*c[:6],ticket);cycle+=1
  else:
   if pc==labels['kill_branch']:
    kp=labels['killed_load'];kt=token(kp);emit('BIND',*kt,kp,code[(kp-BASE)//4],kt[0],1,0)
    owner(active);sel(kp,pc,0);cycle+=1
    owner(active);emit('KILL',*kt,kp,1,1,1,1,1);cycle+=1
    owner(active,1);emit('HARD',1,1,token(pc)[0],2);cycle+=1
   emit('RETIRE',*token(pc),pc,0);cycle+=1
 close();emit('FINISH',len(bound),len(ops),len(ops),len(ops),len(trace))
 return events

def rejected(name,rows=None,m=None):
 try:validate(rows if rows is not None else synthetic(),m if m is not None else manifest,'on')
 except (Failure,KeyError,IndexError,ValueError):return {'name':name,'rejected':True}
 raise AssertionError('mutation unexpectedly accepted: '+name)

def mutate(event,col,delta=1):
 rows=copy.deepcopy(synthetic());row=next(x for n,x in rows if n==event);row[col]^=delta;return rows

baseline=validate(synthetic(),manifest,'on')
results=[rejected('full token high tag bit',mutate('MEMBER',2,1<<63)),rejected('owner generation',mutate('ACK',5,1<<63)),rejected('cohort generation',mutate('ACK',7,1<<63)),rejected('response ticket',mutate('ACK',10))]
r=synthetic();next(x for n,x in r if n=='REPLY' and not opmap[x[3]]['store'])[4]^=1;results.append(rejected('load byte',r))
m=copy.deepcopy(manifest);m['final_bytes'][64][1]^=1;results.append(rejected('overwritten final byte',m=m))
m=copy.deepcopy(manifest);m['final_bytes'][0][1]^=1;results.append(rejected('unwritten guard byte',m=m))
r=synthetic();next(x for n,x in r if n=='ACK')[0]=0;results.append(rejected('cause-edge phase',r))
r=synthetic();y=next(x for n,x in r if n=='MEMBER' and x[3]==labels['case0_Y']);early=copy.deepcopy(y);at=next(i for i,(n,x) in enumerate(r) if n=='SELECT');early[0]=r[at][1][0];r.insert(at,('MEMBER',early));results.append(rejected('Y accepted before U retirement',r))
r=synthetic();next(x for n,x in r if n=='SELECT' and x[4]==0)[11]=0;results.append(rejected('head load seal removed',r))
r=synthetic();next(x for n,x in r if n=='SELECT' and x[3]==labels['case1_Q'])[11]=0;results.append(rejected('unselected head load seal removed',r))
r=synthetic();r=[(n,x) for n,x in r if not(n=='SELECT' and x[3]==labels['case1_Q'])];results.append(rejected('missing unselected head coverage',r))
r=synthetic();next(x for n,x in r if n=='KILL')[2]^=1<<63;results.append(rejected('killed old full tag changed',r))
r=synthetic();r=[(n,x) for n,x in r if n!='KILL'];results.append(rejected('missing actual killed-token coverage',r))
result={'status':'PASS_OFFLINE_SYNTHETIC_CONTROLS_ONLY','baseline':baseline,'negative_controls':results,'count':len(results),'cpu_execution':False}
(OUT/'offline-selftest.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
