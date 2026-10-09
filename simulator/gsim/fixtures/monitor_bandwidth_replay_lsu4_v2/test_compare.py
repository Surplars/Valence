#!/usr/bin/env python3
"""Synthetic in-memory positives and mutations through the exact production parsers."""
import copy
import io
import sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import compare
from prepare import require
c=compare
root=Path(__file__).resolve().parents[4]

def make_corpus():
    rows=[];lookup={};traffic=['kind\tcycle\ttag\tindex\taddress\tdata\tmeta_or_flags']
    def node(tag,pc,allocated,kind=0):
        r=dict.fromkeys(c.STAGE_COLUMNS,-1);r.update(kind=kind,tag=tag,index=tag%16,pc=pc,source1=0,source2=0,destination=0,allocated=allocated,first_seen=allocated+1,retired_without_done=0)
        for name in c.STATE_NAMES:r['state_'+name]=0
        return r
    limit=node(998,0xfff787c4,88,1);limit.update(destination=9,ready1_visible=89,ready2_visible=89,pending_clear_visible=90,done_visible=90,retired=91)
    initial=node(999,0xfff787c8,89,1);initial.update(destination=5,ready1_visible=90,ready2_visible=90,retired=91,retired_without_done=1)
    lookup.update({998:limit,999:initial})
    def edge(r,operand,p):
        if p is None:return
        for suffix,key in [('tag','tag'),('index','index'),('pc','pc'),('done_visible','done_visible'),('retired','retired')]:r['src'+str(operand)+'_'+suffix]=p[key]
    for iteration in range(1024):
        base=100+iteration*10;previous=initial if not iteration else lookup[1000+(iteration-1)*4+1]
        for j,pc in enumerate(c.HOT_PCS):
            a=base+j//2;tag=1000+iteration*4+j;r=node(tag,pc,a)
            r.update(ready1_visible=a+1,ready2_visible=a+1,source1=(5,5,7 if iteration else 0,9)[j],source2=(0,0,6,5)[j],destination=(6,5,7,0)[j])
            if j==0:
                r.update(prepared_visible=base+2,lsu_start=base+3,physical_accepted=base+4,pending_clear_visible=base+4,done_visible=base+5,retired=base+6);edge(r,1,previous)
                traffic.extend([f'request\t{base+4}\t{tag}\t{tag%16}\t{0xfff98000+iteration*8}\t0\t130944',f'reply\t{base+5}\t{tag}\t{tag%16}\t{0xfff98000+iteration*8}\t0\t0'])
            elif j==1:
                r.update(pending_clear_visible=base+2,done_visible=base+2,retired=base+6);edge(r,1,previous)
            elif j==2:
                r.update(ready2_visible=base+5,pending_clear_visible=base+6,done_visible=base+6,retired=base+8);edge(r,1,None if not iteration else lookup[tag-4]);edge(r,2,lookup[tag-2])
            else:
                r.update(pending_clear_visible=base+4,done_visible=base+5,retired=base+8);edge(r,1,limit);edge(r,2,lookup[tag-2])
            for cycle in range(r['first_seen'],r['retired']+1):
                if cycle==r['lsu_start']:state=c.STATE_NAMES[0]
                elif 0<=r['done_visible']<=cycle:state=c.STATE_NAMES[1]
                elif 0<=r['pending_clear_visible']<=cycle:state=c.STATE_NAMES[2]
                elif j:state=c.STATE_NAMES[3]
                elif cycle<r['ready1_visible']:state=c.STATE_NAMES[4]
                elif cycle<r['prepared_visible']:state=c.STATE_NAMES[5]
                else:state=c.STATE_NAMES[7]
                r['state_'+state]+=1
            lookup[tag]=r;rows.append(r)
    rows.extend([limit,initial]);states,hist,done,without=c.stage_derived(rows)
    text=(root/'build/gsim/monitor-whole-on-r1/positive.log').read_text()
    text=text.replace('MONITOR_REPLAY_PASS ','MONITOR_REPLAY_PASS lsu_owners=4 terminal_raw_request_valid=0 terminal_raw_reply_valid=0 ')
    text='\n'.join(line+' lsu_occupied_3=0 lsu_occupied_4=0' if line.startswith('MONITOR_PIPELINE ') else line for line in text.splitlines())+'\n'
    summary=dict(hot_retired_loads=1024,pointer_addi=1024,sum_add=1024,branch=1024,source_producer_joins=1024,retired_predecessor_done_joins=done,retired_predecessor_retirement_without_done_joins=without,physical_address_joins=1024,external_producer_rows=2,allocation_scope='accepted_rename_prefix_full_token',completion_scope='registered_done_or_explicit_retirement_without_done',pending_clear_scope='registered_pending_visibility')
    text+='MONITOR_STAGE_PASS '+' '.join(f'{k}={v}' for k,v in summary.items())+'\n'
    for name,value in states.items():text+=f'MONITOR_STAGE_STATE name={name} owner_cycles={value}\n'
    for name,bins in hist.items():text+=f'MONITOR_STAGE_HIST name={name} histogram='+','.join(f'{k}:{v}' for k,v in sorted(bins.items()))+'\n'
    frontend=[];next_tag=1000;prior=None;counts=dict(rows=0,cursor_backedges_d8_to_d0=0,backedges_without_current_packet=0,backedges_instruction0_invalid=0)
    allocations={}
    for r in rows:
        if not r['kind']:allocations[r['allocated']]=allocations.get(r['allocated'],0)+1
    for cycle in range(100,10341):
        cursor=0xfff787d8 if (cycle-100)%10==1 else 0xfff787d0;base=cursor&~7;snapshot=prior['read_base'] if prior else base
        present=any(snapshot+8*i==base for i in range(3));backedge=bool(prior and prior['cursor']==0xfff787d8 and cursor==0xfff787d0)
        r=dict.fromkeys(c.FRONTEND_COLUMNS,0);r.update(cycle=cycle,cursor=cursor,read_base=base,not_invalidated=1,instruction0_valid=int(present),instruction1_valid=int(present),supply_count=2*present,rename_count=allocations.get(cycle,0),next_tag=next_tag,tail=next_tag%16,current_packet_present=int(present),backedge_d8_to_d0=int(backedge))
        for i in range(3):r['present'+str(i)]=1;r['key'+str(i)]=snapshot+8*i
        next_tag+=r['rename_count'];frontend.append(r);prior=r;counts['rows']+=1;counts['cursor_backedges_d8_to_d0']+=backedge;counts['backedges_without_current_packet']+=backedge and not present;counts['backedges_instruction0_invalid']+=backedge and not present
    fs={**counts,'first_cycle':100,'last_cycle':10340,'joined_hot_owners':4096,'unjoined_hot_owners':0,'causal_claim':0}
    text+='MONITOR_FRONTEND_PASS '+' '.join(f'{k}={v}' for k,v in fs.items())+'\n'
    result=c.semantic_result(text)
    trace_result=copy.deepcopy(result);trace_result['rdtime'][2]['retirement_cycle']=100;trace_result['rdtime'][3]['retirement_cycle']=10340
    trace_result['pass']['physical_requests']=trace_result['pass']['physical_replies']=1024
    return text,result,trace_result,rows,frontend,'\n'.join(traffic)+'\n'

def tsv(columns,rows):return '\t'.join(columns)+'\n'+''.join('\t'.join(str(r[k]) for k in columns)+'\n' for r in rows)
text,result,trace_result,stage_rows,frontend_rows,traffic=make_corpus()
files={'positive-traffic.tsv':traffic,'positive-hot-stage.tsv':tsv(c.STAGE_COLUMNS,stage_rows),'positive-frontend.tsv':tsv(c.FRONTEND_COLUMNS,frontend_rows)}
class File:
    def __init__(self,content):self.content=content
    def open(self):return io.StringIO(self.content)
class Directory:
    def __init__(self,values):self.values=values
    def __truediv__(self,name):return File(self.values[name])
c.traces(Directory(files),trace_result)
count=0
def reject(fn,anchor):
    global count
    try:fn()
    except (AssertionError,RuntimeError,KeyError,ValueError) as e:
        require(anchor in str(e),'wrong negative reason: '+str(e));count+=1;return
    raise RuntimeError('comparator host negative accepted: '+anchor)
def frontend_mutation(rows):
    changed={**files,'positive-frontend.tsv':tsv(c.FRONTEND_COLUMNS,rows)};c.traces(Directory(changed),trace_result)
def stage_mutation(rows):
    changed={**files,'positive-hot-stage.tsv':tsv(c.STAGE_COLUMNS,rows)};c.traces(Directory(changed),trace_result)
reject(lambda:frontend_mutation([]),'frontend complete interval')
for rows in (frontend_rows[1:],frontend_rows[:-1],frontend_rows[:10]+frontend_rows[11:],frontend_rows[:10]+[frontend_rows[10]]+frontend_rows[10:],frontend_rows[:10]+[frontend_rows[11],frontend_rows[10]]+frontend_rows[12:]):reject(lambda rows=rows:frontend_mutation(rows),'frontend ')
rows=copy.deepcopy(frontend_rows);rows[0]['cycle']-=1;reject(lambda:frontend_mutation(rows),'frontend interval')
rows=copy.deepcopy(frontend_rows);rows[0]['rename_count']=0;reject(lambda:frontend_mutation(rows),'accepted-prefix full-token join')
rows=copy.deepcopy(frontend_rows);rows[0]['next_tag']^=1<<40;reject(lambda:frontend_mutation(rows),'accepted-prefix full-token join')
rows=copy.deepcopy(frontend_rows);rows[5]['key0']^=64;reject(lambda:frontend_mutation(rows),'registered packet key adjacency')
rows=copy.deepcopy(stage_rows);rows[1]['done_visible']=rows[1]['retired']+999;reject(lambda:stage_mutation(rows),'optional stage timestamp')
rows=copy.deepcopy(stage_rows);rows[2]['pending_clear_visible']=rows[2]['allocated']-999;reject(lambda:stage_mutation(rows),'optional stage timestamp')
rows=copy.deepcopy(stage_rows);rows[1]['src1_tag']=rows[1]['src1_index']=rows[1]['src1_pc']=rows[1]['src1_done_visible']=rows[1]['src1_retired']=-1;reject(lambda:stage_mutation(rows),'used operand lost source edge')
reject(lambda:stage_mutation(stage_rows[:-1]),'source producer row absent')
reject(lambda:stage_mutation(stage_rows[:1]+stage_rows[2:]),'complete retirement set')
rows=copy.deepcopy(stage_rows)
for r in rows:
    if not r['kind'] and r['pc']==c.HOT_PCS[0]:
        for suffix in ('tag','index','pc','done_visible','retired'):r['src1_'+suffix]=stage_rows[0]['src1_'+suffix]
reject(lambda:stage_mutation(rows),'dynamic predecessor chain')
rows=copy.deepcopy(stage_rows);rows[0]['state_lsu_start']+=1;reject(lambda:stage_mutation(rows),'state conservation')
changed=copy.deepcopy(trace_result);changed['stage_histograms']['load_start_to_physical_request']='2:1024';reject(lambda:c.traces(Directory(files),changed),'histogram reconstruction')
changed=copy.deepcopy(trace_result);changed['frontend_summary']['joined_hot_owners']-=1;reject(lambda:c.traces(Directory(files),changed),'exact complete summary')
for prefixes in [('MONITOR_DISTRIBUTION ',),('MONITOR_BUCKET ',)]:reject(lambda prefixes=prefixes:c.semantic_result('\n'.join(l for l in text.splitlines() if not l.startswith(prefixes))),'set missing')
reject(lambda:c.semantic_result(text+'MONITOR_STAGE_HIST name=load_accepted_allocation_gap histogram=10:1023\n'),'duplicate/malformed stage report')
negative=text.replace('MONITOR_STAGE_HIST name=load_start_to_physical_request histogram=1:1024','MONITOR_STAGE_HIST name=load_start_to_physical_request histogram=-999:1024');reject(lambda:c.semantic_result(negative),'negative histogram bin')
reject(lambda:c.semantic_result(text.replace('BW read_cache_hot','BW changed_hot')),'UART exact report')
reject(lambda:c.semantic_result(text.replace('full_drain=1','full_drain=0')),'terminal proof')
reject(lambda:c.semantic_result(text+'runtime error: synthetic\n'),'sanitizer')
x={'products':dict.fromkeys({'launcher_contract.h','replay','positive-traffic.tsv','positive-hot-stage.tsv','positive-frontend.tsv'}|{'negative-'+n+'-traffic.tsv' for n in c.NEGATIVES}),'steps':[dict(name=n,exit=1 if n.startswith('negative-') else 0) for n in ['link','positive']+['negative-'+n for n in c.NEGATIVES]]}
c.inventory(x)
y=copy.deepcopy(x);y['products'].pop('replay');reject(lambda:c.inventory(y),'product set')
y=copy.deepcopy(x);y['steps'].pop();reject(lambda:c.inventory(y),'step set')
y=copy.deepcopy(x);y['steps'][1]['exit']=1;reject(lambda:c.inventory(y),'step exit')
# Final independent review probes, run through the same production parsers.
import re
zero='\n'.join(re.sub(r' count=.*$', ' count=0 sum=0 min=0 max=0 histogram=',line) if line.startswith('MONITOR_DISTRIBUTION ') and not line.split()[1].endswith('_start_gap') else line for line in text.splitlines())
reject(lambda:c.semantic_result(zero),'mandatory retired-owner distribution coverage')
rows=copy.deepcopy(stage_rows);rows[2]['ready2_visible']=rows[2]['first_seen'];reject(lambda:stage_mutation(rows),'registered operand-ready mirror precedes')
rows=copy.deepcopy(stage_rows);rows[0]['state_load_staged_capacity_predicate_blocked']=rows[0]['state_lsu_start'];rows[0]['state_lsu_start']=0
changed=copy.deepcopy(trace_result);states,hist,done,without=c.stage_derived(rows);changed['stage_states']=dict(states)
changed_files={**files,'positive-hot-stage.tsv':tsv(c.STAGE_COLUMNS,rows)}
reject(lambda:c.traces(Directory(changed_files),changed),'staged state exceeds possible matching-address phase')
# Legal absent mirror remains optional; missing registered done stays explicit.
c.ready_witness(-1,stage_rows[0])
c.ready_witness(stage_rows[-1]['retired']+1,stage_rows[-1])
reject(lambda:c.ready_witness(stage_rows[-1]['retired'],stage_rows[-1]),'registered operand-ready mirror precedes')
print(f'PASS_MONITOR_V2_COMPARATOR_HOST negatives={count} exact_trace_parser=1 complete_cycle_token_join=1 optional_unobserved_done=1 synthetic_only=1')
