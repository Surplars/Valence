#!/usr/bin/env python3
"""Independent exact-token/byte/order/lifecycle validation of actual observations.
DUT event data is evidence only. Guest expectations are recomputed from raw ISA.
Missing directed coverage is a failure, even when architectural bytes pass.
"""
import argparse,json
from collections import defaultdict
from pathlib import Path
from prepare_guest import authored,interpret,initial,BASE

class Failure(AssertionError):pass
def need(v,msg):
 if not v:raise Failure(msg)

def validate(rows,manifest,mode,coverage=True):
 code,labels=authored();trace,ops,final=interpret(code);expected={e['pc']:e for e in trace};memory={m['pc']:m for m in ops}
 killed_spec={'pc':labels['killed_load'],'instruction':code[(labels['killed_load']-BASE)//4],'address':manifest['lines'][2],'data':0,'size':3,'store':False,'expected':0x1122334455667788}
 need(manifest['raw_words']==code and manifest['killed_load']==killed_spec,'raw layout or independent wrong-path intent changed')
 memory[killed_spec['pc']]=killed_spec
 need(manifest['trace']==trace and manifest['memory_operations']==ops,'manifest does not match independent raw ISA interpretation')
 need(manifest['final_bytes']==[[a,b] for a,b in sorted(final.items())],'manifest final-byte mutation')
 bound={};binding_cycle={};by_pc={};start={};local={};reply={};complete={};retire={};members={};acks={};drains={};owners={};reserves={};refill={};install={};release={};offers=defaultdict(list);selection=[];retire_seq=[];retire_tokens=[];kills={};hard_events=[];finish=False
 last_cycle=-1
 for name,x in rows:
  need(bool(x),f'empty event {name}');cy=x[0];need(cy>=last_cycle,'cause-edge phase moved backwards');last_cycle=cy
  if name=='BIND':
   _,idx,tag,pc,raw,head,count,age=x;t=(idx,tag)
   need(0<=idx<16 and 0<count<=16 and (idx-head)%16==age<count,'binding is outside actual live ROB window')
   need(t not in bound,'duplicate full-token binding')
   if pc>=BASE:
    n=(pc-BASE)//4;need(pc%4==0 and (raw==code[n] if n<len(code) else n<len(code)+32 and raw==0x6f),'raw guest PC/instruction mismatch')
   else:need((pc,raw) in [(0x80000000,0x00200297),(0x80000004,0x00028067)],'unknown boot instruction')
   bound[t]=pc;binding_cycle[t]=cy
   if pc in memory:
    need(pc not in by_pc or by_pc[pc] in kills,'live memory PC repeated');by_pc[pc]=t
  elif name in ('START','PROOF','LOCAL','REPLY','COMPLETE','RETIRE','OFFER','MEMBER','ACK','DRAIN'):
   t=tuple(x[1:3]);pc=x[3];need(bound.get(t)==pc,'wrong/stale/high-bit full token or PC')
   if name!='RETIRE':need(pc in memory,'nonmemory full token used as memory')
   m=memory.get(pc)
   for case in range(2):
    if pc==labels[f'case{case}_Y'] and name in ('START','PROOF','OFFER','MEMBER'):
     u=by_pc.get(labels[f'case{case}_U']);need(u in retire and retire[u]<cy,'Y authorized/started/accepted before prior U retirement edge')
   if name=='START':
    need(t not in kills and pc!=killed_spec['pc'],'killed/stale wrong-path load issued')
    need(t not in start,'duplicate full token start');start[t]=cy
    _,_,_,_,slot,addr,data,size,flags,head,headtag,busy=x
    need(addr==m['address'] and size==m['size'] and bool(flags&1)==m['store'] and not flags&6,'actual LSU start vs independent ISA address/size/class')
    if m['store']:need(data==m['data'] and t==(head,headtag),'store data or actual full-token head mismatch')
    else:need(not busy,'load started through posted responsibility')
   elif name=='PROOF':need(m['store'],'load received store proof')
   elif name=='LOCAL':need(t in start and m['store'] and t not in local,'local response lacks exact started store');local[t]=cy
   elif name=='REPLY':
    need(t in start and t not in reply and x[5]==0,'duplicate/early/error reply');reply[t]=cy
    if not m['store']:need(x[4]==m['expected'],'wrong expected load byte')
   elif name=='COMPLETE':need(t in reply and t not in complete,'complete before exact-token response');complete[t]=cy
   elif name=='RETIRE':
    need(t not in retire and t not in kills,'duplicate or killed retire');retire[t]=cy;retire_seq.append(pc);retire_tokens.append(t)
    if m:need(t in complete,'memory retired before exact-token completion')
   elif name=='OFFER':offers[t].append((cy,x[4],x[5],x[6]));need(x[6]==m['address'],'offered cache address differs from ISA')
   elif name=='MEMBER':
    need(t in start and t in local and m['store'] and t not in members,'member lacks original actual/local-completed store')
    c=tuple(x[4:11]);ticket,newline=x[11:13]
    need(c[5]==m['address']&~63,'member context line differs from instruction')
    need(c not in refill,'member admitted after first original refill offer')
    members[t]=(cy,c,ticket,newline)
   elif name in ('ACK','DRAIN'):
    need(t in members,'ACK/drain lacks actual member acceptance');mc,c,ticket,_=members[t]
    need(tuple(x[4:10])==c[:6] and x[10]==ticket,'owner/cohort/epoch/response-ticket mutation')
    need(mc<cy,'member event did not follow acceptance edge')
    if name=='ACK':need(t not in acks,'duplicate ACK');acks[t]=cy
    else:
     need(t in acks and acks[t]<cy and c in install and install[c]<cy and t not in drains,'drain before real ACK/install or duplicate');drains[t]=cy
  elif name=='OWNER':
   c=tuple(x[1:8]);state=tuple(x[8:]);need(len(state)==8,'owner row schema')
   need(c not in release,'released owner reappeared with same full context')
   reserve=tuple(x[11:16]);need(len(reserve)==5,'complete cache reservation schema')
   if c in reserves:need(reserves[c]==reserve,'same full context changed set/way/victim reservation')
   else:reserves[c]=reserve
   owners[(cy,c)]=state
  elif name in ('REFILL_OFFER','REFILL_FIRE','INSTALL','RELEASE'):
   c=tuple(x[1:8]);need((cy,c) in owners,'owner lifecycle event lacks exact live context')
   if name=='REFILL_OFFER':refill.setdefault(c,cy)
   elif name=='REFILL_FIRE':need(c in refill and refill[c]<=cy,'refill fire before valid offer')
   elif name=='INSTALL':need(c in refill and refill[c]<cy and c not in install,'install before refill or duplicate');install[c]=cy
   else:
    owned=[t for t,v in members.items() if v[1]==c];need(owned and all(t in drains and drains[t]<cy for t in owned),'release before exact member drain');release[c]=cy
  elif name=='SELECT':
   _,idx,tag,pc,age,hi,ht,hpc,pending,live,busy,seal,hard,issued,address,ram,denied=x;t=(idx,tag);h=(hi,ht)
   need(bound.get(t)==pc and bound.get(h)==hpc and (idx-hi)%16==age,'selection lost exact live token/head/age')
   need(pc in memory and not memory[pc]['store'] and address==memory[pc]['address'],'selected candidate differs from authored load')
   need(pending and live and busy and not issued,'selected load pending/live/no-start premise missing')
   need(t not in start,'stale issued load remained selected')
   need(t not in kills or kills[t][0]==cy,'killed old full token reselected after recovery edge')
   if hpc in memory and not memory[hpc]['store']:need(seal,'actual selected/unselected head load lost old seal')
   selection.append(x)
  elif name=='KILL':
   _,idx,tag,pc,pending,live,accepted,busy,seal=x;t=(idx,tag)
   need(bound.get(t)==pc and t not in retire and t not in kills,'kill lost original unretired full token')
   need(accepted,'kill without actual accepted recovery')
   if pc==killed_spec['pc']:need(pending and live and busy and t not in start,'designated kill is not a real pending unissued posted-busy load')
   kills[t]=x
  elif name=='HARD':
   need(x[1] and x[2],'real hard cause failed to seal');hard_events.append(x)
  elif name=='FINISH':finish=True
  else:raise Failure(f'unknown event {name}')
 need(finish,'missing functional-finish receipt')
 need(retire_seq==[e['pc'] for e in trace],'retirement differs from raw program order')
 need(len(start)==len(ops)==len(reply)==len(complete),'missing actual memory lifecycle')
 need(all(t in acks and t in drains and v[1] in release and v[1] in reserves for t,v in members.items()),'incomplete member/full-reservation lifecycle')
 # Full-tag index reuse is actual observed rebinding, never low-bit matching.
 tags=defaultdict(set)
 for idx,tag in bound:tags[idx].add(tag)
 reuse=any(len(v)>1 for v in tags.values())
 wrap=any(a[0]==15 and b[0]==0 for a,b in zip(retire_tokens,retire_tokens[1:]))
 killed_observed=[];replacement=by_pc.get(labels['replacement_load'])
 for t,k in kills.items():
  if k[3]!=killed_spec['pc']:continue
  selected=any(tuple(s[1:3])==t and s[0]<=k[0] and s[4]>0 for s in selection)
  same_index=replacement is not None and replacement[0]==t[0] and replacement[1]!=t[1] and binding_cycle[replacement]>k[0] and replacement in start
  old_store=by_pc.get(labels['kill_S0']);owner=members.get(old_store)
  committed_owner=owner is not None and old_store in retire and retire[old_store]<k[0] and (k[0],owner[1]) in owners and owner[1] in release and release[owner[1]]>k[0]
  hard_recovery=any(h[1]&1 and k[0]<=h[0]<release.get(owner[1],0) for h in hard_events) if owner else False
  if selected and same_index and committed_owner and hard_recovery:killed_observed.append(t)
 head_selected=[s for s in selection if s[4]==0 and s[11]]
 head_unselected=[s for s in selection if s[4]>0 and s[7]==labels['case1_U'] and s[3]==labels['case1_Q'] and s[11]]
 c0={l:by_pc.get(labels['case0_'+l]) for l in ['S0','S1','U']};s0,s1,u=[c0[l] for l in ['S0','S1','U']]
 young=[];joined=False;off_discriminates=False
 if s0 in members and s1 in start:
  a,c,_,_=members[s0]
  for s in selection:
   cy=s[0]
   if tuple(s[1:3])!=u or not s[4] or s[12] or not s[15] or s[16]:continue
   st=owners.get((cy,c));
   if not st or any(st[:3]) or (c in refill and refill[c]<=cy):continue
   # Older successor is exact current head, or has really retired but its
   # queued proof has not yet been accepted. Matching PA alone is insufficient.
   is_head=tuple(s[5:7])==s1
   queued=s1 in retire and retire[s1]<cy
   later_member=s1 not in members or members[s1][0]>cy
   if (is_head or queued) and later_member:young.append(s)
  joined=s1 in members and members[s1][1]==c and not members[s1][3] and members[s1][0]<refill.get(c,1<<64)
  off_discriminates=bool(young) and any(s[11] for s in young) and not joined and c in release
 missing=[]
 if not reuse:missing.append('actual full-tag ROB index reuse')
 if not wrap:missing.append('actual ordered retirement across slot15 to slot0')
 if not killed_observed:missing.append('selected unissued wrong-path load killed under posted responsibility, real recovery hard seal, same-index replacement with a different full tag')
 if not head_selected:missing.append('selected actual head-load old seal')
 if not head_unselected:missing.append('MUL U actual head with younger Q selected old seal')
 if not young:missing.append('designated U selected younger while S1 actual head/retired queued and original S0 owner unsealed')
 if mode=='on':
  if not any(not s[11] for s in young):missing.append('ON selected-younger exception observed')
  if not joined:missing.append('S0/S1 same full owner/root/epoch/MSHR before refill offer')
 else:
  if not off_discriminates:missing.append('OFF same-guest old-seal discrimination')
 result={'status':'PASS' if not missing else 'COVERAGE_INCOMPLETE','mode':mode,'functional':True,'members':len(members),'full_tag_index_reuse':reuse,'retirement_slot15_to_slot0':wrap,'killed_selected_load_and_exact_index_reuse':len(killed_observed),'hard_cause_samples':len(hard_events),'selected_head_samples':len(head_selected),'unselected_head_samples':len(head_unselected),'designated_younger_samples':len(young),'designated_join':joined,'off_discriminates':off_discriminates,'missing':missing,'not_claimed':['CPU AMO/LR/SC','generation/tag exhaustion','fault/decode/recovery matrix','external forced backpressure','dirty-victim WB-tail stress','physical timing/performance']}
 if coverage:need(not missing,'mandatory directed coverage absent: '+ '; '.join(missing))
 return result

def read_trace(path):
 result=[]
 for line in Path(path).read_text().splitlines():
  p=line.split('\t');result.append((p[0],list(map(int,p[1:]))))
 return result

def main():
 a=argparse.ArgumentParser();a.add_argument('trace');a.add_argument('--mode',choices=['off','on'],required=True);a.add_argument('--output');args=a.parse_args()
 manifest=json.loads((Path(__file__).parent/'guest-manifest.json').read_text())
 try:
  result=validate(read_trace(args.trace),manifest,args.mode,False)
 except (Failure,KeyError,ValueError,IndexError) as e:result={'status':'FAIL','reason':str(e)}
 text=json.dumps(result,indent=2)+'\n';print(text,end='')
 if args.output:Path(args.output).write_text(text)
 raise SystemExit(0 if result['status']=='PASS' else 2)
if __name__=='__main__':main()
