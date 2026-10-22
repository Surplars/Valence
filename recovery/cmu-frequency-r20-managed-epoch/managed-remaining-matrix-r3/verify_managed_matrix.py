#!/usr/bin/env python3
"""Verify exact bounded r20 matrix receipts and independent stable ledgers."""
from pathlib import Path
import hashlib,json,re,datetime
root=Path.cwd();base=root/'recovery/cmu-frequency-r20-managed-epoch';normal=base/'managed-accelerated-normal-r5';matrix=base/'managed-remaining-matrix-r3'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def fields(line):return dict(re.findall(r'(\w+)=([^\s]+)',line))
def one(lines,name):
 rows=[fields(s) for s in lines if s.split(' ',1)[0]==name];assert len(rows)==1,(name,rows);return rows[0]
n=json.loads((normal/'receipt.json').read_text());m=json.loads((matrix/'receipt.json').read_text())
assert n['status']=='PASS_SELECTED_CASES' and m['status']=='PASS_REMAINING_MATRIX'
assert n['source_sha256']==m['source_sha256'] and n['rtl_sha256']==m['rtl_sha256'] and n['tools']==m['tools']
assert n['guest']['symbols']==m['guest']['symbols']
for key in ('guest.bin','guest.hex','guest_symbols.svh'):assert n['guest']['artifacts'][key]==m['guest']['artifacts'][key]
for name,h in m['source_sha256'].items():assert sha(root/name)==h,name
for name,v in m['tools'].items():assert sha(Path(v['path']))==v['sha256'],name
for name,h in m['rtl_sha256'].items():assert sha(root/'out/cmu-frequency-r20/managed-accelerated-emission-r1/rtl'/name)==h,name
assert 'active_subprocess' not in n and 'active_subprocess' not in m
assert m['bootstrap_qualification']['sha256']==sha(normal/'receipt.json')
assert len(m['case_checkpoints'])==7 and len(m['negative_controls'])==4
expected_positive={'unrelated-tx-normal':(normal,n,'5/7/11/13/17/3/19/23'),
 'unrelated-tx-cancel':(matrix,m,'5/7/11/13/17/3/19/23'),
 'reversed-tx-normal':(matrix,m,'11/5/7/3/17/2/13/19'),
 'reversed-tx-cancel':(matrix,m,'11/5/7/3/17/2/13/19')}
positive=[];negative=[]
for label,(directory,receipt,clocks) in expected_positive.items():
 c=[x for x in receipt['cases'] if x['name']==label];assert len(c)==1;c=c[0]
 assert c['returncode']==0 and c['child_reaped'] and not c['timed_out'] and not c['disk_bound'] and c['elapsed_seconds']<=c['timeout_seconds']
 log=directory/(label+'.log');assert sha(log)==receipt['logs_sha256'][log.name];lines=log.read_text().splitlines()
 passed=one(lines,'MANAGED_CONTROL_EPOCH_PASS');assert passed==dict(case='3',clocks=clocks,packet='16/16',AXI_R='66',AXI_B='3',cpu_checked='1')
 wires=[fields(s) for s in lines if s.startswith('I1_PACKET_TX_WIRE ')];assert wires==[dict(bytes='72',crc='449789ae')]*2
 joined=one(lines,'I1_PACKET_JOINED_RETIREMENT');assert joined==dict(epoch='1',AON='1',debug='1',receipt='1',network='1',fabric='1')
 ledger=one(lines,'I1_FIXED_FINAL_LEDGER');a,b=ledger['timer'].split('/');assert a==b and int(a)>3
 assert {k:v for k,v in ledger.items() if k!='timer'}==dict(UI_read='66',source_read='66',UI_B='3',source_B='3',retained_IRQ='1')
 tx=one(lines,'MANAGED_CONTROL_RESTORED_TX');assert tx==dict(CPU_restart='1',frames='2',packet_reads='16',replies='16',control_requests='2/2' if label.endswith('cancel') else '6/6')
 assert one(lines,'I1_FIXED_RESET')==dict(common_cold='1',fixed_clocks_paused='1',stale_proofs_cleared='1')
 rejoin=one(lines,'MANAGED_CONTROL_BOOTSTRAP_REJOIN');assert rejoin['released']=='1' and rejoin['exact_fabric_clock']=='1' and rejoin['transactions']=='51'
 detail={}
 if label.endswith('normal'):
  assert one(lines,'MANAGED_CONTROL_STATISTICS')==dict(retained_drops='2',recovered_once='1',retained_config='1')
  h=one(lines,'MANAGED_CONTROL_HELD');assert h['epoch']=='1' and h['live_raw_drops']=='2' and h['MDIO_stopped']=='1' and h['new_CSR_backpressured']=='1' and int(h['pending'],16)>0
 else:
  detail=one(lines,'MANAGED_CONTROL_CANCEL');assert detail['cancel_accepted_before_held']=='1' and detail['real_terminal_join']=='1' and detail['released']=='1'
  if int(detail['runtime_park_edges'])>0:assert int(detail['matched_held_idle_samples'])>0
 positive.append(dict(case=label,elapsed_seconds=c['elapsed_seconds'],wall_budget=c['timeout_seconds'],timer=ledger['timer'],packet='16/16',frames=2,wire_bytes_each=72,crc_each='449789ae',axi_r='66/66',axi_b='3/3',csr=tx['control_requests'],cancel_observations=detail,log_sha256=sha(log)))
expected_negative={'tx-payload':('FIXED_NEGATIVE_OBSERVATION TX','NETWORK_ORACLE_PAYLOAD'),
 'control-csr-drain':('MANAGED_CONTROL_NEGATIVE_OBSERVATION CSR_DRAIN','MANAGED_CONTROL_ORACLE_CSR_DRAIN'),
 'retained-statistics':('MANAGED_CONTROL_NEGATIVE_OBSERVATION STATISTICS','MANAGED_CONTROL_ORACLE_STATISTICS'),
 'park-retention':('MANAGED_CONTROL_NEGATIVE_OBSERVATION PARK_RETENTION','MANAGED_CONTROL_ORACLE_PARK_RETENTION')}
assert {x['name'] for x in m['negative_controls']}==set(expected_negative)
for name,(inject,reject) in expected_negative.items():
 label='negative-'+name;case=[x for x in m['cases'] if x['name']==label];assert len(case)==1;c=case[0]
 assert c['returncode']!=0 and c['child_reaped'] and not c['timed_out'] and not c['disk_bound'] and c['elapsed_seconds']<=c['timeout_seconds']
 log=matrix/(label+'.log');assert sha(log)==m['logs_sha256'][log.name];text=log.read_text()
 assert inject in text and reject in text and 'MANAGED_CONTROL_EPOCH_PASS' not in text
 control=[x for x in m['negative_controls'] if x['name']==name][0];assert control['result']=='PASS_EXPECTED_REJECTION'
 negative.append(dict(case=label,elapsed_seconds=c['elapsed_seconds'],wall_budget=c['timeout_seconds'],injection=inject,rejection=reject,log_sha256=sha(log)))
for label,item in m['case_checkpoints'].items():assert sha(matrix/item['path'])==item['sha256']
d=json.loads((base/'emission/default-comparison.json').read_text());assert len(d['reference_sha256'])==248
for name,h in d['reference_sha256'].items():
 assert sha(Path(d['reference'])/name)==h and sha(Path(d['current'])/name)==h
production={k:v for k,v in m['source_sha256'].items() if k.startswith(('src/main/scala/','src/main/resources/'))};assert len(production)==315
original=json.loads((base/'managed-normal-r6/receipt.json').read_text());assert production=={k:v for k,v in original['source_sha256'].items() if k.startswith(('src/main/scala/','src/main/resources/'))}
comparison=json.loads((normal/'baseline-comparison.json').read_text());assert comparison['status']=='PASS_ARCHITECTURAL_LEDGER_COMPARISON' and comparison['candidate_receipt_sha256']==sha(normal/'receipt.json')
report=dict(status='PASS_BOUNDED_MANAGED_CONTROL_EPOCH_MATRIX',verified_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),normal_receipt_sha256=sha(normal/'receipt.json'),remaining_matrix_receipt_sha256=sha(matrix/'receipt.json'),source_count=len(m['source_sha256']),unchanged_production_sources=len(production),rtl_count=len(m['rtl_sha256']),tool_count=len(m['tools']),default_rtl_byte_identical=248,positive=positive,negative_controls=negative,scope='four real combined TX positives across two clock ratios and normal/early-cancel; four unrelated normal observation negatives; preboot-only acceleration, all runtime source/fabric edges identical',exclusions=['production fixed-clock island','full-system drain ACK','clock gate or stopped-clock feedback','DRP/backend or runtime frequency whitelist','physical PHY/MIG/board/routed timing','RX payload and timeout scenarios','late cancellation after actual park','concurrent eight-clock PHY initialization'],old_r5_interrupted_child_reaping='Unknown and unchanged; no retrospective inference',upload_status='This task performed no upload; parent reported denied uploads pending exact-manifest authorization',verification_script_sha256=sha(Path(__file__)))
(matrix/'aggregate-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
