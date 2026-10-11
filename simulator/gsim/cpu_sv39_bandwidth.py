#!/usr/bin/env python3
"""Fresh actual S-mode CPU Bare/Sv39 throughput, fixed capacities and AXI service.

Baseline versus previously qualified bandwidth policy batch; no capacity gain.
No synthesis, board/Linux execution or ISA-compliance/NEMU claim.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import run as common

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def inputs():
    paths = list((common.ROOT / 'src/main').rglob('*.scala'))
    paths += list((common.ROOT / 'third_party/berkeley-hardfloat/src/main').rglob('*.scala'))
    paths += list((common.ROOT / 'src/test/scala/ooo').glob('*.scala'))
    paths += [Path(__file__), common.ROOT / 'build.mill', common.ROOT / '.mill-version',
              common.HERE / 'run.py', common.HERE / 'config/toolchain.json',
              common.HERE / 'payloads/cpu_sv39_bandwidth.S', common.HERE / 'payloads/cpu_hot_bandwidth.ld']
    paths += [common.HERE / 'harness' / n for n in ('cpu_sv39_bandwidth.cpp','board_boot.cpp',
               'board_ddr_benchmark.h','performance_observer.h','mshr_occupancy.h')]
    return {str(p.relative_to(common.ROOT)): sha(p) for p in sorted(set(paths))}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag',required=True)
    ap.add_argument('--profiles',nargs='+',choices=('baseline','reuse','batch','flow','scheduled','accepted','admission',
                    'admission-retained'),
                    default=['baseline','accepted'])
    ap.add_argument('--sizes',nargs='+',type=int,choices=(4096,65536),default=[4096,65536])
    ap.add_argument('--reps',type=int,choices=(1,2,4),default=2)
    args=ap.parse_args()
    if not re.fullmatch('[A-Za-z0-9_-]+',args.tag):ap.error('unsafe tag')
    out=common.BUILD/('cpu-sv39-bandwidth-'+args.tag);out.mkdir(parents=True,exist_ok=False)
    frozen=inputs()
    state={'status':'RUNNING','source_sha256':frozen,'profiles':args.profiles,'sizes':args.sizes,
        'reps':args.reps,'commands':[],'cases':{},'artifacts':{},'scope':__doc__,
        'geometry':{'issue':2,'LSU':2,'ROB':16,'PRF':48,'DTLB':8,'ITLB':8,'PTE_cache':4,
            'I_L1_bytes':32768,'D_L1_bytes':32768,'read_MSHR':2,'writeback':2,'DDR_shared':4,'DDR_write':2},
        'events':['d_tlb_hit','d_walk','d_pte_physical_read','d_pte_cache_hit','i_tlb_hit','i_walk',
            'i_pte_physical_read','d_translation_busy','ingress_blocked','waiting_walk',
            'translated_blocked','checked_head_blocked','physical_offer_blocked','upstream_blocked',
            'virtual_reply_blocked','physical_request','physical_reply','cache_offer_blocked',
            'fetch_wait','lsu_start_blocked','flush','physical_owner_full','translated_full','checked_full']}
    def save():(out/'receipt.json').write_text(json.dumps(state,indent=2)+'\n')
    def guard():
        if inputs()!=frozen:raise RuntimeError('source changed during matched CPU measurement')
    def step(name,command,expected=0,anchor=None,timeout=900):
        guard();print('+ '+' '.join(map(str,command)),flush=True)
        start=time.monotonic();log=out/(name+'.log')
        with log.open('x') as stream:
            r=subprocess.run(list(map(str,command)),cwd=common.ROOT,stdout=stream,stderr=subprocess.STDOUT,
                timeout=timeout,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        text=log.read_text();state['commands'].append({'name':name,'argv':list(map(str,command)),
            'exit':r.returncode,'expected':expected,'seconds':time.monotonic()-start,'log_sha256':sha(log)});save()
        if (expected==0 and r.returncode!=0) or (expected!=0 and r.returncode==0) or (anchor and anchor not in text):
            raise RuntimeError(name+'\n'+text[-5000:])
        return text
    save()
    try:
        gsim,cxx=common.setup(False)
        state['toolchain']={**common.LOCK,'compiler':common.compiler()[1],'gsim_sha256':sha(gsim)}
        fw=out/'guest';fw.mkdir()
        march=['-march=rv64im_zicsr_zifencei','-mabi=lp64','-mno-relax']
        step('guest',[ 'riscv64-unknown-elf-gcc',*march,'-nostdlib','-nostartfiles','-Wl,--no-relax',
            '-Wl,--build-id=none','-T',common.HERE/'payloads/cpu_hot_bandwidth.ld',
            common.HERE/'payloads/cpu_sv39_bandwidth.S','-o',fw/'guest.elf'])
        step('guest-bin',['riscv64-unknown-elf-objcopy','-O','binary',fw/'guest.elf',fw/'guest.bin'])
        symbols={}
        for line in step('guest-symbols',['riscv64-unknown-elf-nm','-n',fw/'guest.elf']).splitlines():
            words=line.split()
            if len(words)==3 and words[2] in ('bw_begin','bw_end','bw_drain','bw_done'):symbols[words[2]]=int(words[0],16)
        if len(symbols)!=4:raise RuntimeError('missing guest markers')
        (fw/'cpu_sv39_symbols.h').write_text(''.join(f'#define {k.upper()} {v}ULL\n' for k,v in symbols.items()))
        state['symbols']=symbols
        base=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
            '-DDDR_MODEL=1','-DDDR_MULTI_ID_MODEL=1','-DDDR_BENCHMARK_MODEL=1',
            '-DBOARD_CPU_HZ=100000000','-DBOARD_UART_BAUD=460800','-DUART_DIVISOR=1',
            '-DBOARD_DDR_BYTES=2147483648ULL','-DDDR_READ_CREDITS=8',
            '-DDDR_READ_LATENCY=32','-DDDR_READ_BEAT_GAP=1','-DBOARD_CYCLE_LIMIT=2600000ULL',
            '-I'+str(fw)]
        for profile in args.profiles:
            model=out/profile;model.mkdir()
            step(profile+'-elaborate',['mill','-i','IonSoC.test.runMain','ooo.CpuSv39BandwidthGsimMain',model,profile])
            step(profile+'-generate',[gsim,'--threads=1','--dir='+str(model),model/'BoardSocGsim.fir'])
            objects=[]
            for i,unit in enumerate(sorted(model.glob('BoardSocGsim[0-9]*.cpp'))):
                obj=unit.with_suffix('.o');objects.append(obj)
                step(profile+'-compile-'+str(i),[cxx,*base,'-I'+str(model),'-c',unit,'-o',obj])
            step(profile+'-link',[cxx,*base,'-I'+str(model),common.HERE/'harness/cpu_sv39_bandwidth.cpp',
                *objects,'-o',model/'run'])
            state['cases'][profile]={}
            for size in args.sizes:
                for op in range(3):
                    for mode in range(2):
                        key=f'{size}-{op}-{mode}'
                        text=step(profile+'-'+key,[model/'run',fw/'guest.bin',mode,op,size,args.reps],
                            anchor='CPU_SV39_PASS',timeout=600)
                        row=next(l for l in text.splitlines() if l.startswith('CPU_SV39_RESULT '))
                        fields=dict(w.split('=') for w in row.split()[1:])
                        state['cases'][profile][key]={k:(float(v) if k=='payload_MiBps' else int(v)) for k,v in fields.items()};save()
            for injection,anchor,op in (('read','CPU read data mismatch',0),('memory','final copied/stored memory mismatch',2),
                                       ('trap','unexpected CPU trap cause',0)):
                step(profile+'-negative-'+injection,[model/'run',fw/'guest.bin',1,op,4096,1,'--inject-'+injection],
                     expected=1,anchor=anchor,timeout=120)
        for profile,cases in state['cases'].items():
            for size in args.sizes:
                for op in range(3):
                    a=cases[f'{size}-{op}-0'];b=cases[f'{size}-{op}-1']
                    for field in ('retired','pc_hash','loads','stores'):
                        if a[field]!=b[field]:raise RuntimeError('Bare/Sv39 architectural ROI drift: '+field)
                        for other,records in state['cases'].items():
                            for mode in range(2):
                                if cases[f'{size}-{op}-{mode}'][field]!=records[f'{size}-{op}-{mode}'][field]:
                                    raise RuntimeError('policy architectural ROI drift: '+field)
        guard()
        state['artifacts']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='receipt.json'}
        state['status']='PASS_ACTUAL_S_MODE_CPU_SV39_BANDWIDTH';save();print(state['status'],flush=True)
    except Exception as e:
        state['status']='FAIL';state['error']=str(e);save();raise

if __name__=='__main__':main()
