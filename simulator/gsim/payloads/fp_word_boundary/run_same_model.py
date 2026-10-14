#!/usr/bin/env python3
"""Link a bounded guest host to an existing, hash-qualified BoardSoc model; never generate RTL/model."""
import argparse, hashlib, json, os, re, shutil, subprocess, time
from pathlib import Path

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser()
    for name in ('model','link-receipt','service','activate','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();src=Path(__file__).resolve().parent
    for key in ('model','link_receipt','service','activate','out'):setattr(a,key,getattr(a,key).resolve())
    assert not a.out.exists(), 'choose a fresh output directory'
    d=json.loads(a.link_receipt.read_text())
    links=[x for x in d['commands'] if x.get('label') in ('copy-link','on-link')]
    assert len(links)==1, 'one original same-model link contract required'
    original=links[0]['argv'];first_include=next(i for i,x in enumerate(original) if x.startswith('-I'))
    flags=original[1:first_include]
    assert all(not x.endswith(('.cpp','.o')) for x in flags)
    assert '-DDDR_READ_LATENCY=32' in flags and '-DDDR_READ_BEAT_GAP=1' in flags and '-DDDR_READ_CREDITS=8' in flags
    assert '-DDDR_BENCHMARK_MODEL=1' in flags
    expected={Path(x['unit']).with_suffix('.o').name:x['sha256'] for x in d['objects']}
    objects=sorted(a.model.glob('BoardSocGsim*.o'))
    assert {x.name:sha(x) for x in objects}==expected,'model objects differ from supplied qualification'
    model_before={x.name:sha(x) for x in objects+[a.model/'BoardSocGsim.h',a.model/'BoardSocGsim.fir']}
    required_service=('board_boot.cpp','board_ddr_benchmark.h','fabric_idle_service.h')
    for f in required_service:
        assert sha(a.service/f)==d['host_files']['harness/'+f], f+' does not match qualified service'
    a.out.mkdir(parents=True);(a.out/'host').mkdir();(a.out/'guest').mkdir()
    for f in required_service:shutil.copyfile(a.service/f,a.out/'host'/f)
    for f in ('guest.S','guest.ld','cases.json','expected_oracle.py'):shutil.copyfile(src/f,a.out/'guest'/f)
    shutil.copyfile(src/'host.cpp',a.out/'host'/'host.cpp')
    receipt={'status':'RUNNING','source_files':{str(x.relative_to(src)):sha(x) for x in sorted(src.iterdir()) if x.is_file()},'link_receipt':str(a.link_receipt),'link_receipt_sha256':sha(a.link_receipt),'model':str(a.model),'model_before':model_before,'service_files':{f:sha(a.service/f) for f in required_service},'flags':flags,'commands':[],'negative_class':'guest expected literal corruption; not a DUT mutant'}
    receiptpath=a.out/'receipt.json'
    def save():receiptpath.write_text(json.dumps(receipt,indent=2)+'\n')
    def run(label,argv,expected_exit=0,contains=()):
        log=a.out/(label+'.log');t=time.monotonic()
        command=['/bin/bash','--noprofile','--norc','-c','source "$1"; shift; exec "$@"','fp-board',str(a.activate),*map(str,argv)]
        env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0')
        with log.open('w') as out:r=subprocess.run(command,stdout=out,stderr=subprocess.STDOUT,env=env,timeout=240)
        record={'label':label,'argv':command,'exit':r.returncode,'seconds':time.monotonic()-t,'log_sha256':sha(log)}
        receipt['commands'].append(record);save();s=log.read_text()
        assert (r.returncode==0 if expected_exit==0 else r.returncode!=0),(label,r.returncode,s[-3000:])
        for text in contains:assert text in s,(label,'missing',text,s[-3000:])
        print(label,'PASS',round(record['seconds'],2),'seconds',flush=True)
        return s
    try:
        run('oracle',['python3',a.out/'guest'/'expected_oracle.py'],contains=('FP_LITERAL_RATIONAL_ORACLE_PASS cases=20',))
        elf=a.out/'guest'/'guest.elf';image=a.out/'guest'/'guest.bin'
        run('guest-compile',['riscv64-unknown-elf-gcc','-march=rv64gc','-mabi=lp64d','-mcmodel=medany','-mno-relax','-nostdlib','-nostartfiles','-Wl,--no-relax','-Wl,--build-id=none','-Wl,--defsym=BOARD_RAM_BYTES=536870912','-T'+str(a.out/'guest'/'guest.ld'),a.out/'guest'/'guest.S','-o',elf])
        run('guest-binary',['riscv64-unknown-elf-objcopy','-O','binary',elf,image])
        symbols=run('guest-symbols',['riscv64-unknown-elf-nm','-n',elf])
        sym={parts[2]:int(parts[0],16) for line in symbols.splitlines() if len(parts:=line.split())==3}
        cases=json.loads((src/'cases.json').read_text());pcs=[sym[f'fp_convert_case_{i}'] for i in range(len(cases))];passes=[sym[f'fp_convert_pass_{i}'] for i in range(len(cases))]
        assert len(set(pcs+passes))==2*len(cases)
        assert sym['fp_boundary_expected'] % 8 == 0, 'literal doubleword alignment'
        assert sym['fp_boundary_expected'] - 0x80200000 + 8 <= image.stat().st_size
        (a.out/'guest'/'fp_case_pcs.h').write_text('#pragma once\nstatic constexpr unsigned fpCaseCount='+str(len(cases))+';\nstatic constexpr uint64_t fpCasePc[]={' + ','.join(hex(x)+'ULL' for x in pcs)+'};\nstatic constexpr uint64_t fpPassPc[]={' + ','.join(hex(x)+'ULL' for x in passes)+'};\nstatic constexpr uint64_t fpSuccessPc='+hex(sym['fp_guest_success'])+'ULL;\nstatic constexpr uint64_t fpFailurePc='+hex(sym['fp_guest_failure'])+'ULL;\n')
        receipt['guest']={f:sha(a.out/'guest'/f) for f in ('guest.S','guest.ld','guest.elf','guest.bin','fp_case_pcs.h')};receipt['pc_anchors']={'convert':pcs,'checked':passes,'success':sym['fp_guest_success'],'failure':sym['fp_guest_failure']};save()
        binary=a.out/'run'
        run('host-link',[original[0],*flags,'-I'+str(a.out/'host'),'-I'+str(a.out/'guest'),'-I'+str(a.model),a.out/'host'/'host.cpp',*objects,'-o',binary])
        positive=run('positive',[binary,image],contains=('FP_WORD_BOUNDARY_BOARD_PASS cases=20','RV64GC_BOARD_PASS','context_fprs=32 s_ecall=1'))
        reached=re.findall(r'^FP_BOUNDARY_CASE_REACHED id=(\d+)$',positive,re.M)
        assert reached==list(map(str,range(20))),reached
        negative=run('negative-expected',[binary,image,'--inject-fp-expected'],expected_exit=1,contains=('FP_EXPECTED_LITERAL_CORRUPTED','FP_BOUNDARY_CASE_REACHED id=0','firmware independent anchor/context failure'))
        assert 'FP_WORD_BOUNDARY_BOARD_PASS' not in negative
        assert re.findall(r'^FP_BOUNDARY_CASE_REACHED id=(\d+)$',negative,re.M)==['0']
        receipt['binary_sha256']=sha(binary);receipt['positive_cycles']=int(re.search(r'FP_WORD_BOUNDARY_BOARD_PASS cases=20 cycles=(\d+)',positive)[1]);receipt['status']='PASS'
    except BaseException as e:
        receipt['status']='FAIL';receipt['error']=str(e);raise
    finally:
        receipt['model_after']={x.name:sha(x) for x in objects+[a.model/'BoardSocGsim.h',a.model/'BoardSocGsim.fir']}
        assert receipt['model_after']==model_before,'model mutated during test'
        save()
if __name__=='__main__':main()
