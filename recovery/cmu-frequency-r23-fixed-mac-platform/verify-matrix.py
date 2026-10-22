#!/usr/bin/env python3
"""Independent fixed-MAC integration verifier. Never promotes gate/DRP/board ACK."""
from pathlib import Path
import hashlib,json,re,difflib,argparse
p=argparse.ArgumentParser(description=__doc__)
p.add_argument("--positive-checkpoint",action="store_true",help="Explicit incomplete checkpoint: excludes the still-pending five real-MAC negatives")
a=p.parse_args()
R=Path.cwd();O=R/'out/cmu-frequency-r23';HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_text())
changes=[]
def bind(mapping):
    for n,h in mapping.items():assert sha(n if Path(n).is_absolute() else R/n)==h,n

def historic_bind(j,d):
    for n,h in j['source_sha256'].items():
        if sha(R/n)==h:continue
        # Only the exact approved HOST timeout extension and three header-comment
        # lines changed after the first two immutable measured positive runs.
        archived=d/('source-'+Path(n).name);assert sha(archived)==h,n
        before=archived.read_text();after=(R/n).read_text();expected=before
        if n=='simulator/gsim/common/fixed_mac_epoch_tb.sv':
            expected=before.replace('// Only the external AXI RAM responder is modeled. No terminal receipt is injected.\n// r20 replaces, rather than supplements, the r19 packet endpoint with the real\n// managed bank.', '// External AXI RAM and Clause22 PHY pins are modeled. No terminal receipt is injected.\n// r23 replaces the r19 packet endpoint with the actual fixed125 managed\n// bank and tagged boundary.')
        elif n=='simulator/gsim/common/fixed_mac_epoch_native.py':
            expected=before.replace("    p.add_argument('--negative-only', choices=NEGATIVES)","    p.add_argument('--negative-only', choices=NEGATIVES)\n    p.add_argument('--native-wall-seconds', type=int, choices=(180,300), default=180,\n                   help='Host-only per-native-case ceiling; 300s approved for this bounded r23 matrix')")
            expected=expected.replace('maximum_child_seconds=180,','maximum_child_seconds=a.native_wall_seconds, build_child_seconds=180,')
            expected=expected.replace('rc,log=old.run(command+args,out,label,180,record)','rc,log=old.run(command+args,out,label,a.native_wall_seconds,record)')
            expected=expected.replace("        preboot_scope='continuous raw125 MAC; only empty large domains pause, no source rejoin',", "        approved_case_wall_budgets=({**{r+'-'+s:300 for r in RATIOS for s in old.SCENARIOS},\n                                    **{'negative-'+n:300 for n in NEGATIVES}} if a.native_wall_seconds==300 else {}),\n        wall_budget_scope='175.457s measured normal; approved 300s host-only ceiling for bounded r23 cases, no DUT/MDIO/guest timing changes',\n        preboot_scope='continuous raw125 MAC; only empty large domains pause, no source rejoin',")
        else:raise AssertionError('unapproved source difference '+n)
        assert expected==after,n
        changes.append(dict(record=str(d.relative_to(R)),path=n,historical_sha256=h,current_sha256=sha(R/n),
                            exact_diff=list(difflib.unified_diff(before.splitlines(),after.splitlines(),lineterm=''))))

def emission(name):
    j=read(O/(name+'-emission.json'));assert j['status']=='PASS_EMIT_ONLY' and j['returncode']==0
    bind(j['source_sha256']);assert {p.name:sha(p) for p in (O/(name+'-rtl')).glob('*.sv')}==j['rtl_sha256']
    return j
adapter=emission('adapter-r3');integrated=emission('integrated-r2');platform=emission('platform-r1')
d=read(O/'default-r1-comparison.json');bind(d['source_sha256'])
assert d['source_unchanged'] and d['same_inventory'] and d['changed']==[]
assert d['byte_identical']==d['total']==248
assert {p.name:sha(p) for p in (O/'default-r1').glob('*.sv')}==d['current_sha256']==d['reference_sha256']
bank=(O/'platform-r1-rtl/ManagedPeripheralBank.sv').read_text();mac=(O/'platform-r1-rtl/TriSpeedManagedGmac.sv').read_text()
assert bank.count('TriSpeedManagedGmac gmac (')==1
for v in ['.sourceClock                        (_gmac_continuousClock)',
          '.fixedClock                           (_gmac_continuousClock)',
          '.fabricClock                          (sourceClock)']:assert v in bank
assert 'assign continuousClock = rawTxClock;' in mac
boundary=(O/'platform-r1-rtl/FixedMacBoundary.sv').read_text()
assert len(re.findall(r'  HeldResponseCdcDataFifo_\d+ (?:txData|txControl|rxData|rxStatus) \(',boundary))==4
u=read(O/'adapter-matrix-r5/receipt.json');assert u['status']=='PASS_ADAPTER_MATRIX'
bind(u['source_sha256']);bind(u['input_sha256'])
for n,p in u['tools'].items():assert sha(p)==u['tool_sha256'][n]
assert sha(O/'adapter-matrix-r5/test.vvp')==u['binary_sha256']
expected={'fabric50':False,'fabric250':False,'fabric71':False,'fault1':False,'fault2':False,'fault3':False,
          'negative1':True,'negative2':True,'negative3':True,'negative4':True}
assert set(u['cases'])==set(expected)
markers={1:('EPOCH_NEGATIVE_OLD_RELEASED_SNAPSHOT','EPOCH_ORACLE_RELEASE_OWNERSHIP'),
2:('EPOCH_NEGATIVE_DUPLICATE_SERIAL','EPOCH_ORACLE_COMMAND_SERIAL'),
3:('EPOCH_NEGATIVE_TERMINAL_BACKPRESSURE','EPOCH_ORACLE_RELEASE_OWNERSHIP'),
4:('EPOCH_NEGATIVE_FINAL_SNAPSHOT_BACKPRESSURE','EPOCH_ORACLE_RELEASE_OWNERSHIP')}
for n,negative in expected.items():
    c=u['cases'][n];log=O/'adapter-matrix-r5'/(n+'.log');text=log.read_text()
    assert c['passed'] and c['expected_failure']==negative and c['log_sha256']==sha(log)
    resource=next(x for x in u['resources'] if x['label']==n)
    assert not resource['timed_out'] and not resource['disk_floor_breached']
    assert (resource['returncode']!=0)==negative
    if negative:assert all(m in text for m in markers[int(n[-1])]) and 'FIXED_MAC_EPOCH_ADAPTER_PASS' not in text
    else:
        assert 'commands=5 receipts=5 release_snapshots=2 csr=2/2' in text and 'early_cancel=1' in text
        assert 'FIXED_MAC_UNSENT_PARK_CANCEL csr_owner_retained=1 parked_commands=0 released_before_fresh_reply=1' in text
        if n.startswith('fault'):assert f'FIXED_MAC_EPOCH_FAULT_PASS case={n[-1]} failed_closed=1' in text
negative_markers={
 'tx-payload':(1,'NETWORK_ORACLE_PAYLOAD','FIXED_NEGATIVE_OBSERVATION TX'),
 'control-csr-drain':(5,'MANAGED_CONTROL_ORACLE_CSR_DRAIN','MANAGED_CONTROL_NEGATIVE_OBSERVATION CSR_DRAIN'),
 'retained-statistics':(6,'MANAGED_CONTROL_ORACLE_STATISTICS','MANAGED_CONTROL_NEGATIVE_OBSERVATION STATISTICS'),
 'park-retention':(7,'MANAGED_CONTROL_ORACLE_PARK_RETENTION','MANAGED_CONTROL_NEGATIVE_OBSERVATION PARK_RETENTION'),
 'final-snapshot':(8,'FIXED_MAC_ORACLE_FINAL_SNAPSHOT_OWNER','FIXED_MAC_NEGATIVE_OLD_RELEASED_SNAPSHOT')}
groups={'integrated-smoke-r1':['fabric50-normal'],'integrated-cancel-r1':['fabric50-cancel'],
        'integrated-second-ratio-r2':['fabric71-normal','fabric71-cancel'],
        **({} if a.positive_checkpoint else {'integrated-negative-'+n+'-r1':['negative-'+n] for n in negative_markers})}
results={};recordhash={};common_guest=None;assert_count=None
for group,labels in groups.items():
    p=O/group;j=read(p/'receipt.json');assert j['status']=='PASS_SELECTED_CASES';historic_bind(j,p)
    assert j['rtl_sha256']==integrated['rtl_sha256'];assert j['fixed_source_hz']==125000000
    assert not j['full_ack'] and not j['physical_qualified'] and not j['gate_drp_backend']
    for name,t in j['tools'].items():assert sha(t['path'])==t['sha256']
    for name,h in j['logs_sha256'].items():assert sha(p/name)==h
    for name,h in j['guest']['artifacts'].items():assert sha(p/name)==h
    image={n:h for n,h in j['guest']['artifacts'].items() if n!='guest.elf'}
    if common_guest is None:common_guest=image
    assert image==common_guest  # ELF has per-output-directory debug paths; separately bound above
    assert sha(p/'sim.vvp')==j['sim_sha256']
    assert sha(p/'preprocessed.sv')==j['production_assertions']['preprocessed_sha256']
    pretext=(p/'preprocessed.sv').read_text()
    assert pretext.count('$fatal')==j['production_assertions']['inline_fatal_sites']==519
    for m in j['production_assertions']['required_messages']:assert m in pretext
    assert 'active_subprocess' not in j
    assert [c['name'] for c in j['cases'][6:]]==labels
    for c in j['cases']:
        assert c['child_reaped'] and not any(c[k] for k in ('timed_out','disk_bound','interrupted','stop_requested'))
        assert c['minimum_free_bytes']>=4*1024**3
        if c['name'] not in labels:assert c['returncode']==0 and c['timeout_seconds']<=180
    for label in labels:
        c=next(c for c in j['cases'] if c['name']==label);text=(p/(label+'.log')).read_text()
        assert c['timeout_seconds'] in (180,300)
        if c['timeout_seconds']==300:assert j['approved_case_wall_budgets'][label]==300
        assert '+case=3' in c['command'] and '+rx-half=4' in c['command'] and '+tx-half=4' in c['command']
        if label.startswith('negative-'):
            number,reject,inject=negative_markers[label[9:]]
            assert c['returncode']!=0 and reject in text and inject in text and 'FIXED_MAC_PLATFORM_EPOCH_PASS' not in text
            assert '+negative='+str(number) in c['command'] and '+managed-scenario=0' in c['command']
            assert len(j['negative_controls'])==1 and j['negative_controls'][0]['passed']
        else:
            assert c['returncode']==0 and 'FIXED_MAC_PLATFORM_EPOCH_PASS' in text
            ratio,scenario=label.split('-');cancel=scenario=='cancel';commands=3 if cancel else 4
            clocks='5/10/11/13/4/4/19/23' if ratio=='fabric50' else '11/7/7/3/4/4/13/19'
            assert f'clocks={clocks} packet=16/16' in text
            held_cycles=44 if ratio=='fabric50' else 40
            assert f'FIXED_MAC_FINAL_RECEIPT commands={commands} receipts={commands} released_snapshots=1 held_cycles={held_cycles}' in text
            assert 'MANAGED_CONTROL_RESTORED_TX CPU_restart=1 frames=2 packet_reads=16 replies=16' in text
            assert 'I1_FIXED_RESET common_cold=1 fixed_clocks_paused=1 stale_proofs_cleared=1' in text
            if cancel:
                assert 'cancel_accepted_before_held=1 real_terminal_join=1' in text and 'runtime_park_edges=0' in text
            else:
                assert 'MANAGED_CONTROL_STATISTICS retained_drops=2 recovered_once=1 retained_config=1' in text
                assert 'MANAGED_CONTROL_BLOCKERS real_CSR_reply=1 config_images_consumed=1 MDIO_policy_boundary=1' in text
        results[label]=dict(seconds=c['elapsed_seconds'],returncode=c['returncode'],log_sha256=sha(p/(label+'.log')))
    recordhash[group]=sha(p/'receipt.json')
result=dict(status='PASS_REAL_POSITIVES_CHECKPOINT' if a.positive_checkpoint else 'PASS_SCOPED_FIXED_MAC_PLATFORM_PROTOCOL',whole_matrix_complete=not a.positive_checkpoint,label='Dynamic protocol simulation, NOT hardware frequency switching',
  verifier_sha256=sha(__file__),production_source_files=len(list((R/'src/main/scala').rglob('*.scala'))),
  default_sv_byte_identical=248,enabled_platform_sv=len(platform['rtl_sha256']),adapter_positive=6,adapter_ordinary_negative=4,
  real_i1_positive=4,real_i1_ordinary_negative=0 if a.positive_checkpoint else 5,real_i1=results,records=recordhash,exact_historical_source_differences=changes,
  guest_non_elf_artifact_sha256=common_guest,production_assertion_sites=519,fixed_source_hz=125000000,integrated_rx_payload_dma=False,late_cancel_after_park=False,
  integrated_fixed_mac_paused_reset=False,physical_gate_drp_qualified=False,hardware_default_changed=False,
  archive_manifest_wip2_note='SCOPE.md was appended after WIP2 manifest generation; other manifest entries must still hash-match. Immutable historical manifest is preserved.')
print(json.dumps(result,indent=2))
