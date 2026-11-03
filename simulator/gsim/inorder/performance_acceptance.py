#!/usr/bin/env python3
"""Actual CPU IPC and committed prediction ledger, with identical fixed memory service."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'simulator/gsim'))
import run as common


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'build'):
        parser.error('fresh output within repository build/ required')
    output.mkdir(parents=True)
    gsim,cxx=common.setup(False)
    values=json.loads((ROOT/'out/OrbitalI1/test/runClasspath.json').read_text())['value']
    paths=[Path(value.split(':',3)[3]) for value in values]
    if any(not path.exists() and 'resources' not in str(path) for path in paths):
        raise RuntimeError('incomplete runtime classpath')
    runtime=os.pathsep.join(str(path) for path in paths if path.exists())
    sources=[ROOT/'build.mill',Path(__file__).resolve(),ROOT/'simulator/gsim/harness/i1_performance.cpp',
             ROOT/'simulator/gsim/harness/five_stage.cpp',ROOT/'simulator/gsim/harness/i1_prediction_metrics.h']
    sources+=sorted((ROOT/'src/main/scala/core/inorder').glob('*.scala'))
    sources+=sorted((ROOT/'src/test/scala/inorder').glob('*.scala'))
    frozen={str(path.relative_to(ROOT)):sha(path) for path in sources}
    receipt={'status':'RUNNING','scope':'nine bounded RV64IM bare-core workloads, fpga8, BTB off/128 entries',
        'service':'one fetch owner and one data owner; always READY; exactly 1 or 7 cycles per accepted request; no RNG jitter',
        'prediction_scope':'actual owner-carried next-PC predictions, reconciled at resolution and retirement',
        'direction_scope':'effective taken/not-taken, excluding branch targets equal to fall-through',
        'warm_scope':'per static control-flow PC, after its first eight committed visits',
        'recovery_scope':'redirect resolution to first target retirement, including an ending EBREAK target',
        'source_sha256':frozen,'gsim_sha256':sha(gsim),'commands':[],'profiles':{},
        'full_isa_or_coremark_qualified':False,'physical_qualified':False}
    def save():
        (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    def run(argv,folder,log,negative=None):
        argv=[str(value) for value in argv]
        receipt['commands'].append({'argv':argv,'log':str(folder/log)})
        save()
        with (folder/log).open('w') as stream:
            result=subprocess.run(argv,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,
                env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        text=(folder/log).read_text()
        if negative:
            if result.returncode==0 or negative not in text:
                raise RuntimeError('negative not rejected independently: '+str(folder/log))
        elif result.returncode:
            raise RuntimeError('failed: '+str(folder/log))
        return text
    try:
        for entries in (0,128):
            name='btb-'+str(entries)
            folder=output/name;folder.mkdir()
            flags=['--pipeline=fpga8','--timing-cuts','--dsp-tiled','--fast-division','--predictor='+str(entries)]
            run(['java','-cp',runtime,'inorder.I1PerformanceCoreMain',folder,'64',*flags],folder,'elaborate.log')
            run([gsim,'--threads=1','--dir='+str(folder),folder/'I1PerformanceCore.fir'],folder,'generate.log')
            cpp=sorted(folder.glob('I1PerformanceCore[0-9]*.cpp'))
            if not cpp:raise RuntimeError('missing performance model')
            run([cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                 '-DDUT_XLEN=64','-DDUT_PIPELINE_STAGES=8','-I'+str(folder),*cpp,
                 ROOT/'simulator/gsim/harness/i1_performance.cpp','-o',folder/'run'],folder,'compile.log')
            text=run([folder/'run'],folder,'positive.log')
            if 'I1_PERFORMANCE_PASS' not in text:raise RuntimeError('performance workload incomplete')
            rows=[]
            for line in text.splitlines():
                if line.startswith('I1_PERF '):
                    values=dict(token.split('=',1) for token in line.split()[1:])
                    row={key:(value if key=='name' else int(value)) for key,value in values.items()}
                    row['whole_workload_ipc']=row['retired']/row['cycles']
                    row['retirement_window_ipc']=row['retired']/row['retirement_window']
                    row['next_pc_accuracy']=row['correct']/row['branches'] if row['branches'] else None
                    row['effective_direction_accuracy']=row['direction_correct']/row['direction_queries'] if row['direction_queries'] else None
                    row['return_target_accuracy']=row['returns_correct']/row['returns'] if row['returns'] else None
                    row['indirect_target_accuracy']=row['indirect_correct']/row['indirect'] if row['indirect'] else None
                    row['warm_next_pc_accuracy']=row['warm_correct']/row['warm_branches'] if row['warm_branches'] else None
                    row['branch_mpki']=1000*row['retired_misses']/row['retired']
                    row['redirect_to_target_retire_mean_cycles']=row['recovery_sum']/row['recovery_count'] if row['recovery_count'] else None
                    rows.append(row)
            if len(rows)!=18:raise RuntimeError('nine cases x two memory latencies required')
            run([folder/'run','--inject-observation'],folder,'negative-observation.log','prediction observation mismatch')
            run([folder/'run','--inject-register-mismatch'],folder,'negative-register.log','independent register oracle mismatch')
            per_pc=[]
            for line in text.splitlines():
                if line.startswith('I1_PRED_PC '):
                    values=dict(token.split('=',1) for token in line.split()[1:])
                    record={key:(value if key=='name' else int(value)) for key,value in values.items()}
                    record['pc_hex']=hex(record['pc'])
                    record['next_pc_accuracy']=record['correct']/record['count']
                    record['warm_next_pc_accuracy']=record['warm_correct']/record['warm_count'] if record['warm_count'] else None
                    per_pc.append(record)
            for row in rows:
                if sum(record['count'] for record in per_pc if (record['name'],record['latency'])==(row['name'],row['latency']))!=row['branches']:
                    raise RuntimeError('per-static-PC denominator differs')
            receipt['profiles'][name]={'flags':flags,'rows':rows,'per_static_pc':per_pc,'observation_negative_rejected':True,
                'register_negative_rejected':True}
            save()
            print(name,'PASS',len(rows),'workloads and both negative controls',flush=True)
        left={(row['name'],row['latency']):row for row in receipt['profiles']['btb-0']['rows']}
        for row in receipt['profiles']['btb-128']['rows']:
            prior=left[row['name'],row['latency']]
            if row['retired']!=prior['retired'] or row['branches']!=prior['branches']:
                raise RuntimeError('prediction profiles changed retired work')
        for relative,digest in frozen.items():
            if sha(ROOT/relative)!=digest:raise RuntimeError('source drift: '+relative)
        receipt['status']='PASS_I1_IPC_PREDICTION_BOUNDED_ONLY'
    except BaseException as error:
        receipt.update(status='FAIL',error=repr(error));raise
    finally:save()
    print(json.dumps({'status':receipt['status'],'receipt':str(output/'receipt.json')},indent=2))


if __name__=='__main__':main()
