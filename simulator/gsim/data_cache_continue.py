#!/usr/bin/env python3
"""Continue a completed positive baseline after only the old full-sweep negative timed out.

Reuses both hash-verified board models and baseline positive runs. Never changes
firmware, enlarges watchdogs, or repeats completed positive workloads.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import data_cache_capacity as exp
from data_cache_finalize import compare_models
from analyze_frontend_perf import rows
from frontend_perf import board_rows
from control_stage import negative


def source_manifest():
    return {**exp.inputs(),**exp.hashes([Path(__file__),exp.common.HERE/'data_cache_finalize.py',
      *exp.common.HERE.glob('*.py'),*exp.common.HERE.joinpath('harness').glob('*.h'),
      *[exp.common.HERE/'harness'/p for p in ['board_boot.cpp','board_coremark.cpp','ddr_bench_app.cpp',
        'rv64gc_board.cpp','data_cache_locality_negative.cpp','data_cache_directory.cpp']]])}


def record(log,stem,trace=None):
    text=log.read_text();assert 'PASS' in text and not re.search(r'\bFAIL\b',text)
    r={'dcache':rows(text,'DCACHE'),'ipc':board_rows(text,stem=='board_coremark'),'log_sha256':exp.perf.sha256(log)}
    for row in r['dcache']:
        assert row['misses']==row['empty']+row['replacements']==row['read_miss']+row['write_miss']
        assert sum(row['state_'+str(i)] for i in range(12))==row['cycles']
        if row['name']=='whole_run':assert row['writeback_beats']==8*row['writeback_lines']
    if stem=='board_coremark':
        r['ticks']=int(re.search(r'Total ticks\s*:\s*(\d+)',text)[1]);r['retired_pc_sha256']=exp.perf.sha256(trace)
        assert r['retired_pc_sha256']==exp.PC_HASH and trace.stat().st_size//8==360528 and r['ipc'][1]['retired']==360528
        r['crc_lines']=[l for l in text.splitlines() if 'crc' in l.lower()]
    if stem=='data_cache_locality':
        r['phases']=[{'bytes':int(b),'phase':p,'ticks':int(t)} for b,p,t in re.findall(r'LOCALITY size=(\d+) phase=(\w+) ticks=(\d+) PASS',text)]
        r['ipc']=rows(text,'BOARD_IPC');r['complete']=rows(text,'COMPLETE')
        assert len(r['phases'])==len(r['dcache'])==len(r['ipc'])==32 and len(r['complete'])==8
        phase_names=('read_cold_1','read_warm_3','write_warm_3','write_flush','copy_warm_3','copy_flush','chase_cold_1','chase_warm_3')
        assert [(p['bytes'],p['phase']) for p in r['phases']]==[(b,p) for b in (1024,2048,4096,8192) for p in phase_names]
        assert [p['name'] for p in r['dcache']]==[f'locality_{i}' for i in range(32)]
        assert [p['name'] for p in r['ipc']]==[f'locality_{i}' for i in range(32)]
        assert [(t['size'],t['phase']) for t in r['complete']]==[(b,p) for b in (1024,2048,4096,8192) for p in ('write','copy')]
        for i,t in enumerate(r['complete']):
            offset=8*(i//2)+(2 if t['phase']=='write' else 4)
            assert t['ticks']>=sum(p['ticks'] for p in r['phases'][offset:offset+2])
        r['total_guest_cycles']=int(re.search(r'GSIM D-cache locality application: PASS cycles=(\d+)',text)[1])
        assert r['total_guest_cycles']<10000000
    return r


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--raw',type=Path,required=True)
    ap.add_argument('--frozen-inputs',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();out=a.out.resolve();out.mkdir(exist_ok=False)
    raw=json.loads(a.raw.read_text());old=a.raw.parent.resolve();frozen=json.loads(a.frozen_inputs.read_text())
    assert raw['status']=='FAIL_SOURCE_DRIFT' and 'timed out after 120 seconds' in raw['failure']
    assert frozen['captured_before_any_locality_driver_exists'] and frozen['source_sha256']==exp.inputs()
    assert str(old/'dcache2k-data_cache_locality') in raw['failure'] and '--inject-mismatch' in raw['failure']
    assert str(exp.common.BUILD/'dcache-locality-firmware-20261007/ddr_bench.bin') in raw['failure']
    drift=sorted(p for p,v in raw['source_sha256'].items() if frozen['source_sha256'][p]!=v)
    assert drift==sorted(str(exp.common.ROOT/p) for p in ('fpga/firmware/ddr_bench.c','simulator/gsim/harness/data_cache_locality.cpp'))
    assert all(exp.perf.sha256(Path(p))==v for p,v in raw['artifacts'].items())
    for group in ('source_sha256','additional_compiled_inputs','final_locality_firmware'):
        assert all(exp.perf.sha256(Path(p))==v for p,v in frozen[group].items())
    models={'dcache2k':exp.BASE/'board-model','dcache4k':old/'board-model'}
    report={'status':'RUNNING','source_sha256':source_manifest(),'profile':'staged-fetch-turnover','fixed':raw['fixed'],
      'semantics':raw['semantics'],'coupling':raw['coupling'],'limitations':raw['limitations'],
      'model_comparison':compare_models(models['dcache2k']/'BoardSocGsim.fir',models['dcache4k']/'BoardSocGsim.fir'),
      'baseline_geometry':raw['baseline_geometry'],'candidate_geometry':raw['candidate_geometry'],
      'memory_geometry':raw['memory_geometry'],'instruction_geometry':raw['instruction_geometry'],
      'raw_receipt':{'path':str(a.raw),'sha256':exp.perf.sha256(a.raw),'status':raw['status'],'failure':raw['failure']},
      'input_epoch_reconciliation':{'frozen_inputs':str(a.frozen_inputs),'sha256':exp.perf.sha256(a.frozen_inputs),
        'reason':'Final continuous-total firmware and matching host formatter were frozen before the first locality driver. Raw preliminary source/firmware snapshot predates this authorized refinement. Baseline positive artifacts are retained; only its optional full-sweep negative exceeded its old 120-second helper watchdog. This continuation uses a first-ROI independent negative and a 10M-cycle/8KiB-output positive guard. No model rebuild or positive baseline repeat.'},
      'budgets':{'positive_locality_guest_cycles':10000000,'positive_uart_bytes':8192,'positive_wall_seconds':900,
                 'short_negative_guest_cycles':2000000,'short_negative_uart_bytes':2048,'negative_wall_seconds':120},
      'short_checks_receipt':raw['short_checks_receipt'],'runs':{}}
    cxx,_=exp.common.compiler();exact=exp.common.BUILD/'coremark-rvc-20261007/rv64imc'
    locality=exp.common.BUILD/'dcache-locality-firmware-20261007';firmware=exp.BASE/'firmware'
    lstart,lstop=exp.rdtime(locality/'ddr_bench.elf','locality_start'),exp.rdtime(locality/'ddr_bench.elf','locality_stop')
    images={'board_coremark':exact/'coremark_board.bin','ddr_bench_app':firmware/'ddr_bench.bin',
            'rv64gc_board':firmware/'rv64gc_smoke.bin','data_cache_locality':locality/'ddr_bench.bin'}
    report['firmware_sha256']=exp.hashes([*images.values(),exact/'coremark_board.elf',locality/'ddr_bench.elf'])
    assert exp.perf.sha256(images['board_coremark'])==exp.RVC_HASH
    def compile_driver(model,driver,binary):
        exp.common.run([cxx,*exp.flags(model),'-DUART_DIVISOR=1','-DBOARD_CPU_HZ=100000000','-DBOARD_UART_BAUD=460800',
          '-DUART_EXTRA_STOP_BITS=0','-DDDR_MODEL=1','-DBOARD_DDR_BYTES=2147483648ULL','-DAPP_TIMEBASE_HZ=50000000',
          f'-DLOCALITY_START_PC={lstart}ULL',f'-DLOCALITY_STOP_PC={lstop}ULL',*model.glob('*.o'),driver,'-ldl','-o',binary],log=binary.with_suffix('.compile.log'))
    try:
        for label,model in models.items():
            objs=list(model.glob('*.o'));assert objs
            expected=raw['runs']['dcache2k']['model_object_sha256'] if label=='dcache2k' else raw['artifacts']
            assert all(expected[str(p)]==exp.perf.sha256(p) for p in objs)
            report['runs'][label]={'model_object_sha256':exp.hashes(objs),'workloads':{}}
            for stem,image in images.items():
                binary=out/(label+'-'+stem);driver=binary.with_suffix('.cpp');log=binary.with_suffix('.log');trace=binary.with_suffix('.retired-pcs.bin')
                if label=='dcache2k':
                    for suffix in ('','.cpp','.compile.log','.log','.retired-pcs.bin','.negative.log'):
                        src=old/(label+'-'+stem+suffix)
                        if src.is_file():shutil.copy2(src,out/src.name)
                    if stem=='data_cache_locality':assert exp.perf.sha256(driver)==frozen['source_sha256'][str(exp.common.HERE/'harness/data_cache_locality.cpp')]
                else:
                    text=(old/('dcache2k-'+stem+'.cpp')).read_text()
                    if stem=='data_cache_locality':
                        anchor='        test.observer=LocalityObserver::sample; test.observerContext=&perf;'
                        assert text.count(anchor)==1
                        text=text.replace(anchor,'''        struct Bounded { LocalityObserver *perf; Test *test; } bounded{&perf,&test};
        test.observer=[](SBoardSocGsim &d,void *p){auto &g=*static_cast<Bounded*>(p);
            check(g.test->cycles<10000000 && g.test->received.size()<8192,"positive locality guest/output budget");
            LocalityObserver::sample(d,g.perf);}; test.observerContext=&bounded;''')
                    driver.write_text(text);compile_driver(model,driver,binary)
                    env={**exp.ENV,'FRONTEND_RETIRE_TRACE':str(trace)} if stem=='board_coremark' else exp.ENV
                    exp.common.run([binary,image],env=env,log=log,timeout=900)
                    if stem=='rv64gc_board':negative(binary,(image,),'firmware independent anchor/context failure',binary.with_suffix('.negative.log'))
                r=record(log,stem,trace);r['executable_sha256']=exp.perf.sha256(binary)
                report['runs'][label]['workloads'][stem]=r
                (out/'progress.json').write_text(json.dumps(report,indent=2)+'\n');print(label,stem,'PASS',flush=True)
            neg=out/(label+'-locality-short-negative');negdriver=neg.with_suffix('.cpp')
            shutil.copy2(exp.common.HERE/'harness/data_cache_locality_negative.cpp',negdriver)
            compile_driver(model,negdriver,neg)
            exp.rejected(neg,(images['data_cache_locality'],),'short locality independent backing-memory mismatch',neg.with_suffix('.log'))
            report['runs'][label]['short_locality_negative']={'binary_sha256':exp.perf.sha256(neg),'log':neg.with_suffix('.log').read_text()}
        b=report['runs']['dcache2k']['workloads'];c=report['runs']['dcache4k']['workloads']
        assert b['board_coremark']['ticks']==486605 and b['board_coremark']['crc_lines']==c['board_coremark']['crc_lines']
        report['coremark_tick_reduction_percent']=100*(486605-c['board_coremark']['ticks'])/486605
        report['locality_comparison']=[{**x,'candidate_ticks':y['ticks'],'tick_reduction_percent':100*(x['ticks']-y['ticks'])/x['ticks']} for x,y in zip(b['data_cache_locality']['phases'],c['data_cache_locality']['phases'])]
        report['continuous_completion_comparison']=[{**x,'candidate_ticks':y['ticks'],'tick_reduction_percent':100*(x['ticks']-y['ticks'])/x['ticks']} for x,y in zip(b['data_cache_locality']['complete'],c['data_cache_locality']['complete'])]
        boundary=exp.common.BUILD/'data-cache-directory-boundary-20261007-r2/receipt.json';br=json.loads(boundary.read_text())
        assert br['status']=='PASS_FULL_DIRECTORY_BOUNDARY'
        assert all(exp.perf.sha256(Path(p))==v for p,v in br['source_sha256'].items())
        assert all(exp.perf.sha256(Path(p))==v for p,v in br['artifact_sha256'].items())
        report['full_directory_boundary']={'path':str(boundary),'sha256':exp.perf.sha256(boundary),'runs':br['runs']}
        report['status']='PASS_MATCHED_DCACHE_CAPACITY'
    except Exception as e:report['status']='FAIL';report['failure']=str(e);raise
    finally:
        if report['source_sha256']!=source_manifest():report['status']='FAIL_SOURCE_DRIFT'
        assert report['firmware_sha256']==exp.hashes([*images.values(),exact/'coremark_board.elf',locality/'ddr_bench.elf'])
        report['artifact_sha256']=exp.hashes(p for p in out.rglob('*') if p.is_file() and p.name!='receipt.json')
        (out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    assert report['status']=='PASS_MATCHED_DCACHE_CAPACITY';print(out/'receipt.json')
if __name__=='__main__':main()
