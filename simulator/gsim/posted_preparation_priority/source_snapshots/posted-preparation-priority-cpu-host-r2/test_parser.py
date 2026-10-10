import copy,json,unittest
import contract as c
import parser as r

def synthetic(case=19,side='off'):
 descriptor={6:([1,0,0,1024,8],6863348401280905216,'READ',1,65536,0),0:([0,0,0,1024,8],6863348401280905216,'READ',0,65536,0),18:([0,1,1,16384,1],0,'WRITE',0,0,131072),19:([0,1,2,16384,1],0,'COPY',0,131072,131072),21:([1,1,2,16384,1],0,'COPY',1,131072,131072)}[case]
 prefix,result,op,mode,reads,writes=descriptor
 def counts(n):
  d={'cycles':n,'candidate_read':int(n>0),'candidate_store':0,'allocated_read':0,'allocated_store':0,'useful_read':0,'useful_store':0,'candidate':int(n>0),'allocated':0,'useful':0,'error':0,'busy_cycles':0,'miss_owner_cycles':0,'release_owner_cycles':0,'miss_peak':0,'release_peak':0};d.update(zip(r.AXI,[int(n>0)]*7));return d
 line=lambda n,d:n+' '+' '.join(str(k)+'='+str(v)for k,v in d.items())
 tail=0 if case in (0,6) else 2;end=15+tail
 lines=[line('WORKSET_PROGRESS',dict(cases=1,index=case,cycles=19,accepted_marker=1,independent_words=32768,per_case_poison_rejected=1)),line('STORE_PF_TERMINAL_DRAIN',dict(accepted_terminal=1,consecutive_quiet=2,**{k:0 for k in r.DRAIN})),'WORKSETS_SIGNATURE error=0 cases=1 cause=9',line('STORE_PF_ROI',dict(index=case,mode=mode,op=op,begin_offer=10,begin_accepted=11,end_offer=15,end_accepted=16,tail_offer=end,tail_accepted=end+1,**counts(5))),line('STORE_PF_TAIL',dict(index=case,**counts(tail))),line('STORE_PF_WHOLE_BOOT',dict(diagnostic_only=1,**counts(20))),line('COPY_PF_VICTIM',dict(index=case,**{k:0 for k in 'store_pf_allocations store_pf_errors actual_probes store_pf_installs observed_evictions matching_A_demand subsequent_B_store_miss subsequent_B_store_hit used_before_eviction'.split()})),f'WORKSET_ROW index={case} '+' '.join(map(str,[*prefix,99,0 if case in (0,6) else 11,result])),'FORMAL_BC_REPLAY_PASS pf_and_prepared=1 real_cpu=1 real_S_Bare_Sv39_4K_2M=1 cases=1 guest_changed=0 speedup_required=0 independent_per_case_words=32768',f'BOOTROM_MMU_WORKSETS_PASS cycles=30 begin={case} end={case+1} faults=3 S_ecalls=1 full_buffers_verified_per_case=1 independent_final_words=32768 independent_row_oracles_per_segment=1 offline_oracle_poison_rejected=3 full54=0 FPGA=0']
 for label,n in [('roi',5)]+([]if case in (0,6) else [('flush',2)]):
  w={'window':label,'cycles':n,'accepted_r_wire_bytes':8,'accepted_w_wire_bytes':8,'accepted_r_requested_payload_bytes':8,'accepted_w_strobe_bytes':8,'outstanding_sample':'pre_edge_accepted_owners','r_backpressure_cycles':0,'read_outstanding_without_r_valid':n-1,'read_window_empty':0,'both_outstanding_cycles':n,'simultaneous_r_w_fire':1,'whole_bus_empty':0}
  for k in ('ar','aw','r','w'):w[k]={'fire':1,'valid_not_ready':0,'no_offer':n-1}
  for k in ('read','write'):w.update({k+'_outstanding_histogram':{'1':n},k+'_outstanding_cycle_sum':n,k+'_outstanding_mean':1.0,k+'_outstanding_peak':1,k+'_carry_in':1,k+'_carry_out':1})
  lines.append('POSTED_BANDWIDTH_AXI '+json.dumps(w))
 for label in ('roi','flush','whole_boot_diagnostic'):
  w={'window':label,'full_generation_bits':64,'causal_attribution':'unknown_bus_owner_not_joined','examples':[]}
  for k in ('accepted','installed','drained','victim_release_ack','released','live_cycles'):w[k]=0
  lines.append('POSTED_BANDWIDTH_OWNER '+json.dumps(w))
 lines += ['POSTED_BANDWIDTH_USEFUL '+json.dumps({'case':case,'architectural_read_bytes':reads,'architectural_write_bytes':writes,'raw_bus_bytes_are_useful':False,'prefetch_useful_bus_bytes':None,'ddr_due':32,'ddr_beat_gap':1,'injected_held_b':False}),'POSTED_BANDWIDTH_TERMINAL posted_owner_masks=0 passive=1 posted_store_merge=1']
 return '\n'.join(lines)+'\n'

class Controls(unittest.TestCase):
 def test_three_cases_two_sides(self):
  for side in ('off','on'):
   for case in (0,6,18,19,21):self.assertEqual(r.parse(synthetic(case,side),side,case)['case'],case)
 def test_known_actual_copy_logs_preserved(self):
  for case in (19,21):
   p=c.BASE/f'posted-copy-supply-ledger-r2/on-case{case}-r2/positive.log';out=r.parse(p.read_text(),'off',case);self.assertEqual(out['row'][:5],[int(case==21),1,2,16384,1])
 def test_warm_independent_checksum(self):
  mask=(1<<64)-1;answer=(8*sum((0x729ad0513fe68bc4^((n*0x0102040810204081)&mask))for n in range(1024)))&mask
  self.assertEqual(answer,6863348401280905216)
  self.assertEqual(r.parse(synthetic(0),'off',0)['row'][-1],answer)
 def test_all_drain_poison(self):
  for case in (0,6,18,19,21):
   for field in r.DRAIN:
    with self.subTest(case=case,field=field),self.assertRaises(RuntimeError):r.parse(synthetic(case).replace(field+'=0',field+'=1'), 'off',case)
 def test_original_oracle_mutations(self):
  for case in (0,6,18,19,21):
   for a,b in [('S_ecalls=1','S_ecalls=2'),('faults=3','faults=2'),('begin_accepted=11','begin_accepted=10'),('per_case_poison_rejected=1','per_case_poison_rejected=0'),('axi_read_beats=1','axi_read_beats=0'),('independent_final_words=32768','independent_final_words=1'),('offline_oracle_poison_rejected=3','offline_oracle_poison_rejected=0'),('consecutive_quiet=2','consecutive_quiet=1'),('cause=9','cause=13')]:
    with self.subTest(case=case,a=a),self.assertRaises(RuntimeError):r.parse(synthetic(case).replace(a,b),'off',case)
 def test_passive_mutations(self):
  for case in (0,6,18,19,21):
   for a,b in [('"fire": 1','"fire": 2'),('"no_offer": 4','"no_offer": 3'),('"accepted_r_wire_bytes": 8','"accepted_r_wire_bytes": 7'),('"accepted_w_strobe_bytes": 8','"accepted_w_strobe_bytes": 9'),('"read_outstanding_mean": 1.0','"read_outstanding_mean": 2.0'),('"read_outstanding_histogram": {"1": 5}','"read_outstanding_histogram": {"1": 4}'),('"full_generation_bits": 64','"full_generation_bits": 8'),('"prefetch_useful_bus_bytes": null','"prefetch_useful_bus_bytes": 8'),('"ddr_due": 32','"ddr_due": 256'),('posted_owner_masks=0','posted_owner_masks=1'),('posted_store_merge=1','posted_store_merge=0')]:
    with self.subTest(case=case,a=a),self.assertRaises(RuntimeError):r.parse(synthetic(case).replace(a,b),'off',case)
 def test_warm_row_and_no_fabricated_flush(self):
  for a,b in [('1024 8 99 0 6863348401280905216','1024 1 99 0 6863348401280905216'),('6863348401280905216','6863348401280905217'),('1024 8 99 0','1024 8 99 1'),('op=READ','op=WRITE'),('tail_offer=15','tail_offer=16'),('"architectural_read_bytes": 65536','"architectural_read_bytes": 8192'),('"architectural_write_bytes": 0','"architectural_write_bytes": 131072'),('STORE_PF_TAIL index=0 cycles=0','STORE_PF_TAIL index=0 cycles=1')]:
   with self.subTest(a=a),self.assertRaises(RuntimeError):r.parse(synthetic(0).replace(a,b),'off',0)
  text=synthetic(0);roi=next(x for x in text.splitlines()if x.startswith('POSTED_BANDWIDTH_AXI '))
  with self.assertRaises(RuntimeError):r.parse(text+roi.replace('"roi"','"flush"')+'\n','off',0)
 def test_missing_duplicate_records(self):
  for case in (0,6,18,19,21):
   for prefix in ('POSTED_BANDWIDTH_AXI','POSTED_BANDWIDTH_OWNER','POSTED_BANDWIDTH_TERMINAL','WORKSET_ROW','WORKSETS_SIGNATURE'):
    text=synthetic(case);line=next(x for x in text.splitlines()if x.startswith(prefix))
    with self.subTest(case=case,prefix=prefix),self.assertRaises(RuntimeError):r.parse(text.replace(line+'\n','',1),'off',case)
    with self.subTest(case=case,prefix=prefix),self.assertRaises(RuntimeError):r.parse(text+line+'\n','off',case)
 def test_case6_sv39_identity(self):
  self.assertEqual(r.parse(synthetic(6),'off',6)['mode'],1)
  with self.assertRaises(RuntimeError):r.parse(synthetic(6).replace('mode=1','mode=0'),'off',6)
  with self.assertRaises(RuntimeError):r.parse(synthetic(6).replace('1 0 0 1024 8','0 0 0 1024 8'),'off',6)
 def test_sv39_physical_only_authority(self):
  with self.assertRaises(RuntimeError):r.parse(synthetic(21).replace('"accepted": 0','"accepted": 1'),'on',21)
 def test_unselected_case_side_and_sanitizer(self):
  for case in (1,20,22,23):
   with self.assertRaises(RuntimeError):r.parse(synthetic(19),'on',case)
  with self.assertRaises(RuntimeError):r.parse(synthetic(19),'bad',19)
  with self.assertRaises(RuntimeError):r.parse(synthetic(19)+'ERROR: AddressSanitizer','off',19)
if __name__=='__main__':unittest.main()
