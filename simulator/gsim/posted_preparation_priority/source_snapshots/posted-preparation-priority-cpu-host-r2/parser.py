#!/usr/bin/env python3
"""Preserved formal CPU result checks, extended by passive posted bandwidth validation."""
import argparse,json,os,re,shutil,signal,subprocess,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
from contract import *
DRAIN='lsu_live request_fifo adapter_and_return_counts backend_offer_valid adapter_wait_or_ack pf_busy_owners pf_candidate cache_mshr_engine cache_writeback cache_responses cache_control home_acquire_release_probe home_transfer home_dma_owners shared_state_owners translation_walkers dma_busy axi_holders_and_offers'.split()
AXI='axi_read_requests axi_read_declared_beats axi_read_beats axi_write_requests axi_write_declared_beats axi_write_beats axi_write_responses'.split()
def save(path,data,new=False):
 text=json.dumps(data,indent=2)+'\n'
 if new:
  with Path(path).open('x') as f:f.write(text)
 else:
  tmp=Path(str(path)+'.tmp');tmp.write_text(text);tmp.replace(path)
def fields(line):
 pairs=[x.split('=',1) for x in line.split()[1:]];require(all(len(x)==2 for x in pairs) and len({x[0] for x in pairs})==len(pairs),'duplicate/malformed result column')
 return {k:v if k=='op' else int(v) for k,v in pairs}
def parse(text,side,case):
 require(side in ('off','on') and case in CASES,'scope mismatch')
 require(not re.search(SANITIZERS,text),'sanitizer output')
 expected=f'FORMAL_BC_REPLAY_PASS pf_and_prepared={1} real_cpu=1 real_S_Bare_Sv39_4K_2M=1 cases=1 guest_changed=0 speedup_required=0 independent_per_case_words=32768'
 require(text.splitlines().count(expected)==1,'missing exact actual formal replay terminal pass')
 lines=text.splitlines();select=lambda prefix:[x for x in lines if x.startswith(prefix+' ')]
 rows=select('WORKSET_ROW');require(len(rows)==1,'exactly one terminal formal workset required');a=rows[0].split();require(a[1]=='index='+str(case),'wrong case row');row=list(map(int,a[2:]));require(len(row)==8 and row[:5]==CASES[case]["row_prefix"] and row[5]>0 and (row[6]==0 if case in (0,6) else row[6]>0) and row[7]==CASES[case]["result"],'independent row/count/result/timing mismatch')
 rr=select('STORE_PF_ROI');tt=select('STORE_PF_TAIL');ww=select('STORE_PF_WHOLE_BOOT');dd=select('STORE_PF_TERMINAL_DRAIN');progress=select('WORKSET_PROGRESS');sig=select('WORKSETS_SIGNATURE');done=select('BOOTROM_MMU_WORKSETS_PASS')
 require(all(len(x)==1 for x in (rr,tt,ww,dd,progress,sig,done)),'missing/extra per-case coverage record')
 roi,tail,whole,drain=map(lambda x:fields(x[0]),(rr,tt,ww,dd));p=fields(progress[0]);sg=fields(sig[0]);terminal=fields(done[0])
 require(p['cases']==1 and p['index']==case and p['accepted_marker']==1 and p['independent_words']==32768 and p['per_case_poison_rejected']==1,'per-case independently verified buffers missing')
 require(sg=={'error':0,'cases':1,'cause':9},'signature mismatch')
 require(terminal['begin']==case and terminal['end']==case+1 and terminal['faults']==3 and terminal['S_ecalls']==1 and terminal['independent_final_words']==32768 and terminal['offline_oracle_poison_rejected']==3 and terminal['full54']==0 and terminal['FPGA']==0,'trap/terminal/oracle coverage mismatch')
 require(roi['index']==tail['index']==case and roi['mode']==CASES[case]['mode'] and roi['op']==CASES[case]['op'],'ROI case/mode/op mismatch')
 require(all(roi[k+'_accepted']==roi[k+'_offer']+1 for k in ('begin','end','tail')),'marker acceptance edge mismatch')
 require(roi['cycles']==roi['end_offer']-roi['begin_offer']>0 and tail['cycles']==roi['tail_offer']-roi['end_offer'] and (tail['cycles']==0 if case in (0,6) else tail['cycles']>0),'half-open ROI interval mismatch')
 require(drain.pop('accepted_terminal')==1 and drain.pop('consecutive_quiet')>=2 and set(drain)==set(DRAIN) and not any(drain.values()),'terminal real-owner drain incomplete')
 if case in (0,6):require(all(v==0 for k,v in tail.items() if k!='index'),'READ must have zero tail counters')
 for r in (roi,tail,whole):
  for name in ('candidate','allocated','useful'):require(r[name]==r[name+'_read']+r[name+'_store'],'PF origin totals mismatch')
  require(all(k in r and r[k]>=0 for k in AXI),'AXI counters missing/negative')
 require(whole['diagnostic_only']==1 and whole[AXI[1]]==whole[AXI[2]] and whole[AXI[4]]==whole[AXI[5]] and whole[AXI[3]]==whole[AXI[6]],'whole-boot terminal AXI conservation failed')
 cc=select('COPY_PF_VICTIM');require(len(cc)==1,'COPY PF victim summary missing/extra');copy=fields(cc[0]);require(copy.pop('index')==case,'COPY observer case mismatch')
 require(set(copy)==set('store_pf_allocations store_pf_errors actual_probes store_pf_installs observed_evictions matching_A_demand subsequent_B_store_miss subsequent_B_store_hit used_before_eviction'.split()) and all(v>=0 for v in copy.values()),'COPY observer field schema/count mismatch')
 require(copy['subsequent_B_store_miss']+copy['subsequent_B_store_hit']<=copy['matching_A_demand']<=copy['observed_evictions']<=copy['store_pf_installs'],'COPY chain counts inconsistent')
 if case%2==0:require(not any(copy.values()),'COPY claim outside enabled COPY ROI')
 witnesses=[fields(x) for x in select('COPY_PF_WITNESS')];require(len(witnesses)==min(8,copy['subsequent_B_store_miss']+copy['subsequent_B_store_hit']),'COPY witness/count mismatch')
 for w in witnesses:
  require(set(w)==set('index slot line allocation_cycle install_cycle victim_cycle demand_line subsequent_store_cycle used_before_eviction'.split()) and w['used_before_eviction'] in (0,1),'COPY witness schema mismatch')
  require(w['index']==case and 0<=w['slot']<512 and 0xfffb8000<=w['line']<0xfffd8000 and w['line']%64==0,'COPY full-PA witness geometry')
  require(w['demand_line']==0xfff98000+(w['line']-0xfffb8000) and w['allocation_cycle']<w['install_cycle']<w['victim_cycle']<w['subsequent_store_cycle'],'COPY allocation/install/victim/store chain mismatch')
 return {'copy_victim':copy,'copy_witnesses':witnesses,'case':case,'mode':CASES[case]['mode'],'op':CASES[case]['op'],'row':row,'ticks':row[5],'flush_tail':row[6],'roi':roi,'tail':tail,'whole_boot_diagnostic':whole,'store_origin_witnessed_in_timed_roi':roi['candidate_store']>0,'speedup_required':False}


original_parse=parse
def unique_json(text,prefix):
 result=[]
 def pairs(items):
  require(len({k for k,v in items})==len(items),'duplicate JSON key')
  return dict(items)
 for line in text.splitlines():
  if line.startswith(prefix+' '):result.append(json.loads(line[len(prefix)+1:],object_pairs_hook=pairs))
 return result

def validate_window(w,legacy,label):
 require(w['window']==label and w['cycles']==legacy['cycles']>0,'passive/legacy interval mismatch')
 n=w['cycles'];require(w['outstanding_sample']=='pre_edge_accepted_owners','wrong occupancy sample edge')
 for channel in ('ar','aw','r','w'):
  c=w[channel];require(set(c)=={'fire','valid_not_ready','no_offer'} and all(type(x) is int and x>=0 for x in c.values()) and sum(c.values())==n,'AXI cycle partition mismatch')
 for channel,key in [('ar','axi_read_requests'),('aw','axi_write_requests'),('r','axi_read_beats'),('w','axi_write_beats')]:require(w[channel]['fire']==legacy[key],'legacy AXI counter changed')
 for kind in ('read','write'):
  h=w[kind+'_outstanding_histogram'];require(all(k.isdigit() and type(v)is int and v>=0 for k,v in h.items()),'bad occupancy histogram')
  require(sum(h.values())==n and sum(int(k)*v for k,v in h.items())==w[kind+'_outstanding_cycle_sum'],'occupancy histogram sum mismatch')
  require(max(map(int,h))==w[kind+'_outstanding_peak'],'occupancy peak mismatch')
  require(abs(w[kind+'_outstanding_mean']-w[kind+'_outstanding_cycle_sum']/n)<=max(1e-5,abs(w[kind+'_outstanding_mean'])*1e-5),'occupancy mean mismatch')
  require(type(w[kind+'_carry_in'])is int and w[kind+'_carry_in']>=0 and type(w[kind+'_carry_out'])is int and w[kind+'_carry_out']>=0,'invalid carry')
 require(w['accepted_r_wire_bytes']==w['r']['fire']*8 and w['accepted_w_wire_bytes']==w['w']['fire']*8,'wire byte/fire mismatch')
 require(0<=w['accepted_r_requested_payload_bytes']<=w['accepted_r_wire_bytes'] and 0<=w['accepted_w_strobe_bytes']<=w['accepted_w_wire_bytes'],'wire/payload/strobe mismatch')
 require(w['r_backpressure_cycles']==w['r']['valid_not_ready'] and 0<=w['read_outstanding_without_r_valid']<=w['r']['no_offer'] and 0<=w['read_window_empty']<=w['r']['no_offer'],'R wait classification mismatch')
 require(0<=w['both_outstanding_cycles']<=n and 0<=w['simultaneous_r_w_fire']<=min(w['r']['fire'],w['w']['fire']) and 0<=w['whole_bus_empty']<=w['read_window_empty'],'overlap/idle mismatch')

def parse(text,side,case):
 out=original_parse(text,side,case)
 records=unique_json(text,'POSTED_BANDWIDTH_AXI');require(len(records)==(1 if case in (0,6) else 2) and {r['window'] for r in records}==({'roi'} if case in (0,6) else {'roi','flush'}),'missing/duplicate passive windows')
 windows={r['window']:r for r in records}
 validate_window(windows['roi'],out['roi'],'roi')
 if case not in (0,6):validate_window(windows['flush'],out['tail'],'flush')
 if case not in (0,6):
  for kind in ('read','write'):require(windows['roi'][kind+'_carry_out']==windows['flush'][kind+'_carry_in'],'ROI/flush carry lost owner')
 own=unique_json(text,'POSTED_BANDWIDTH_OWNER');require(len(own)==3 and {r['window'] for r in own}=={'roi','flush','whole_boot_diagnostic'},'missing/duplicate owner windows')
 for r in own:
  require(r['full_generation_bits']==64 and r['causal_attribution']=='unknown_bus_owner_not_joined','invented/truncated owner attribution')
  for k in ('accepted','installed','drained','victim_release_ack','released','live_cycles'):require(type(r[k])is int and r[k]>=0,'bad owner counts')
  for e in r['examples']:require(type(e['generation'])is int and 0<=e['generation']<2**64 and e['slot'] in (0,1) and e['line']%64==0,'bad full generation witness')
 useful=unique_json(text,'POSTED_BANDWIDTH_USEFUL');require(useful==[{'case':case,'architectural_read_bytes':CASES[case]['read_bytes'],'architectural_write_bytes':CASES[case]['write_bytes'],'raw_bus_bytes_are_useful':False,'prefetch_useful_bus_bytes':None,'ddr_due':32,'ddr_beat_gap':1,'injected_held_b':False}],'useful payload/DDR contract changed')
 terminal=[fields(x) for x in text.splitlines() if x.startswith('POSTED_BANDWIDTH_TERMINAL ')];require(terminal==[{'posted_owner_masks':0,'passive':1,'posted_store_merge':1}],'posted terminal mask/side mismatch')
 owner_roi=next(x for x in own if x['window']=='roi')
 if case in (0,6):require(all(x[k]==0 for x in own if x['window']=='flush' for k in ('accepted','installed','drained','victim_release_ack','released','live_cycles')),'READ invented flush ownership')
 if case>=20:require(owner_roi['accepted']==0,'Sv39 ROI unexpectedly gained physical-only posted authority')
 out['posted_acceptance_witnessed_in_roi']=owner_roi['accepted']>0
 out['sv39_nonauthorized_path_control']=case>=20
 out.update(axi=windows,owner_observation=own,architectural_useful_payload=useful[0],architectural_bytes_per_roi_cycle=(CASES[case]['read_bytes']+CASES[case]['write_bytes'])/out['roi']['cycles'])
 return out

OWNER_KINDS=('accepted','installed','drained','victim_release_ack','released')
def validate_owner_trace(path,result,rob_entries=16):
 require(rob_entries in (16,32,64),"unsupported actual ROB profile")
 counts={w:{k:0 for k in OWNER_KINDS}for w in ('roi','flush','outside')};seen=set();n=0;last_cycle=-1;terminal=None;dirty=clean=0
 with Path(path).open()as f:
  for line in f:
   row=json.loads(line);require(terminal is None,'owner sidecar data after terminal')
   if 'terminal'in row:
    require(row=={'terminal':True,'events':n},'owner sidecar terminal/count differs');terminal=row;continue
   require(set(row)=={'sequence','window','owner'} and row['sequence']==n and row['window']in counts,'owner sidecar omitted/duplicate sequence/window')
   e=row['owner'];kind=e['event'];require(kind in OWNER_KINDS,'unknown owner sidecar event')
   common={'event','slot','generation','epoch','line','cycle','cohort_slot','cohort_generation'}
   keys=common|({'token_index','token_tag','response_ticket'}if kind in ('accepted','drained')else set())|({'new_line'}if kind=='accepted'else set())
   if kind!='drained':
    keys|={'mshr','set','way','victim_valid'}
    require(e['victim_valid']in (0,1),'invalid victim-valid')
    if e['victim_valid']:keys|={'victim_dirty','victim_address'};require(e['victim_dirty']in (0,1) and e['victim_address']%64==0,'invalid victim witness')
   if kind=='victim_release_ack':keys|={'wb_ticket_slot','wb_ticket_owner_slot','wb_ticket_owner_generation'}
   require(set(e)==keys,'owner sidecar inactive/missing fields')
   for k in ('generation','cohort_generation','line','cycle'):require(type(e[k])is int and 0<=e[k]<2**64,'owner identity/cycle width mismatch')
   require(type(e['epoch'])is int and 0<=e['epoch']<2**32 and e['slot']in (0,1)and e['cohort_slot']in(0,1)and e['line']%64==0 and e['cycle']>=last_cycle,'owner identity/chronology mismatch')
   if kind in ('accepted','drained'):require(type(e['token_tag'])is int and 0<=e['token_tag']<2**64 and type(e['token_index'])is int and 0<=e['token_index']<rob_entries and e['response_ticket']in(0,1),'full ROB member token missing/truncated')
   if kind!='drained':require(e['mshr']in(0,1) and 0<=e['set']<256 and e['way']in(0,1),'owner reservation geometry mismatch')
   if kind=='victim_release_ack':
    require(e['victim_valid']==1 and e['wb_ticket_slot']in(0,1)and e['wb_ticket_owner_slot']==e['slot']and e['wb_ticket_owner_generation']==e['generation'],'victim ReleaseAck full ticket mismatch')
    dirty+=e['victim_dirty'];clean+=not e['victim_dirty']
   key=(kind,e['slot'],e['generation'],e['cycle'],e.get('token_index'),e.get('token_tag'));require(key not in seen,'duplicate full owner sidecar event');seen.add(key)
   w=row['window'];r=result['roi']
   expected_window='roi'if r['begin_offer']<=e['cycle']<r['end_offer']else 'flush'if r['end_offer']<=e['cycle']<r['tail_offer']else 'outside'
   require(w==expected_window,'owner sidecar ROI/flush edge mismatch');counts[w][kind]+=1;n+=1;last_cycle=e['cycle']
 require(terminal is not None,'owner sidecar missing terminal')
 observed={x['window']:x for x in result['owner_observation']}
 for w in ('roi','flush'):
  for k in OWNER_KINDS:require(counts[w][k]==observed[w][k],'owner sidecar/printed window count mismatch')
 for k in OWNER_KINDS:require(sum(counts[w][k]for w in counts)==observed['whole_boot_diagnostic'][k],'owner sidecar omitted whole-boot event')
 return {'path':str(Path(path).resolve()),'sha256':sha(path),'bytes':Path(path).stat().st_size,'events':n,'window_counts':counts,'dirty_victim_release_ack':dirty,'clean_victim_release_ack':clean,'all_valid_events_recorded':True,'external_axi_b_attribution':'unknown'}
