"""Independent local checkpoint verifier; not the unfinished whole r23 matrix."""
from pathlib import Path
import hashlib,json
R=Path.cwd();O=R/'out/cmu-frequency-r23'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def bind(mapping):
    for n,h in mapping.items():assert sha(n if Path(n).is_absolute() else R/n)==h,n
def emission(name):
    j=read(O/(name+'-emission.json'));assert j['status']=='PASS_EMIT_ONLY' and j['returncode']==0
    bind(j['source_sha256']);assert {p.name:sha(p) for p in (O/(name+'-rtl')).glob('*.sv')}==j['rtl_sha256']
    return j
adapter=emission('adapter-r3');integrated=emission('integrated-r2');platform=emission('platform-r1')
d=read(O/'default-r1-comparison.json');assert d['source_unchanged'] and d['same_inventory'] and d['changed']==[]
assert d['byte_identical']==d['total']==248
assert {p.name:sha(p) for p in (O/'default-r1').glob('*.sv')}==d['current_sha256']==d['reference_sha256']
bind(d['source_sha256'])
bank=(O/'platform-r1-rtl/ManagedPeripheralBank.sv').read_text()
assert bank.count('TriSpeedManagedGmac gmac (')==1
assert '.sourceClock                        (_gmac_continuousClock)' in bank
assert '.fixedClock                           (_gmac_continuousClock)' in bank
assert '.fabricClock                          (sourceClock)' in bank
u=read(O/'adapter-matrix-r3/receipt.json');assert u['status']=='PASS_ADAPTER_MATRIX'
bind(u['source_sha256']);bind(u['input_sha256'])
for n,p in u['tools'].items():assert sha(p)==u['tool_sha256'][n]
assert sha(O/'adapter-matrix-r3/test.vvp')==u['binary_sha256']
expected={'fabric50':False,'fabric250':False,'fabric71':False,'fault1':False,'fault2':False,'fault3':False,
          'negative1':True,'negative2':True,'negative3':True,'negative4':True}
assert set(u['cases'])==set(expected)
markers={1:('EPOCH_NEGATIVE_OLD_RELEASED_SNAPSHOT','EPOCH_ORACLE_RELEASE_OWNERSHIP'),
2:('EPOCH_NEGATIVE_DUPLICATE_SERIAL','EPOCH_ORACLE_COMMAND_SERIAL'),
3:('EPOCH_NEGATIVE_TERMINAL_BACKPRESSURE','EPOCH_ORACLE_RELEASE_OWNERSHIP'),
4:('EPOCH_NEGATIVE_FINAL_SNAPSHOT_BACKPRESSURE','EPOCH_ORACLE_RELEASE_OWNERSHIP')}
for n,negative in expected.items():
    c=u['cases'][n];log=O/'adapter-matrix-r3'/(n+'.log');text=log.read_text()
    assert c['passed'] and c['expected_failure']==negative and c['log_sha256']==sha(log)
    resource=next(x for x in u['resources'] if x['label']==n)
    assert not resource['timed_out'] and not resource['disk_floor_breached']
    assert (resource['returncode']!=0)==negative
    if negative:
        assert all(m in text for m in markers[int(n[-1])]) and 'FIXED_MAC_EPOCH_ADAPTER_PASS' not in text
    else:
        assert 'commands=5 receipts=5 release_snapshots=2 csr=1/1' in text and 'early_cancel=1' in text
        if n.startswith('fault'):assert f'FIXED_MAC_EPOCH_FAULT_PASS case={n[-1]} failed_closed=1' in text
n=read(O/'integrated-smoke-r1/receipt.json');assert n['status']=='PASS_SELECTED_CASES'
bind(n['source_sha256']);assert n['rtl_sha256']==integrated['rtl_sha256']
for name,tool in n['tools'].items():assert sha(tool['path'])==tool['sha256']
for name,digest in n['logs_sha256'].items():assert sha(O/'integrated-smoke-r1'/name)==digest
for name,digest in n['guest']['artifacts'].items():assert sha(O/'integrated-smoke-r1'/name)==digest
assert sha(O/'integrated-smoke-r1/sim.vvp')==n['sim_sha256']
assert 'active_subprocess' not in n
for case in n['cases']:assert case['child_reaped'] and case['returncode']==0 and not case['timed_out'] and not case['disk_bound']
text=(O/'integrated-smoke-r1/fabric50-normal.log').read_text()
for marker in ('FIXED_MAC_PLATFORM_EPOCH_PASS','clocks=5/10/11/13/4/4/19/23 packet=16/16',
 'FIXED_MAC_FINAL_RECEIPT commands=4 receipts=4 released_snapshots=1 held_cycles=44',
 'MANAGED_CONTROL_RESTORED_TX CPU_restart=1 frames=2 packet_reads=16 replies=16 control_requests=6/6',
 'MANAGED_CONTROL_STATISTICS retained_drops=2 recovered_once=1 retained_config=1',
 'I1_FIXED_RESET common_cold=1 fixed_clocks_paused=1 stale_proofs_cleared=1'):
    assert marker in text,marker
result=dict(status='PASS_R23_CHECKPOINT_ONLY',whole_matrix_complete=False,default_sv_byte_identical=248,
 enabled_platform_sv=len(platform['rtl_sha256']),adapter_positive=6,adapter_ordinary_negative=4,
 real_i1_normal_fabric50=True,real_i1_cancel=False,second_ratio=False,
 records={str(p.relative_to(R)):sha(p) for p in [O/'adapter-matrix-r3/receipt.json',O/'integrated-smoke-r1/receipt.json',O/'default-r1-comparison.json',O/'platform-r1-emission.json']},
 physical_gate_drp_qualified=False,remote_upload=False)
print(json.dumps(result,indent=2))
