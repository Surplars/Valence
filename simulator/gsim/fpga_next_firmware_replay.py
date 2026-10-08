#!/usr/bin/env python3
"""Replay the checkpointed OpenSBI/U-Boot guest on an explicitly frozen board.

No firmware build/port changes. A passed model's exact objects, inputs and guest
are checked before a new bounded guest-only replay. A timeout is incomplete,
not a functional pass. This does not qualify physical hardware or Linux.
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

IMAGE_SHA256 = '5addbabefc52bc37a40a62a64f7d819b57dc09f1cb5af094434d598f33023504'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--model-receipt',type=Path,required=True)
    ap.add_argument('--image',type=Path,required=True)
    ap.add_argument('--elf',type=Path,required=True)
    ap.add_argument('--tag',required=True)
    ap.add_argument('--max-cycles',type=int,default=8000000)
    ap.add_argument('--seconds',type=int,default=300)
    a=ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.tag):ap.error('unsafe tag')
    if a.max_cycles<=0 or a.max_cycles>8000000 or a.seconds<=0 or a.seconds>300:
        ap.error('this checkpoint replay is bounded to8Mcycles/300seconds')
    if sha(a.image)!=IMAGE_SHA256 or a.image.stat().st_size!=2312856:
        raise RuntimeError('guest differs from the checkpointed exact payload')
    proof=a.model_receipt.resolve();root=proof.parent;baseline=json.loads(proof.read_text())
    if not str(baseline.get('status','')).startswith('PASS_FPGA_NEXT_BOARD'):
        raise RuntimeError('expected a passed FPGA-next board model receipt')
    model=root/'model';units=sorted(model.glob('BoardSocGsim[0-9]*.cpp'))
    artifacts=[model/'BoardSocGsim.fir',model/'BoardSocGsim.h',*units,*[p.with_suffix('.o') for p in units]]
    if not units:raise RuntimeError('frozen board model empty')
    binding={}
    for p in artifacts:
        name=p.relative_to(root).as_posix();expected=baseline['artifacts'].get(name)
        if not expected or sha(p)!=expected:raise RuntimeError('frozen model artifact mismatch: '+name)
        binding[name]=expected
    includes=common.HERE/'harness'
    support=[includes/'board_boot.cpp',*sorted(includes.glob('*.h'))]
    for p in support:
        name=p.relative_to(common.ROOT).as_posix()
        if baseline['inputs'].get(name)!=sha(p):raise RuntimeError('host memory/harness differs: '+name)
    out=common.BUILD/('fpga-next-firmware-'+a.tag);out.mkdir(parents=True,exist_ok=False)
    cxx,version=common.compiler();exe=out/'run';harness=includes/'board_uboot_checkpoint.cpp'
    defines=['-DUART_DIVISOR=1','-DBOARD_CPU_HZ=100000000','-DBOARD_UART_BAUD=460800','-DUART_EXTRA_STOP_BITS=0',
        '-DDDR_MODEL=1','-DBOARD_DDR_BYTES=2147483648ULL','-DDDR_MULTI_ID_MODEL=1','-DDDR_BENCHMARK_MODEL=1',
        '-DDDR_READ_CREDITS=8','-DDDR_READ_LATENCY=32','-DDDR_READ_BEAT_GAP=1','-DBOARD_CYCLE_LIMIT=8000000ULL']
    build=[cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',*defines,
        '-I'+str(model),'-I'+str(includes),harness,*[p.with_suffix('.o') for p in units],'-ldl','-o',exe]
    record={'schema':'valence-fpga-next-guest-replay-v1','status':'RUNNING','model_receipt_sha256':sha(proof),
        'model_inputs':baseline['inputs'],'model_artifacts':binding,'guest_sha256':sha(a.image),'guest_bytes':a.image.stat().st_size,
        'elf_sha256':sha(a.elf),'harness_sha256':sha(harness),'support_sha256':{p.name:sha(p) for p in support},
        'compiler':version,'build_command':list(map(str,build)),'source_classification':'EXPLICIT_FROZEN_MODEL_GUEST_ONLY',
        'limits':['No firmware feature/port work','No physical FPGA/MIG/CDC qualification','No Linux boot claim']}
    try:
        common.run(build,log=out/'compile.log',timeout=180)
        record['executable_sha256']=sha(exe)
        dis=subprocess.check_output(['riscv64-unknown-elf-objdump','-d','--disassemble=semihosting_enabled',a.elf],text=True)
        match=re.search(r'^\s*([0-9a-f]+):.*\bebreak\b',dis,re.M)
        semihost='0x'+match[1] if match else '0'
        cmd=[exe,a.image.resolve(),str(a.max_cycles),str(a.seconds),semihost,'valence-uboot> ']
        record['run_command']=list(map(str,cmd))
        started=time.monotonic()
        with (out/'console.log').open('w') as stream:
            result=subprocess.run(list(map(str,cmd)),stdout=stream,stderr=subprocess.STDOUT,timeout=a.seconds+15,
                env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        record['seconds']=time.monotonic()-started;record['exit']=result.returncode
        text=(out/'console.log').read_text(errors='replace')
        record['console_sha256']=sha(out/'console.log')
        record['status']='PASS_FROZEN_FIRMWARE_REPLAY' if result.returncode==0 and 'UBOOT_GSIM_PASS' in text else \
            'INCOMPLETE_BOUNDED_BUDGET' if 'budget exhausted' in text else 'FAIL_FIRMWARE_REPLAY'
        for p in artifacts:
            if sha(p)!=binding[p.relative_to(root).as_posix()]:raise RuntimeError('model changed during replay')
        if sha(a.image)!=record['guest_sha256'] or sha(harness)!=record['harness_sha256']:
            raise RuntimeError('guest/harness changed during replay')
        print(text[-8000:])
    except BaseException as error:
        record['status']='FAIL';record['error']=str(error);raise
    finally:
        (out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
    print(record['status']+' '+str(out/'receipt.json'))
    return 0 if record['status'].startswith('PASS') else 2


if __name__=='__main__':raise SystemExit(main())
