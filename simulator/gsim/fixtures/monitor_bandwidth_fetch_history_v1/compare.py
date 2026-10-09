#!/usr/bin/env python3
"""Strict, independently reparsed LSU4 oneflag comparison; pinned LSU2 is cross-checkpoint only."""
import argparse
import csv
import json
import re
import sys
from collections import Counter, deque
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import run_replay as driver
from prepare import require,sha
PINS=json.loads((HERE/'fetch-history-pins.json').read_text())
INTERVALS={'read_cache_sized_cold':(0,1),'read_cache_hot':(2,3),'write_cache_sized':(4,5),'write_cache_sized_flush':(5,6),'copy_cache_sized':(7,8),'copy_cache_sized_flush':(8,9),'read_over_cache':(10,11),'write_over_cache':(12,13),'write_over_cache_flush':(13,14),'copy_over_cache':(15,16),'copy_over_cache_flush':(16,17)}
PCS=[0xfff783d8,0xfff78404,0xfff787b0,0xfff787e4,0xfff784c4,0xfff784ec,0xfff78500,0xfff785dc,0xfff78618,0xfff7862c,0xfff783d8,0xfff78404,0xfff784c4,0xfff784ec,0xfff78500,0xfff785dc,0xfff78618,0xfff7862c]
NEGATIVES={'data':'monitor independent physical RAM reply mismatch','token':'monitor CPU reply full-token mismatch','marker':'monitor rdtime marker sequence mismatch','stage-token':'hot stage start lacks full-token ROB owner'}
WHOLE='whole_run_includes_UART_and_launcher'

INITIAL_PC=0xfff787cc
INITIAL_WORD=0x00000713
def initial_sum(add,nodes,edge):
    key=edge(add,1);producer=nodes.get(key)
    require(producer is not None,'initial sum lacks external full-token producer')
    require(add['pc']==0xfff787d8 and add['source1']>0,'actual first ADD source identity drift')
    require(producer['kind']==1 and producer['pc']==INITIAL_PC and producer['destination']==add['source1'],
            'initial sum producer PC/physical destination mismatch')
    require(producer['source1']==producer['source2']==0,'initial ADDI zero-source provenance mismatch')
    require(producer['retired']>=producer['first_seen'] and producer['cancelled']==-1 and producer['tag']<add['tag'],
            'initial sum producer lifetime/age mismatch')
    require(all(producer[f'src{operand}_{field}']==-1 for operand in (1,2) for field in ('tag','index','pc','done_visible','retired')),
            'initial zero-source producer unexpectedly has a register dependency')
    return {'producer':producer,'first_add_token':{'tag':add['tag'],'index':add['index']},'physical_source':add['source1']}

def clean_log(text):
    require(not re.search(r'AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|LeakSanitizer|Sanitizer:DEADLYSIGNAL',text),'sanitizer diagnostic found')

def semantic_result(text):
    clean_log(text)
    for anchor in ('MONITOR_REPLAY_PASS ','MONITOR_STAGE_PASS ','MONITOR_FRONTEND_PASS ','MONITOR_UART_BEGIN','MONITOR_UART_END','CPU_BANDWIDTH_PASS verified=1 copy_bytes=payload_not_double_bus_traffic'):
        require(text.count(anchor)==1,'missing/duplicate positive anchor: '+anchor)
    require('MONITOR_REPLAY_FAIL' not in text and 'SELFTEST' not in text,'positive contains failure/quick mode')
    result=driver.parse(text)
    require(set(result['intervals'])==set(INTERVALS),'incomplete exact interval set')
    require(set(result['pipeline'])==set(INTERVALS)|{WHOLE} and set(result['ipc'])==set(INTERVALS)|{WHOLE},'incomplete exact pipeline/IPC set')
    require(set(result['loops'])=={'cold_8K_loop','hot_8K_loop','cold_128K_loop'},'incomplete exact loop set')
    ticks=result['rdtime'];keys=set()
    for i,r in enumerate(ticks):
        require(r['ordinal']==i and r['pc']==PCS[i] and 0<=r['token_index']<16,'rdtime ordinal/PC/token drift')
        key=(r['token_tag'],r['token_index']);require(key not in keys,'duplicate rdtime full token');keys.add(key)
        if i:require(r['actual_ticks']>ticks[i-1]['actual_ticks'] and r['retirement_cycle']>ticks[i-1]['retirement_cycle'],'nonmonotonic rdtime')
    for name,(first,last) in INTERVALS.items():
        r=result['intervals'][name]
        require(r['actual_ticks']==ticks[last]['actual_ticks']-ticks[first]['actual_ticks'],'interval differs from actual rdtime: '+name)
        require(r['retirement_cycles_inclusive']==ticks[last]['retirement_cycle']-ticks[first]['retirement_cycle']+1,'interval retirement window mismatch')
    uart_names=[n for n in INTERVALS if not n.endswith('_flush')]
    for i,(name,line) in enumerate(zip(uart_names,result['uart'])):
        m=re.fullmatch(r'BW ([a-z_]+) bytes=(\d+) ticks=(\d+) flush_tail=(\d+) clock_hz=(\d+) milli_MiB_s=(\d+)',line)
        require(m is not None and m[1]==name,'UART exact report sequence mismatch')
        size=8192 if i<4 else 131072;elapsed=result['intervals'][name]['actual_ticks']
        tail=result['intervals'].get(name+'_flush',{}).get('actual_ticks',0)
        require(tuple(map(int,m.groups()[1:]))==(size,elapsed,tail,100000000,(size*100000000*1000//elapsed)//1048576),'UART fields differ from actual rdtime')
    p=result['pass']
    for name,value in {'full_return':1,'full_drain':1,'lsu_owners':4,'actual_rdtime_records':18,'board_measurement':0,'terminal_raw_request_valid':0,'terminal_raw_reply_valid':0,'a_stores':52224,'b_stores':34816}.items():require(p[name]==value,'terminal proof drift: '+name)
    require(p['compiler']=='14.2.0' and p['physical_requests']==p['physical_replies']>0 and p['owner_checks']>0,'terminal counters incomplete')
    require(result['loops']['hot_8K_loop']['retired_loads']==1024 and result['loops']['cold_8K_loop']['retired_loads']==1024 and result['loops']['cold_128K_loop']['retired_loads']==16384,'loop coverage mismatch')
    s=result['stage_summary']
    for name in ('hot_retired_loads','pointer_addi','sum_add','branch'):require(s[name]==1024,'stage coverage drift: '+name)
    require(s['retired_predecessor_done_joins']+s['retired_predecessor_retirement_without_done_joins']==1024,'predecessor completion/retirement witness coverage mismatch')
    require(s['allocation_scope']=='accepted_rename_prefix_full_token','exact accepted allocation witness missing')
    require(s['physical_address_joins']>=1024 and s['source_producer_joins']>=1024,'stage source/physical joins missing')
    for name in ('load','pointer_addi','sum_add','branch'):
        bins=result['stage_histograms'][name+'_accepted_allocation_gap']
        require(sum(int(item.split(':')[1]) for item in bins.split(','))==1023,'allocation gap coverage mismatch')
    strict_summaries(result)
    return result

STATE_NAMES=('lsu_start','completion_visible_awaiting_retire','issued_completion_not_visible','nonload_pending_registered_ready_not_issue_eligibility','load_address_source_not_ready','load_source_ready_no_matching_staged_address','load_staged_capacity_predicate_blocked','load_staged_other_start_gating')
HIST_NAMES=('load_accepted_allocation_gap','pointer_addi_accepted_allocation_gap','sum_add_accepted_allocation_gap','branch_accepted_allocation_gap','all_hot_allocation_to_pending_clear_visible','all_hot_done_visible_to_retire','load_allocation_to_source_ready_visible','load_source_ready_to_prepared_visible','load_prepared_visible_to_start','load_start_to_physical_request','load_predecessor_done_visible_to_start','load_predecessor_retirement_to_start_signed','load_predecessor_retired_without_done_to_start')
SIGNED_HIST='load_predecessor_retirement_to_start_signed'
DISTRIBUTION_STAGES=('start_to_fifo','fifo_to_physical','physical_to_reply','reply_to_lsu_reply','lsu_reply_to_result','start_to_result','start_to_retire','result_to_retire','start_gap')
STAGE_COLUMNS='kind tag index pc source1 source2 destination allocated first_seen ready1_visible ready2_visible pending_clear_visible prepared_visible lsu_start physical_accepted done_visible retired cancelled retired_without_done src1_tag src1_index src1_pc src1_done_visible src1_retired src2_tag src2_index src2_pc src2_done_visible src2_retired'.split()+['state_'+n for n in STATE_NAMES]
FRONTEND_COLUMNS='cycle cursor read_base read_context snapshot_context not_invalidated instruction0_valid instruction1_valid supply_count rename_count next_tag tail present0 key0 present1 key1 present2 key2 current_packet_present backedge_d8_to_d0 primary0_data primary0_access_faults primary0_page_faults history_enabled history_present history_key history_context history_data history_access_faults history_page_faults history_matches effective_packet0_valid'.split()
HOT_PCS=tuple(range(0xfff787d0,0xfff787dd,4))

def histogram(value,signed=False):
    require(isinstance(value,str),'histogram must be text')
    bins={}
    if not value:return bins
    for item in value.split(','):
        pair=item.split(':');require(len(pair)==2,'malformed histogram bin')
        key,count=map(int,pair);require(key not in bins and count>0 and (signed or key>=0),'duplicate/nonpositive/negative histogram bin');bins[key]=count
    require(list(bins)==sorted(bins),'histogram bins out of order')
    return bins

def exact_tsv(file,columns):
    require(file.readline().rstrip('\n')=='\t'.join(columns),'exact TSV header mismatch')
    for line in file:
        cells=line.rstrip('\n').split('\t');require(len(cells)==len(columns),'malformed TSV column count')
        yield dict(zip(columns,map(int,cells)))

def stage_derived(rows):
    states=Counter({n:0 for n in STATE_NAMES});hist={n:Counter() for n in HIST_NAMES};previous={};done=without=0
    def add(name,a,b):
        if a>=0 and b>=0:hist[name][b-a]+=1
    for r in rows:
        if r['kind'] or r['retired']<0:continue
        label=('load','pointer_addi','sum_add','branch')[HOT_PCS.index(r['pc'])]
        if r['pc'] in previous:add(label+'_accepted_allocation_gap',previous[r['pc']],r['allocated'])
        previous[r['pc']]=r['allocated']
        for name in STATE_NAMES:states[name]+=r['state_'+name]
        add('all_hot_allocation_to_pending_clear_visible',r['allocated'],r['pending_clear_visible'])
        add('all_hot_done_visible_to_retire',r['done_visible'],r['retired'])
        if r['pc']==HOT_PCS[0]:
            add('load_allocation_to_source_ready_visible',r['allocated'],r['ready1_visible'])
            add('load_source_ready_to_prepared_visible',r['ready1_visible'],r['prepared_visible'])
            add('load_prepared_visible_to_start',r['prepared_visible'],r['lsu_start'])
            add('load_start_to_physical_request',r['lsu_start'],r['physical_accepted'])
            add('load_predecessor_done_visible_to_start',r['src1_done_visible'],r['lsu_start'])
            add(SIGNED_HIST,r['src1_retired'],r['lsu_start'])
            if r['src1_done_visible']>=0:done+=1
            else:
                without+=1;add('load_predecessor_retired_without_done_to_start',r['src1_retired'],r['lsu_start'])
    return states,hist,done,without

def strict_summaries(result):
    require(set(result['stage_states'])==set(STATE_NAMES) and set(result['stage_histograms'])==set(HIST_NAMES),'exact stage state/histogram schema missing')
    for n,v in result['stage_states'].items():require(isinstance(v,int) and v>=0,'invalid state owner-cycle count')
    for n,v in result['stage_histograms'].items():histogram(v,n==SIGNED_HIST)
    expected={loop+'_'+stage for loop in result['loops'] for stage in DISTRIBUTION_STAGES}
    require(set(result['distributions'])==expected,'exact complete distribution set missing')
    for name,r in result['distributions'].items():
        require(set(r)=={'count','sum','min','max','histogram'},'distribution field schema drift')
        bins=histogram(r['histogram']);require(r['count']==sum(bins.values()) and r['sum']==sum(k*v for k,v in bins.items()) and r['min']==min(bins,default=0) and r['max']==max(bins,default=0),'distribution histogram conservation mismatch')
        loop=next(n for n in result['loops'] if name.startswith(n+'_'));owners=result['loops'][loop]['started_owners']
        require(r['count']<=owners and (not name.endswith('_start_gap') or r['count']==max(0,owners-1)),'distribution owner count mismatch')
        if not name.endswith('_start_gap'):require(r['count']>=result['loops'][loop]['retired_loads'],'mandatory retired-owner distribution coverage missing')
        if name.endswith(('_start_to_retire','_result_to_retire')):require(r['count']==result['loops'][loop]['retired_loads'],'retirement-ending distribution count mismatch')
    names=set(INTERVALS)|{WHOLE};require(set(result['buckets'])==names,'complete cycle-bucket interval set missing')
    for name in names:
        ipc=result['ipc'][name];buckets=result['buckets'][name];pipe=result['pipeline'][name]
        require(buckets and all(isinstance(v,int) and v>0 for v in buckets.values()) and sum(buckets.values())==ipc['cycles'],'cycle bucket conservation mismatch')
        require(ipc['zero_commit']+ipc['single_commit']+ipc['dual_commit']==ipc['cycles'] and ipc['single_commit']+2*ipc['dual_commit']==ipc['retired'],'IPC count conservation mismatch')
        require(sum(pipe['supply_'+str(i)] for i in range(3))==ipc['cycles'] and sum(pipe['lsu_occupied_'+str(i)] for i in range(5))==ipc['cycles'],'pipeline occupancy conservation mismatch')
        require(sum(i*pipe['lsu_occupied_'+str(i)] for i in range(5))==pipe['lsu_owner_cycles'],'LSU owner-cycle conservation mismatch')
        if name!=WHOLE:require(ipc['cycles']==result['intervals'][name]['retirement_cycles_inclusive'],'IPC interval cycles mismatch')

def ready_witness(visible,producer):
    # OwnerOperandReady is a registered mirror. Accepted completion updates both
    # ROB.done and the ready mirror at the following edge. If the producer retires
    # on that completion without visible done, its mirror wake is visible no
    # earlier than retirement+1. Forwarding eligibility is a separate predicate;
    # an absent mirror sample remains absent and is not required by this check.
    if visible<0:return
    witness=producer['done_visible']
    if witness<0 and producer['retired_without_done']:witness=producer['retired']+1
    if witness>=0:require(visible>=witness,'registered operand-ready mirror precedes producer wake witness')

def phase_states(r,terminal):
    def span(first,last):
        if first<0:return 0
        first=max(first,r['first_seen']);last=min(last,terminal)
        return max(0,last-first+1)-int(first<=r['lsu_start']<=last)
    done=r['done_visible'];pending=r['pending_clear_visible'];start=r['lsu_start']
    pending_end=min(terminal,done-1 if done>=0 else terminal,pending-1 if pending>=0 else terminal)
    expected={'lsu_start':int(start>=0),'completion_visible_awaiting_retire':span(done,terminal),
        'issued_completion_not_visible':span(pending,done-1 if done>=0 else terminal)}
    if r['pc']!=HOT_PCS[0]:
        expected['nonload_pending_registered_ready_not_issue_eligibility']=span(r['first_seen'],pending_end)
        for name in STATE_NAMES[4:]:expected[name]=0
    else:
        expected['nonload_pending_registered_ready_not_issue_eligibility']=0
        ready=r['ready1_visible'];prepared=r['prepared_visible']
        expected['load_address_source_not_ready']=span(r['first_seen'],min(pending_end,ready-1 if ready>=0 else pending_end))
        staged=r['state_load_staged_capacity_predicate_blocked']+r['state_load_staged_other_start_gating']
        if prepared>=0:require(ready>=0 and ready<=prepared,'prepared load lacks prior source-ready observation')
        require(staged<=span(prepared,pending_end),'staged state exceeds possible matching-address phase')
        mandatory_unprepared=span(ready,min(pending_end,prepared-1 if prepared>=0 else pending_end))
        require(r['state_load_source_ready_no_matching_staged_address']>=mandatory_unprepared,'missing reconstructable ready-but-unprepared cycles')
    for name,count in expected.items():require(r['state_'+name]==count,'stage state contradicts reconstructable phase: '+name)

def traces(directory,result):
    counts=Counter();pending=deque();last_cycle=0;request_cycles={}
    with (directory/'positive-traffic.tsv').open() as f:
        require(f.readline().rstrip('\n')=='kind\tcycle\ttag\tindex\taddress\tdata\tmeta_or_flags','raw trace header changed')
        for line in f:
            row=line.rstrip('\n').split('\t');require(len(row)==7,'truncated traffic row')
            kind=row[0];cycle,tag,index,address,data,meta=map(int,row[1:]);require(kind in ('request','reply') and cycle>=last_cycle and 0<=index<16 and 0<=tag<2**64,'raw traffic schema/order drift');last_cycle=cycle;counts[kind]+=1
            identity=(tag,index,address)
            if kind=='request':
                pending.append(identity)
                if not meta&1:
                    require((tag,index) not in request_cycles,'duplicate physical read token');request_cycles[(tag,index)]=cycle
            else:require(pending and pending.popleft()==identity and meta==0,'raw reply ownership/fault mismatch')
    require(not pending and counts['request']==result['pass']['physical_requests'] and counts['reply']==result['pass']['physical_replies'],'complete traffic conservation mismatch')
    with (directory/'positive-hot-stage.tsv').open() as f:rows=list(exact_tsv(f,STAGE_COLUMNS))
    require(rows,'empty scalar stage trace');nodes={};hot=[];retired=Counter();previous_tag=-1
    phases=('ready1_visible','ready2_visible','pending_clear_visible','prepared_visible','lsu_start','physical_accepted','done_visible')
    for r in rows:
        key=(r['tag'],r['index']);require(key not in nodes and 0<=r['tag']<2**64 and 0<=r['index']<16,'duplicate/invalid stage full token');nodes[key]=r
        require(r['kind'] in (0,1) and r['allocated']>=0 and r['first_seen']==r['allocated']+1,'stage exact allocation/role mismatch')
        require(all(0<=r[n]<64 for n in ('source1','source2','destination')),'stage physical register schema mismatch')
        is_retired=r['retired']>=0;is_cancelled=r['cancelled']>=0
        require(is_retired!=is_cancelled,'stage terminal states not exclusive/exhaustive')
        terminal=r['retired'] if is_retired else r['cancelled']-1
        require(terminal>=r['first_seen'] and r['retired_without_done']==int(is_retired and r['done_visible']==-1),'stage terminal/done observation mismatch')
        for field in phases:require(r[field]==-1 or r['first_seen']<=r[field]<=terminal,'impossible supplied optional stage timestamp: '+field)
        require(all(r['state_'+name]>=0 for name in STATE_NAMES),'negative stage state count')
        if r['kind']:
            require(r['pc'] not in HOT_PCS and not any(r['state_'+name] for name in STATE_NAMES),'external producer row misclassified');continue
        require(r['pc'] in HOT_PCS and r['tag']>previous_tag,'hot PC/allocation token order drift');previous_tag=r['tag'];hot.append(r)
        require(sum(r['state_'+name] for name in STATE_NAMES)==terminal-r['first_seen']+1,'stage owner-cycle state conservation mismatch')
        if r['pc']!=HOT_PCS[0]:require(all(r[n]==-1 for n in ('prepared_visible','lsu_start','physical_accepted')),'nonload has load-only stage')
        phase_states(r,terminal)
        if r['lsu_start']>=0:require(r['first_seen']<=r['ready1_visible']<=r['prepared_visible']<=r['lsu_start'],'load readiness/preparation/start order mismatch')
        if r['physical_accepted']>=0:require(r['lsu_start']>=0 and r['lsu_start']<=r['physical_accepted'] and request_cycles.get(key)==r['physical_accepted'],'load full-token physical request join mismatch')
        if is_retired:
            retired[r['pc']]+=1
            if r['pc']==HOT_PCS[0]:require(r['physical_accepted']>=0,'retired load missing physical phase')
    require(retired==Counter({pc:1024 for pc in HOT_PCS}),'stage trace complete retirement set mismatch')
    external_used=set()
    for r in hot:
        used=1 if r['pc']<HOT_PCS[2] else 2
        for operand in (1,2):
            prefix='src'+str(operand);fields=[r[prefix+'_'+f] for f in ('tag','index','pc','done_visible','retired')];physical=r['source'+str(operand)]
            if fields[0]<0:
                require(fields==[-1]*5 and (operand>used or physical==0),'used operand lost source edge');continue
            producer=nodes.get(tuple(fields[:2]));require(producer is not None,'source producer row absent')
            require(producer['pc']==fields[2] and producer['done_visible']==fields[3] and producer['retired']==fields[4] and producer['destination']==physical and producer['tag']<r['tag'] and producer['allocated']<=r['allocated'],'source producer full-token/physical/age binding mismatch')
            if operand<=used:ready_witness(r['ready'+str(operand)+'_visible'],producer)
            if producer['kind']:external_used.add((producer['tag'],producer['index']))
            if r['retired']>=0 and operand<=used:require(producer['retired']>=0 and producer['retired']<=r['retired'],'retired consumer has unretired/younger source producer')
        if r['pc']==HOT_PCS[0] and r['retired']>=0:
            require(r['source1']>0 and r['src1_pc'] in (0xfff787c8,HOT_PCS[1]),'load pointer source PC missing')
            witness=r['src1_done_visible'] if r['src1_done_visible']>=0 else r['src1_retired']
            require(0<=witness<=r['lsu_start'],'load predecessor lacks prior done or retirement-without-done witness')
    require(external_used=={k for k,r in nodes.items() if r['kind']},'unused/invented external producer rows')
    by_pc={pc:[r for r in hot if r['pc']==pc and r['retired']>=0] for pc in HOT_PCS}
    def token(r):return r['tag'],r['index']
    def edge(r,operand):return r['src'+str(operand)+'_tag'],r['src'+str(operand)+'_index']
    initial=edge(by_pc[HOT_PCS[0]][0],1);limit=edge(by_pc[HOT_PCS[3]][0],1)
    require(nodes[initial]['kind']==1 and nodes[initial]['pc']==0xfff787c8 and nodes[limit]['kind']==1 and nodes[limit]['pc']==0xfff787c4,'initial pointer/limit producer binding mismatch')
    for i in range(1024):
        ld,addi,add,bne=[by_pc[pc][i] for pc in HOT_PCS]
        predecessor=initial if not i else token(by_pc[HOT_PCS[1]][i-1])
        require(edge(ld,1)==predecessor and edge(addi,1)==predecessor and edge(add,2)==token(ld) and edge(bne,2)==token(addi) and edge(bne,1)==limit,'exact scalar dynamic predecessor chain mismatch')
        if i:require(edge(add,1)==token(by_pc[HOT_PCS[2]][i-1]),'sum recurrence source chain mismatch')
        else:initial_sum(add,nodes,edge)
    states,hist,done,without=stage_derived(rows)
    require(dict(states)==result['stage_states'],'stage row/state summary mismatch')
    for name,bins in hist.items():require(dict(bins)==histogram(result['stage_histograms'][name],name==SIGNED_HIST),'stage row/histogram reconstruction mismatch: '+name)
    ss=result['stage_summary']
    require(ss['source_producer_joins']==sum(r['pc']==HOT_PCS[0] for r in hot) and ss['physical_address_joins']==sum(r['physical_accepted']>=0 for r in hot) and ss['external_producer_rows']==len(external_used) and ss['retired_predecessor_done_joins']==done and ss['retired_predecessor_retirement_without_done_joins']==without,'stage exact summary join counts mismatch')
    first=min(result['rdtime'][2]['retirement_cycle'],min(r['allocated'] for r in hot));last=result['rdtime'][3]['retirement_cycle']
    require(first<=last and all(first<=r['allocated']<=last for r in hot),'expected hot owner allocation outside complete frontend interval')
    expected_by_cycle={}
    for r in hot:expected_by_cycle.setdefault(r['allocated'],set()).add(token(r))
    frontend_counts=Counter({n:0 for n in ('rows','cursor_backedges_d8_to_d0','backedges_without_current_packet','backedges_instruction0_invalid','backedges_without_effective_packet','backedges_history_recovered')});prior=None;joined=set()
    with (directory/'positive-frontend.tsv').open() as f:
        for r in exact_tsv(f,FRONTEND_COLUMNS):
            require(r['cycle']==first+frontend_counts['rows'] and r['cycle']<=last,'frontend interval omission/duplicate/reordering/outside row');frontend_counts['rows']+=1
            for n in ('not_invalidated','instruction0_valid','instruction1_valid','present0','present1','present2','current_packet_present','backedge_d8_to_d0','history_enabled','history_present','history_matches','effective_packet0_valid'):require(r[n] in (0,1),'frontend boolean schema mismatch')
            require(r['read_base']==(r['cursor']&~7) and r['supply_count']==r['instruction0_valid']+r['instruction1_valid'] and 0<=r['rename_count']<=2 and 0<=r['tail']<16 and 0<=r['next_tag']<2**64,'frontend cursor/supply/accepted-prefix schema mismatch')
            accepted={(r['next_tag']+lane,(r['tail']+lane)&15) for lane in range(r['rename_count'])}
            owners=expected_by_cycle.get(r['cycle'],set());require(owners<=accepted,'hot owner lost exact frontend accepted-prefix full-token join');joined.update(owners)
            require(r['key1']==(r['key0']+8)%2**64 and r['key2']==(r['key0']+16)%2**64,'frontend registered packet key adjacency mismatch')
            if prior:require(r['next_tag']==prior['next_tag']+prior['rename_count'] and r['key0']==prior['read_base'] and r['snapshot_context']==prior['read_context'],'frontend accepted-event/snapshot continuity mismatch')
            present=bool(r['not_invalidated'] and r['read_context']==r['snapshot_context'] and any(r['present'+str(i)] and r['key'+str(i)]==r['read_base'] for i in range(3)))
            require(r['current_packet_present']==int(present),'frontend full key/present reconstruction mismatch')
            enabled=result['frontend_summary']['history_enabled'];require(enabled in (0,1) and r['history_enabled']==enabled,'history mode mismatch')
            require(all(0<=r[k]<8 for k in ('read_context','snapshot_context','history_context')) and all(0<=r[k]<4 for k in ('primary0_access_faults','primary0_page_faults','history_access_faults','history_page_faults')),'frontend history/context/fault widths')
            require(all(0<=r[k]<2**64 for k in ('primary0_data','history_data','history_key')) and r['history_key']%8==0,'history payload/key widths')
            if not enabled:require(not any(r[k] for k in ('history_present','history_key','history_context','history_data','history_access_faults','history_page_faults','history_matches')),'OFF has history state')
            if enabled and prior:
                expected=(prior['key0'],prior['snapshot_context'],prior['primary0_data'],prior['primary0_access_faults'],prior['primary0_page_faults'],prior['present0'] and prior['not_invalidated'])
                require(tuple(r[k] for k in ('history_key','history_context','history_data','history_access_faults','history_page_faults','history_present'))==expected,'history one-edge row-zero continuity mismatch')
            history=bool(r['history_present'] and r['history_key']==r['read_base'] and r['history_context']==r['read_context'])
            effective=bool(present or (r['not_invalidated'] and history))
            require(r['history_matches']==history and r['effective_packet0_valid']==effective,'history match/effective packet0 mismatch')
            backedge=bool(prior and prior['cursor']==0xfff787d8 and r['cursor']==0xfff787d0)
            require(r['backedge_d8_to_d0']==int(backedge),'frontend backedge classification mismatch')
            frontend_counts['cursor_backedges_d8_to_d0']+=backedge;frontend_counts['backedges_without_current_packet']+=backedge and not present;frontend_counts['backedges_instruction0_invalid']+=backedge and not r['instruction0_valid'];frontend_counts['backedges_without_effective_packet']+=backedge and not effective;frontend_counts['backedges_history_recovered']+=backedge and not present and effective;prior=r
    require(frontend_counts['rows']==last-first+1 and joined=={token(r) for r in hot},'frontend complete interval or zero-unjoined-owner proof missing')
    expected_summary={**frontend_counts,'first_cycle':first,'last_cycle':last,'joined_hot_owners':len(hot),'unjoined_hot_owners':0,'history_enabled':result['frontend_summary']['history_enabled'],'causal_claim':0}
    require(result['frontend_summary']==expected_summary,'frontend exact complete summary mismatch')

def inventory(x):
    compressed=x.get('compress_debug',False);require(isinstance(compressed,bool),'compression mode must be boolean')
    expected_products={'launcher_contract.h','replay','positive-traffic.tsv','positive-hot-stage.tsv','positive-frontend.tsv'}|{'negative-'+n+'-traffic.tsv' for n in NEGATIVES}
    if compressed:expected_products|={'replay.uncompressed','debug-compression.json'}
    require(set(x['products'])==expected_products,'exact complete product set missing')
    expected_steps=['link']+(['debug-compression'] if compressed else [])+['positive']+['negative-'+n for n in NEGATIVES]
    require([s['name'] for s in x['steps']]==expected_steps,'exact complete step set/order missing')
    for s in x['steps']:require(s['exit']==(1 if s['name'].startswith('negative-') else 0),'step exit mismatch')

def compression_evidence(x,root,repo):
    compressed=x.get('compress_debug',False)
    relative='simulator/gsim/elf_debug_compression.py';helper_path=repo/relative
    expected=driver.external_sources(repo,compressed)
    require(x.get('external_fixture_inputs',{})==expected,'exact compression helper source binding mismatch')
    if not compressed:
        require(not x.get('debug_compression_tools',{}),'uncompressed mode has compression tool evidence')
        return
    step=next(s for s in x['steps'] if s['name']=='debug-compression')
    require(step['command']==driver.compression_command(repo,root),'exact compression step command mismatch')
    text=(root/step['log']).read_text();clean_log(text)
    require(text.count('MONITOR_DEBUG_COMPRESSION_PASS')==1,'compression success anchor missing/duplicated')
    helper=driver.load_helper(helper_path)
    proof=helper.validate_compression_receipt(root/'replay.uncompressed',root/'replay',root/'debug-compression.json')
    require(proof['schema']=='valence-new-debug-compression-v1' and proof['status']=='PASS_DEBUG_COMPRESSION_ONLY','compression proof schema/status mismatch')
    require(proof['tools']==x.get('debug_compression_tools') and proof['tool_sha256']==expected[relative],'compression proof tool/helper mismatch')
    require(proof['before_sha256']==x['products']['replay.uncompressed'] and proof['after_sha256']==x['products']['replay'],'compression proof executable product mismatch')


def validate(path,flag):
    path=path.resolve();x=json.loads(path.read_text());root=path.parent;inventory(x)
    require(x['schema']=='valence-whole-monitor-fetch-history-v1' and x['status']=='PASS_WHOLE_MONITOR_FETCH_HISTORY_V1','replay incomplete')
    require(x['fetch_previous_packet']==flag and x['older_prefix']==0 and x['prechecked_data_flow']==0 and x['physical_ingress_flow']==1 and x['lsu_entries']==4,'configuration identity mismatch')
    require(x['model_receipt_sha256']==PINS['model_receipts'][str(flag)] and sha(Path(x['model_receipt']))==x['model_receipt_sha256'],'model receipt binding mismatch')
    require(x['source_freeze']==PINS['model_source_head'] and x['guest_manifest_sha256']==PINS['prepared_manifest_sha256'],'source/guest binding mismatch')
    expected_fixture={p.name:sha(p) for p in HERE.iterdir() if p.is_file() and p.suffix in ('.cpp','.h','.S','.ld','.py','.json','.md')}
    require(x['fixture_inputs']==expected_fixture,'exact complete fixture source binding mismatch')
    original=Path(x['model_repo']).parent/'Valence-cpu-retire-prefix-next/simulator/gsim/fixtures/monitor_bandwidth_replay'
    for name,digest in PINS['original_fixture_files'].items():require(sha(original/name)==digest,'qualified original changed')
    repo=Path(x['model_repo']);sys.path.insert(0,str(repo/'simulator/gsim'))
    import subprocess
    import fpga_next_board as board
    import cpu_retire_prefix_board as validation
    require(board.common.ROOT==repo,'model helpers escaped declared repository')
    anchor=PINS['model_source_head'];tree=subprocess.check_output(['git','rev-parse',anchor+':src/main'],cwd=repo,text=True).strip()
    require(x['production_source_tree']==tree and subprocess.check_output(['git','rev-parse','HEAD:src/main'],cwd=repo,text=True).strip()==tree and subprocess.check_output(['git','rev-parse',x['observer_git_head']+':src/main'],cwd=repo,text=True).strip()==tree,'production tree anchor drift')
    require(subprocess.run(['git','diff','--quiet',anchor,'--','src/main'],cwd=repo).returncode==0,'production working source/resource drift')
    files=set(subprocess.check_output(['git','ls-tree','-r','--name-only',anchor,'--','src/main'],cwd=repo,text=True).splitlines())
    require({str(p.relative_to(repo)) for p in (repo/'src/main').rglob('*') if p.is_file()}==files,'production source/resource file set drift')
    inputs=board.source_inventory();require(x['model_source_inputs']==inputs,'model source closure mismatch')
    require(sha(Path(x['host_compiler']['path']))==x['host_compiler']['sha256'],'host compiler changed')
    model,model_path,objects=validation.validate_model(Path(x['model_receipt']),1,inputs,x['host_compiler']['version'],dma_line_transfers=True,dma_line_entries=4,dma_line_yield_cycles=0,lsu_entries=4,load_order_older_retire=False,fetch_previous_packet=bool(flag))
    require(x['model_plan']==model['plan'] and x['model_git_at_build']==model['git_head'] and x['model_artifacts']==model['artifacts'],'model metadata binding mismatch')
    require(x['model_register_schema']==json.loads(json.dumps(driver.fields(model_path,flag))),'passive model schema mismatch')
    guest=x['guest']
    image=(Path(guest['archive'])/'firmware/monitor-diagnostic.bin').read_bytes()
    require(int.from_bytes(image[INITIAL_PC-driver.prepare.BASE:INITIAL_PC-driver.prepare.BASE+4],'little')==INITIAL_WORD,'initial sum archived instruction signature drift')
    fresh=driver.prepare.archive_check(Path(guest['archive']),Path(guest['source']))
    for name,value in fresh.items():require(guest[name]==value,'guest archive/source mapping changed: '+name)
    for name,digest in x['products'].items():require(sha(root/name)==digest,'product hash mismatch: '+name)
    logs={}
    for s in x['steps']:
        name=s['name'];require(s['log']==name+'.log' and sha(root/s['log'])==s['log_sha256'],'step log binding mismatch')
        text=(root/s['log']).read_text();clean_log(text);logs[name]=text
        require(s['exit']==(1 if name.startswith('negative-') else 0),'step exit mismatch')
        if name.startswith('negative-'):
            mutation=name.removeprefix('negative-');require('MONITOR_REPLAY_FAIL '+NEGATIVES[mutation] in text and 'MONITOR_REPLAY_PASS' not in text,'negative anchor mismatch')
            require((root/(name+'-traffic.tsv')).read_text()=='kind\tcycle\ttag\tindex\taddress\tdata\tmeta_or_flags\n','negative duplicated traffic')
    compression_evidence(x,root,repo)
    linked='replay.uncompressed' if x.get('compress_debug',False) else 'replay'
    require(x['steps'][0]['command']==[x['host_compiler']['argv0'],*x['compile_flags'],str(HERE/'replay.cpp'),*map(str,objects),'-ldl','-o',str(root/linked)],'link command/model object binding mismatch')
    require(x['compile_flags']==driver.compile_flags(model_path,repo,root,flag),'exact compile profile mismatch')
    base=[str(root/'replay'),str(Path(guest['archive'])/'firmware/monitor-diagnostic.bin')]
    positive=next(s['command'] for s in x['steps'] if s['name']=='positive');require(positive[:2]==base and positive[3:]==[str(root/'positive-traffic.tsv'),str(root/'positive-hot-stage.tsv'),str(root/'positive-frontend.tsv')],'positive invocation mismatch')
    prepared=Path(positive[2]).parent;require(positive[2]==str(prepared/'launcher.bin'),'positive launcher filename drift');require(sha(prepared/'manifest.json')==x['guest_manifest_sha256'] and json.loads((prepared/'manifest.json').read_text())==guest,'prepared guest manifest mismatch')
    for tool in guest['tools'].values():require(sha(Path(tool['path']))==tool['sha256'],'guest preparation tool changed')
    for name,digest in guest['artifacts'].items():require(sha(prepared/name)==digest,'prepared guest artifact mismatch')
    for s in [step for step in x['steps'] if step['name'].startswith('negative-')]:
        name=s['name'];require(s['command']==[*base,str(prepared/'launcher.bin'),str(root/(name+'-traffic.tsv')),str(root/(name+'-hot-stage.tsv')),str(root/(name+'-frontend.tsv')),'--inject-'+name.removeprefix('negative-')],'negative invocation mismatch')
    result=semantic_result(logs['positive']);require(result==x['result'],'receipt result differs from independently reparsed log')
    require(result['frontend_summary']['history_enabled']==flag,'frontend trace/model flag mismatch')
    traces(root,result);return x,result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('off',type=Path);p.add_argument('on',type=Path);p.add_argument('--lsu2-on',type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args()
    require(not a.out.exists(),'comparison output exists')
    off,old=validate(a.off,0);on,new=validate(a.on,1)
    for name in ('model_source_inputs','host_compiler','guest_manifest_sha256','fixture_inputs','shared_dma_profile','source_freeze','compress_debug','external_fixture_inputs','debug_compression_tools'):require(off[name]==on[name],'oneflag comparison input differs: '+name)
    require(on['model_plan']=={**off['model_plan'],'parameters':off['model_plan']['parameters']+['--fetch-previous-packet'],'fetch_previous_packet':True} and off['model_plan']['fetch_previous_packet'] is False,'unexpected model flag difference')
    rows=[dict(name=n,off_actual_ticks=old['intervals'][n]['actual_ticks'],on_actual_ticks=new['intervals'][n]['actual_ticks'],rate_change_percent=(old['intervals'][n]['actual_ticks']/new['intervals'][n]['actual_ticks']-1)*100) for n in INTERVALS]
    result=dict(status='PASS_STRICT_WHOLE_MONITOR_FETCH_HISTORY_V1',off_receipt_sha256=sha(a.off),on_receipt_sha256=sha(a.on),same_source=off['source_freeze'],intervals=rows,off_stage=old['stage_histograms'],on_stage=new['stage_histograms'],off_frontend=old['frontend_summary'],on_frontend=new['frontend_summary'],limits=off['limits'])
    if a.lsu2_on:
        require(sha(a.lsu2_on)==PINS['lsu2_on_receipt_sha256'],'LSU2 reference is not qualified pinned receipt')
        ref=json.loads(a.lsu2_on.read_text())
        for name,digest in ref['products'].items():require(sha(a.lsu2_on.parent/name)==digest,'pinned LSU2 artifact changed')
        for s in ref['steps']:require(sha(a.lsu2_on.parent/s['log'])==s['log_sha256'],'pinned LSU2 log changed')
        result['cross_checkpoint_lsu2_on']=dict(receipt_sha256=sha(a.lsu2_on),source=ref['source_freeze'],lsu4_source=off['source_freeze'],same_source_oneflag=False,actual_ticks={n:r['actual_ticks'] for n,r in ref['result']['intervals'].items()})
    a.out.write_text(json.dumps(result,indent=2)+'\n')
    for r in rows:print(f"{r['name']}: {r['off_actual_ticks']} -> {r['on_actual_ticks']} actual ticks; rate {r['rate_change_percent']:+.3f}%")
    print(result['status'],a.out)
if __name__=='__main__':main()
