#!/usr/bin/env python3
"""Independent architectural ledger comparison, never a substitute for native oracles."""
import argparse, copy, hashlib, json, re
from pathlib import Path

EXACT = (
    'MANAGED_CONTROL_LINK_READY', 'MANAGED_CONTROL_CONFIG_INITIALIZED',
    'MANAGED_CONTROL_PHY_READY', 'MANAGED_CONTROL_IDLE_BLOCKERS',
    'MANAGED_CONTROL_BLOCKERS', 'I1_PACKET_TX_TAIL_HELD', 'I1_PACKET_TX_WIRE',
    'I1_PACKET_HOME_MEMORY', 'I1_PACKET_JOINED_RETIREMENT',
    'I1_PACKET_CPU_COHERENT_READBACK', 'MANAGED_CONTROL_STATISTICS',
    'MANAGED_CONTROL_RESTORED_TX', 'I1_FIXED_FRESH_PROOF', 'I1_FIXED_RESET',
    'I1_PACKET_TERMINAL_BACKPRESSURE', 'MANAGED_CONTROL_CSR_ACCEPTED',
    'MANAGED_CONTROL_CSR_COMPLETED',
)
VARIABLE = {
    'I1_PACKET_BOOT': {'retires'},
    'MANAGED_CONTROL_HELD': {'pending'},
    'I1_FIXED_POST_RESUME_OWNER': {'real_MMIO'},
    'I1_FIXED_TX_TIMER_OWNER': {'source'},
    'MANAGED_CONTROL_EPOCH_PASS': {'AXI_R', 'AXI_B'},
}

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def fields(line): return dict(re.findall(r'(\w+)=([^\s]+)', line))
def select(lines, name): return [fields(s) for s in lines if s.split(' ', 1)[0] == name]
def require(condition, reason):
    if not condition: raise AssertionError(reason)
def production(r):
    return {n: h for n, h in r['source_sha256'].items()
            if n.startswith(('src/main/scala/', 'src/main/resources/'))}

def compare(b, c, bl, cl):
    require(b['status'] == c['status'] == 'PASS_SELECTED_CASES', 'both selected cases must pass native runner')
    require(not b.get('bootstrap_accelerated', False) and c['bootstrap_accelerated'], 'baseline/candidate bootstrap modes')
    for r in (b,c):
        require(r['requested_subset']['scenario']=='normal' and r['requested_subset']['single_ratio']=='unrelated', 'normal/unrelated only')
    require(production(b)==production(c), 'production source equality')
    require(b['guest']['symbols']==c['guest']['symbols'], 'guest symbols equality')
    for n in ('guest.bin','guest.hex','guest_symbols.svh'):
        require(b['guest']['artifacts'][n]==c['guest']['artifacts'][n], 'guest artifact equality: '+n)
    require(b['clock_cases']==c['clock_cases'], 'actual clock vector equality')
    for name in EXACT:
        x,y=select(bl,name),select(cl,name)
        require(x and x==y, 'stable ordered ledger mismatch: '+name)
    for name,ignored in VARIABLE.items():
        trim=lambda rows: [{k:v for k,v in r.items() if k not in ignored} for r in rows]
        x,y=select(bl,name),select(cl,name)
        require(x and trim(x)==trim(y), 'stable partial ledger mismatch: '+name)
    require(len(select(cl,'I1_PACKET_TX_WIRE'))==2,'exactly two TX wire frames')
    for lines in (bl,cl):
        held=select(lines,'MANAGED_CONTROL_HELD');require(len(held)==1 and int(held[0]['pending'],16)>0,'retained statistics pending')
        final=select(lines,'I1_FIXED_FINAL_LEDGER');require(len(final)==1,'one final independent ledger')
        f=final[0];timer=f['timer'].split('/');require(timer[0]==timer[1] and int(timer[0])>3,'final timer conservation')
        require(f['UI_read']==f['source_read'] and f['UI_B']==f['source_B'] and f['retained_IRQ']=='1','final UI/source/IRQ conservation')
        passed=select(lines,'MANAGED_CONTROL_EPOCH_PASS');require(len(passed)==1,'one final PASS')
        require(passed[0]['AXI_R']==f['UI_read'] and passed[0]['AXI_B']==f['UI_B'],'final PASS/AXI ledger agreement')
        owner=select(lines,'I1_FIXED_POST_RESUME_OWNER')[0]['real_MMIO'].split('/')
        require(int(owner[0])==int(owner[1])+1,'new MMIO reply really retained')
        coverage=select(lines,'I1_FIXED_AXI_CHANNEL_COVERAGE');require(len(coverage)==1,'one AXI coverage ledger')
        require(all(int(coverage[0][k])>0 for k in ('W_before_AW_beats','AW_stalls','W_stalls','AR_stalls')),'nonzero channel coverage')
    require(len(select(cl,'MANAGED_CONTROL_BOOTSTRAP_REJOIN'))==1,'one permanent fabric rejoin')
    rejoin=select(cl,'MANAGED_CONTROL_BOOTSTRAP_REJOIN')[0]
    require(rejoin['released']=='1' and rejoin['exact_fabric_clock']=='1','real release and permanent rejoin witness')
    return dict(stable_exact_markers=list(EXACT),partial_markers={k:sorted(v) for k,v in VARIABLE.items()},unchanged_production_sources=len(production(b)),matched_guest_artifacts=['guest.bin','guest.hex','guest_symbols.svh'])

def main():
    p=argparse.ArgumentParser();p.add_argument('baseline',type=Path);p.add_argument('candidate',type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args()
    b,c=[json.loads(x.read_text()) for x in (a.baseline,a.candidate)]
    logs=[x.parent/'unrelated-tx-normal.log' for x in (a.baseline,a.candidate)]
    for r,l in zip((b,c),logs):require(sha(l)==r['logs_sha256'][l.name],'native log hash')
    bl,cl=[x.read_text().splitlines() for x in logs];result=compare(b,c,bl,cl)
    tests=[]
    for label,mutation in (
        ('lost_second_packet',lambda xs: xs[:next(i for i,s in enumerate(xs) if s.startswith('I1_PACKET_TX_WIRE'))]+xs[next(i for i,s in enumerate(xs) if s.startswith('I1_PACKET_TX_WIRE'))+1:]),
        ('wrong_retained_statistics',lambda xs:[s.replace('retained_drops=2','retained_drops=3') for s in xs]),
        ('broken_timer_conservation',lambda xs:[re.sub(r'timer=\d+/\d+','timer=58/57',s) if s.startswith('I1_FIXED_FINAL_LEDGER') else s for s in xs]),
    ):
        try:compare(b,c,bl,mutation(cl))
        except AssertionError as e:tests.append(dict(name=label,result='PASS_EXPECTED_COMPARISON_REJECTION',reason=str(e)))
        else:raise AssertionError('comparison selftest failed: '+label)
    result.update(status='PASS_ARCHITECTURAL_LEDGER_COMPARISON',baseline_receipt_sha256=sha(a.baseline),candidate_receipt_sha256=sha(a.candidate),script_sha256=sha(Path(__file__)),selftests=tests,scope='normal/unrelated only; not full matrix, production clock separation, gate, DRP, physical timing, or board proof')
    a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
