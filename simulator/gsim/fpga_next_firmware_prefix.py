#!/usr/bin/env python3
"""Fixed-endpoint prefix of the exact checkpoint payload, using saved board objects."""
import argparse,hashlib,json,os,re,subprocess,time
from pathlib import Path
import run as common
IMAGE_SHA256='5addbabefc52bc37a40a62a64f7d819b57dc09f1cb5af094434d598f33023504'
ELF_SHA256='613b842f33007118c4a795ebf56dbd0b981b814b3f5c42e8eea0eb960e1b94bc'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--model-receipt',type=Path,required=True)
    ap.add_argument('--image',type=Path,required=True);ap.add_argument('--elf',type=Path,required=True);ap.add_argument('--tag',required=True)
    args=ap.parse_args();assert re.fullmatch('[A-Za-z0-9_-]+',args.tag)
    assert sha(args.image)==IMAGE_SHA256 and args.image.stat().st_size==2312856
    assert sha(args.elf)==ELF_SHA256
    proof=args.model_receipt.resolve();parent=json.loads(proof.read_text());assert parent['status'].startswith('PASS_FPGA_NEXT_BOARD')
    root=proof.parent;model=root/'model';units=sorted(model.glob('BoardSocGsim[0-9]*.cpp'));assert units
    modelFiles=[model/'BoardSocGsim.fir',model/'BoardSocGsim.h',*units,*[p.with_suffix('.o') for p in units]]
    binding={}
    for p in modelFiles:
        name=str(p.relative_to(root));assert sha(p)==parent['artifacts'][name],name;binding[str(p)]=sha(p)
    support=[common.HERE/'harness/board_boot.cpp',*sorted((common.HERE/'harness').glob('*.h'))]
    for p in support:
        name=str(p.relative_to(common.ROOT));assert parent['inputs'].get(name)==sha(p),'exact source checkout/support mismatch: '+name
    out=common.BUILD/('fpga-next-firmware-'+args.tag);out.mkdir(parents=True,exist_ok=False)
    harness=common.HERE/'harness/board_uboot_prefix.cpp';cxx,version=common.compiler();exe=out/'run'
    definitions=['-DUART_DIVISOR=1','-DBOARD_CPU_HZ=100000000','-DBOARD_UART_BAUD=460800','-DUART_EXTRA_STOP_BITS=0',
        '-DDDR_MODEL=1','-DBOARD_DDR_BYTES=2147483648ULL','-DDDR_MULTI_ID_MODEL=1','-DDDR_BENCHMARK_MODEL=1',
        '-DDDR_READ_CREDITS=8','-DDDR_READ_LATENCY=32','-DDDR_READ_BEAT_GAP=1','-DBOARD_CYCLE_LIMIT=8000000ULL']
    build=[cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',*definitions,
        '-I'+str(model),'-I'+str(common.HERE/'harness'),harness,*[p.with_suffix('.o') for p in units],'-ldl','-o',exe]
    state={'status':'RUNNING','model_receipt':str(proof),'model_receipt_sha256':sha(proof),'model_inputs':parent['inputs'],
        'model_artifacts':binding,'guest_sha256':sha(args.image),'guest_bytes':args.image.stat().st_size,'elf_sha256':sha(args.elf),
        'source_checkout':subprocess.check_output(['git','rev-parse','HEAD'],cwd=common.ROOT,text=True).strip(),
        'inputs':{str(p):sha(p) for p in [harness,Path(__file__).resolve(),common.HERE/'run.py',*support]},
        'compiler':version,'endpoint_cycles':1000000,'wall_safety_seconds':300,'complete_uboot_pass':False,
        'trace_format':'24-byte records: host cycle, commit lane, retired PC, each unsigned64 little-endian; SHA256 binds complete stream',
        'endpoint_convention':'Total Test ticks include reset/ROM programming/calibration; observer begins after that setup; no tick after1000000',
        'limits':['Bounded firmware prefix only, not U-Boot completion or an independent full-ISA oracle','No guest rebuild/port changes or RTL model build',
            'No host serial commands; UART TX observed','Backing sentinel covers accepted AXI writes and host memory, not dirty lines never evicted',
            'Fixed endpoint may retain accepted outstanding transactions; no final drain is fabricated','No physical hardware/MIG/CDC/Linux boot claim']}
    def save(): (out/'receipt.json').write_text(json.dumps(state,indent=2)+'\n')
    try:
        state['build_command']=list(map(str,build));save();common.run(build,log=out/'compile.log',timeout=180)
        state['executable_sha256']=sha(exe)
        dis=subprocess.check_output(['riscv64-unknown-elf-objdump','-d','--disassemble=semihosting_enabled',args.elf],text=True)
        match=re.search(r'^\s*([0-9a-f]+):.*\bebreak\b',dis,re.M);semihost='0x'+match[1] if match else '0'
        cmd=[exe,args.image.resolve(),'1000000','300',semihost,'valence-uboot> '];state['run_command']=list(map(str,cmd));save()
        start=time.monotonic();env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0','UBOOT_PREFIX_TRACE':str(out/'retired.trace')}
        with (out/'console.log').open('w') as stream:
            result=subprocess.run(list(map(str,cmd)),stdout=stream,stderr=subprocess.STDOUT,env=env,timeout=315)
        state['seconds']=time.monotonic()-start;state['exit']=result.returncode
        text=(out/'console.log').read_text(errors='replace');state['console_sha256']=sha(out/'console.log')
        snapshots=[line for line in text.splitlines() if line.startswith('UBOOT_PREFIX_SNAPSHOT ')]
        if snapshots:state['snapshot']={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',snapshots[-1])}
        if result.returncode==0 and 'UBOOT_FIXED_PREFIX_COMPLETE cycles=1000000 complete_uboot_pass=0' in text:
            assert state['snapshot']['cycles']==1000000 and state['snapshot']['endpoint']==1
            state['status']='COMPLETE_FIXED_ENDPOINT_PREFIX'
        elif 'budget exhausted' in text:state['status']='INCOMPLETE_WALL_SAFETY'
        else:state['status']='FAIL_PREFIX_REPLAY'
        trace=out/'retired.trace'
        if trace.exists():
            state['retirement_trace_sha256']=sha(trace);state['retirement_trace_bytes']=trace.stat().st_size
            if 'snapshot' in state:assert trace.stat().st_size==24*state['snapshot']['commits']
        state['backing_lines']=[line for line in text.splitlines() if line.startswith('UBOOT_PREFIX_BACKING ')]
        state['trap_lines']=[line for line in text.splitlines() if line.startswith('UBOOT_PREFIX_TRAP ')]
        for path,digest in {**binding,**state['inputs']}.items():assert sha(path)==digest,'input changed during replay: '+path
        assert sha(args.image)==state['guest_sha256'] and sha(args.elf)==state['elf_sha256']
        state['artifacts']={str(p.relative_to(out)):sha(p) for p in out.iterdir() if p.is_file() and p.name!='receipt.json'}
        print(text[-6000:])
    except BaseException as error:state['status']='FAIL';state['error']=str(error);raise
    finally:save()
    print(json.dumps({'status':state['status'],'receipt':str(out/'receipt.json')}))
    return 0 if state['status']=='COMPLETE_FIXED_ENDPOINT_PREFIX' else 2
if __name__=='__main__':raise SystemExit(main())
