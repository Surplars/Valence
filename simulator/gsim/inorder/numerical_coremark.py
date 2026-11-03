#!/usr/bin/env python3
"""Pinned official CoreMark, matched binary/cache/service, independent ISA/CRC and ROI prediction checks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlparse

ROOT=Path(__file__).resolve().parents[3]
PIN='1f483d5b8316753a742cbf5590caf5bd0a4e4777'
sys.path.insert(0,str(ROOT/'simulator/gsim'))
import run as common


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'build'):
        parser.error('fresh output inside repository build/ required')
    reference=json.loads(args.reference.read_text())
    ref_classes=Path(reference['reference_classes']).resolve()
    if not ref_classes.is_relative_to(ROOT/'build'):parser.error('reference must stay inside build/')
    for name,digest in reference['class_sha256'].items():
        if sha(ref_classes/name)!=digest:raise RuntimeError('reference class drift')
    source=ROOT/'simulator/build/coremark-src'
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()!=PIN:
        raise RuntimeError('official CoreMark pin mismatch')
    if subprocess.check_output(['git','status','--porcelain'],cwd=source,text=True).strip():
        raise RuntimeError('CoreMark algorithms/source must remain pristine')
    output.mkdir(parents=True)
    gsim,cxx=common.setup(False)
    metadata=json.loads((ROOT/'out/OrbitalI1/test/runClasspath.json').read_text())['value']
    paths=[Path(value.split(':',3)[3]) for value in metadata]
    if any(not path.exists() and 'resources' not in str(path) for path in paths):
        raise RuntimeError('incomplete runtime classpath')
    runtime=os.pathsep.join(str(path) for path in paths if path.exists())
    files=[ROOT/'build.mill',Path(__file__).resolve(),ROOT/'simulator/gsim/harness/five_stage.cpp',
        ROOT/'simulator/gsim/harness/five_stage_coremark.cpp',ROOT/'simulator/gsim/harness/i1_prediction_metrics.h']
    files+=sorted((ROOT/'src/main/scala/core/inorder').glob('*.scala'))
    files+=sorted((ROOT/'src/test/scala/inorder').glob('*.scala'))
    files+=sorted((ROOT/'simulator/gsim/inorder/coremark_port').glob('*'))
    files+=[ROOT/'simulator/gsim/payloads/coremark_port/start.S',ROOT/'simulator/gsim/payloads/coremark_port/link.ld']
    frozen={str(path.relative_to(ROOT)):sha(path) for path in files if path.is_file()}
    receipt={'status':'RUNNING','source_sha256':frozen,'coremark_revision':PIN,
        'coremark_algorithm_sha256':{name:sha(source/name) for name in
            ('core_list_join.c','core_main.c','core_matrix.c','core_state.c','core_util.c','coremark.h')},
        'scope':'official unmodified algorithms, standard 2000-byte one-iteration O3 short evaluation; not a formal CoreMark score',
        'cpu':'RV64IM fpga8, 32KiB I + 32KiB D, 64-byte direct-mapped precise write-through cache, tagged bimodal BTB128',
        'memory_service':'same round-robin two-port burst server, one owner per port, first-beat latency 1/12 cycles, one cycle per subsequent beat',
        'gsim_sha256':sha(gsim),'commands':[],'profiles':{},'formal_score':False,
        'full_soc_or_board_qualified':False}
    def save():(output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    def run(argv,folder,log,negative=None):
        argv=[str(value) for value in argv]
        receipt['commands'].append({'argv':argv,'log':str(folder/log)})
        save()
        with (folder/log).open('w') as stream:
            result=subprocess.run(argv,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,
                env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        text=(folder/log).read_text()
        if negative:
            if result.returncode==0 or negative not in text:raise RuntimeError('negative not rejected: '+str(folder/log))
        elif result.returncode:raise RuntimeError('failed: '+str(folder/log))
        return text
    def parse(text,prefix):
        rows=[json.loads(line[len(prefix):]) for line in text.splitlines() if line.startswith(prefix)]
        if len(rows)!=1:raise RuntimeError('missing single result: '+prefix)
        return rows[0]
    try:
        payload=output/'payload';payload.mkdir()
        port=ROOT/'simulator/gsim/inorder/coremark_port'
        startup=ROOT/'simulator/gsim/payloads/coremark_port'
        gcc='riscv64-unknown-elf-gcc'
        compiler=subprocess.check_output([gcc,'--version'],text=True).splitlines()[0]
        flags=['-O3','-march=rv64im_zicsr_zifencei','-mabi=lp64','-mcmodel=medany','-mno-relax',
            '-msmall-data-limit=0','-ffreestanding','-fno-builtin','-fno-stack-protector','-nostdlib',
            '-nostartfiles','-DITERATIONS=1','-DPERFORMANCE_RUN=1','-DTOTAL_DATA_SIZE=2000',
            '-DCOMPILER_FLAGS="-O3 -march=rv64im_zicsr_zifencei -mabi=lp64 ITERATIONS=1 TOTAL_DATA_SIZE=2000"',
            '-DCOMPILER_VERSION="'+compiler+'"',
            '-DMEM_LOCATION="GSIM: fixed 32KiB I/D write-through caches; CPU/service configuration recorded separately"']
        algorithms=[source/name for name in ('core_list_join.c','core_main.c','core_matrix.c','core_state.c','core_util.c')]
        run([gcc,*flags,'-I'+str(port),'-I'+str(source),'-T'+str(startup/'link.ld'),startup/'start.S',
             *algorithms,port/'core_portme.c','-lgcc','-o',payload/'coremark.elf'],payload,'build.log')
        run(['riscv64-unknown-elf-objcopy','-O','binary',payload/'coremark.elf',payload/'coremark.bin'],payload,'objcopy.log')
        symbols=subprocess.check_output(['riscv64-unknown-elf-nm','-n',payload/'coremark.elf'],text=True)
        (payload/'symbols.txt').write_text(symbols)
        values={row.split()[-1]:int(row.split()[0],16) for row in symbols.splitlines() if len(row.split())==3}
        receipt['payload']={'compiler':compiler,'flags':flags,'binary_sha256':sha(payload/'coremark.bin'),
            'bytes':(payload/'coremark.bin').stat().st_size,'symbols':{key:hex(values[key]) for key in
                ('coremark_validation_errors','coremark_elapsed_ticks','coremark_crcs')}}
        for role,fast in (('reference',False),('default',False),('fast-division',True)):
            folder=output/role;folder.mkdir()
            classpath=(str(ref_classes)+os.pathsep if role=='reference' else '')+runtime
            flags=['--pipeline=fpga8','--timing-cuts','--dsp-tiled','--icache=32768','--dcache=32768','--predictor=128']
            if fast:flags+=['--fast-division']
            load=folder/'class-load.log'
            run(['java','-Xlog:class+load=info:file='+str(load),'-cp',classpath,'inorder.I1PerformanceCachedMain',folder,'64',*flags],folder,'elaborate.log')
            marker='soc.core.inorder.FiveStageMulDiv source: '
            origins=[Path(unquote(urlparse(line.split(marker,1)[1].strip()).path)).resolve()
                for line in load.read_text().splitlines() if marker in line]
            expected=ref_classes if role=='reference' else ROOT/'out/OrbitalI1/compile.dest/classes'
            if origins!=[expected]:raise RuntimeError('unexpected MDU class origin')
            run([gsim,'--threads=1','--dir='+str(folder),folder/'I1PerformanceCachedCore.fir'],folder,'generate.log')
            cpp=sorted(folder.glob('I1PerformanceCachedCore[0-9]*.cpp'))
            if not cpp:raise RuntimeError('missing actual cached CPU model')
            run([cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                '-DDUT_XLEN=64','-DI1_COREMARK_PREDICTION=1','-I'+str(folder),*cpp,
                ROOT/'simulator/gsim/harness/five_stage_coremark.cpp','-o',folder/'run'],folder,'compile.log')
            rows=[]
            for delay in (1,12):
                argv=[folder/'run',payload/'coremark.bin',hex(values['coremark_validation_errors']),
                    hex(values['coremark_elapsed_ticks']),hex(values['coremark_crcs']),delay]
                text=run(argv,folder,'positive-l'+str(delay)+'.log')
                row=parse(text,'MATCHED_COREMARK_PASS ')
                prediction=parse(text,'I1_COREMARK_PREDICTION ')
                row.update(prediction)
                row.update(memory_latency=delay,roi_ipc=row['roi_instructions']/row['roi_ticks'],
                    whole_ipc=row['retired']/row['cycles'])
                row['roi_branch_accuracy']=row['roi_correct']/row['roi_branches']
                row['roi_branch_mpki']=1000*(row['roi_branches']-row['roi_correct'])/row['roi_instructions']
                row['roi_effective_direction_accuracy']=row['roi_direction_correct']/row['roi_direction_queries']
                row['roi_return_accuracy']=row['roi_returns_correct']/row['roi_returns'] if row['roi_returns'] else None
                row['roi_indirect_accuracy']=row['roi_indirect_correct']/row['roi_indirect'] if row['roi_indirect'] else None
                row['roi_warm_branch_accuracy']=row['roi_warm_correct']/row['roi_warm_branches'] if row['roi_warm_branches'] else None
                pcs=[]
                for line in text.splitlines():
                    if line.startswith('I1_COREMARK_PC '):
                        fields=dict(token.split('=',1) for token in line.split()[1:])
                        pcs.append({key:int(value) for key,value in fields.items()})
                if sum(item['count'] for item in pcs)!=row['roi_branches']:
                    raise RuntimeError('per-PC CoreMark ROI denominator mismatch')
                row['per_static_pc']=pcs
                rows.append(row)
                print(role,'latency',delay,'cycles',row['roi_ticks'],'instructions',row['roi_instructions'],
                    'IPC',round(row['roi_ipc'],6),'branch accuracy',round(row['roi_branch_accuracy'],6),flush=True)
            run([*argv,'--inject'],folder,'negative-register.log','CoreMark independent register oracle mismatch')
            run([*argv,'--inject-prediction-observer'],folder,'negative-prediction.log','prediction observation mismatch')
            receipt['profiles'][role]={'flags':flags,'rows':rows,'register_negative_rejected':True,'prediction_negative_rejected':True}
            save()
        baseline=receipt['profiles']['reference']['rows']
        for role in ('default','fast-division'):
            for before,after in zip(baseline,receipt['profiles'][role]['rows']):
                for key in ('memory_latency','roi_instructions','retired','trace_fnv64','crcfinal'):
                    if before[key]!=after[key]:raise RuntimeError('matched workload differs: '+role+' '+key)
                if after['roi_ticks']>before['roi_ticks']:
                    raise RuntimeError('matched actual CoreMark ROI cycle regression: '+role)
        for relative,digest in frozen.items():
            if sha(ROOT/relative)!=digest:raise RuntimeError('source drift during CoreMark: '+relative)
        receipt['status']='PASS_I1_OFFICIAL_COREMARK_O3_SHORT_ONLY'
    except BaseException as error:
        receipt.update(status='FAIL',error=repr(error));raise
    finally:save()
    print(json.dumps({'status':receipt['status'],'receipt':str(output/'receipt.json')},indent=2))


if __name__=='__main__':main()
