#!/usr/bin/env python3
"""Opt-in actual fixed125 MAC + I1/Home/DMA/debug/DDR/timer epoch integration.

No rate/gate/DRP or physical timing proof. Source is continuously fixed125;
empty preboot fabric/CPU/UI/timer/debug domains pause only to bound PHY init.
All real runtime clocks stay independent; explicit UI/timer/snapshot stalls are
hostile tests. External AXI RAM and Clause22 pins are test models.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location('reused_r20_managed_helpers', HERE/'managed_control_epoch_native.py')
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
base = old.base
TB = HERE/'fixed_mac_epoch_tb.sv'
FIXTURE = ROOT/'src/test/scala/platform/CommonFixedMacEpochMain.scala'
PASS = 'FIXED_MAC_PLATFORM_EPOCH_PASS'
CLOCKS = old.CLOCKS
RATIOS = {'fabric50': (5, 10, 11, 13, 4, 4, 19, 23),
          'fabric71': (11, 7, 7, 3, 4, 4, 13, 19)}
NEGATIVES = dict(old.NEGATIVES, **{
    'final-snapshot': (8, 'FIXED_MAC_ORACLE_FINAL_SNAPSHOT_OWNER', 'FIXED_MAC_NEGATIVE_OLD_RELEASED_SNAPSHOT')})

def sources():
    paths = [Path(__file__).resolve(), TB, FIXTURE, old.PHY_MODEL, old.FIXTURE,
             HERE/'managed_control_epoch_native.py', old.COMPARISON, old.FIXED_RUNNER, old.fixed.BASE,
             HERE/'i1_runtime_network.S', HERE/'i1_runtime_network.ld', ROOT/'build.mill', ROOT/'scripts/cloud/env.sh',
             *old.INHERITED_FIXTURES, *old.MANAGED_FIXTURE_SUPPORT]
    paths += sorted((ROOT/'src/main/scala').rglob('*.scala'))
    paths += sorted((ROOT/'src/main/resources').rglob('*.sv'))
    return {str(p.relative_to(ROOT)): base.sha(p) for p in paths}

def main():
    def interrupt(signum, frame): raise KeyboardInterrupt(str(signum))
    signal.signal(signal.SIGTERM, interrupt); signal.signal(signal.SIGINT, interrupt)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--rtl-dir', type=Path, required=True)
    p.add_argument('--emission-receipt', type=Path, required=True)
    p.add_argument('--single-ratio', choices=RATIOS)
    p.add_argument('--scenario', choices=old.SCENARIOS)
    p.add_argument('--negative-only', choices=NEGATIVES)
    p.add_argument('--native-wall-seconds', type=int, choices=(180,300), default=180,
                   help='Host-only per-native-case ceiling; 300s approved for this bounded r23 matrix')
    p.add_argument('--cross-prefix', default='riscv64-unknown-elf-')
    p.add_argument('--iverilog', default=os.environ.get('IVERILOG', 'iverilog'))
    p.add_argument('--vvp', default=os.environ.get('VVP', 'vvp'))
    a = p.parse_args()
    out = a.out.resolve(); rtl = a.rtl_dir.resolve()
    if out.exists() or not out.parent.is_dir(): p.error('fresh output with existing parent required')
    if not os.environ.get('VALENCE_CLOUD_ENV'): p.error('source scripts/cloud/env.sh first')
    out.mkdir()
    frozen = sources(); files = sorted(rtl.glob('*.sv'))
    record = dict(status='RUNNING', scope=__doc__, source_sha256=frozen, tools={}, cases=[],
        ledgers=[], negative_controls=[], requested_subset=dict(ratio=a.single_ratio, scenario=a.scenario, negative=a.negative_only),
        rtl_sha256={f.name: base.sha(f) for f in files}, fixed_source_hz=125000000,
        real_cpu_home_dma=True, actual_aon_terminal_consumption=True, fixture_producer_closed=False,
        shortened_phy_policy_waits=[256,512], full_ack=False, physical_qualified=False,
        unchanged_hardware_default=True, gate_drp_backend=False, maximum_child_seconds=a.native_wall_seconds, build_child_seconds=180,
        approved_case_wall_budgets=({**{r+'-'+s:300 for r in RATIOS for s in old.SCENARIOS},
                                    **{'negative-'+n:300 for n in NEGATIVES}} if a.native_wall_seconds==300 else {}),
        wall_budget_scope='175.457s measured normal; approved 300s host-only ceiling for bounded r23 cases, no DUT/MDIO/guest timing changes',
        preboot_scope='continuous raw125 MAC; only empty large domains pause, no source rejoin',
        exclusions=['RX payload through real DMA', 'fullACK/gate/DRP', 'unilateral reset', 'board/STA', 'arbitrary external IRQ pulse capture'])
    def check():
        if sources()!=frozen: raise RuntimeError('source drift')
        if {f.name:base.sha(f) for f in files}!=record['rtl_sha256']: raise RuntimeError('RTL drift')
        for n,t in record['tools'].items():
            if base.sha(t['path'])!=t['sha256']: raise RuntimeError('tool drift '+n)
        for n,h in record['guest']['artifacts'].items():
            if base.sha(out/n)!=h: raise RuntimeError('guest drift '+n)
    try:
        emit = json.loads(a.emission_receipt.read_text())
        if emit.get('status')!='PASS_EMIT_ONLY' or emit['rtl_sha256']!=record['rtl_sha256']:
            raise RuntimeError('source-bound emission/RTL required')
        bound = {n:h for n,h in frozen.items() if n.startswith(('src/main/', 'src/test/')) or n=='build.mill'}
        if any(emit['source_sha256'].get(n)!=h for n,h in bound.items()): raise RuntimeError('emission source mismatch')
        record['emission_receipt'] = dict(path=str(a.emission_receipt.resolve()), sha256=base.sha(a.emission_receipt))
        old.guest(out, a.cross_prefix, record)
        native={n:base.tool(getattr(a,n)) for n in ('iverilog','vvp')}
        record['tools'].update(base.tool_hashes(native))
        text='\n'.join(f.read_text() for f in files)
        required=[n for n in old.REQUIRED_MODULES if n!='CommonManagedControlEpochFixture']+[
            'CommonFixedMacEpochFixture','CommonFixedMacRuntimeAdapter','FixedMacBoundary','HeldResponseCdcDataFifo','RegisterClockDomainBridge']
        if any('module '+n not in text for n in required):raise RuntimeError('required real owner absent')
        record['required_modules']=required
        for source in [TB,FIXTURE,Path(__file__).resolve(),old.PHY_MODEL]:
            (out/('source-'+source.name)).write_bytes(source.read_bytes())
        defines=['-g2012','-DSTOP_COND=1','-DASSERT_VERBOSE_COND=1']
        pre=out/'preprocessed.sv'
        rc,_=old.run([native['iverilog'],*defines,'-E','-o',pre,*files],out,'preprocess',180,record)
        if rc:raise RuntimeError('preprocess failed')
        pretext=pre.read_text()
        if any(m not in pretext for m in old.REQUIRED_ASSERTIONS):raise RuntimeError('production assertions missing')
        record['production_assertions']=dict(inline_fatal_sites=pretext.count('$fatal'),required_messages=list(old.REQUIRED_ASSERTIONS),preprocessed_sha256=base.sha(pre))
        binary=out/'sim.vvp'
        rc,_=old.run([native['iverilog'],*defines,'-I',out,'-s','fixed_mac_epoch_tb','-o',binary,*files,old.PHY_MODEL,TB],out,'compile',180,record)
        if rc:raise RuntimeError('native compile failed')
        record['sim_sha256']=base.sha(binary)
        command=[native['vvp'],'-i',binary,'+rom='+str(out/'guest.hex'),'+case=3']
        cases=[]
        if not a.negative_only:
            cases=[(ratio,scenario,None) for ratio in ([a.single_ratio] if a.single_ratio else RATIOS)
                   for scenario in ([a.scenario] if a.scenario else old.SCENARIOS)]
        names=[a.negative_only] if a.negative_only else ([] if a.single_ratio or a.scenario else list(NEGATIVES))
        cases += [(a.single_ratio or 'fabric50','normal',n) for n in names]
        for ratio,scenario,negative in cases:
            label='negative-'+negative if negative else ratio+'-'+scenario
            args=[f'+{c}-half={n}' for c,n in zip(CLOCKS,RATIOS[ratio])]+[f'+managed-scenario={old.SCENARIOS[scenario]}']
            if negative:args += [f'+negative={NEGATIVES[negative][0]}']
            rc,log=old.run(command+args,out,label,a.native_wall_seconds,record)
            if negative:
                _,reject,inject=NEGATIVES[negative]
                if rc==0 or reject not in log or inject not in log or PASS in log:raise RuntimeError('negative not rejected '+label)
                record['negative_controls'].append(dict(name=negative,rejection=reject,injection=inject,passed=True))
            elif rc or PASS not in log:raise RuntimeError('positive failed '+label)
            record['ledgers'] += [dict(case=label,line=l) for l in log.splitlines() if l.startswith(('FIXED_MAC_','MANAGED_CONTROL_','I1_FIXED_','I1_PACKET_'))]
            check()
            if base.sha(binary)!=record['sim_sha256']:raise RuntimeError('binary drift')
            snap=dict(record,status='PASS_NEGATIVE_CASE' if negative else 'PASS_POSITIVE_CASE',completed_case=label,
                      logs_sha256={f.name:base.sha(f) for f in out.glob('*.log')})
            (out/('case-'+label+'.json')).write_text(json.dumps(snap,indent=2)+'\n')
            old.checkpoint(out,record)
            print(snap['status'],label,flush=True)
        check();record['status']='PASS_SELECTED_CASES' if a.single_ratio or a.scenario or a.negative_only else 'PASS_FIXED_MAC_PLATFORM_MATRIX'
    except BaseException as e:
        record.update(status='FAIL',error=repr(e));raise
    finally:
        record['logs_sha256']={f.name:base.sha(f) for f in out.glob('*.log')}
        (out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
        print(record['status'],out,flush=True)
if __name__=='__main__':main()
