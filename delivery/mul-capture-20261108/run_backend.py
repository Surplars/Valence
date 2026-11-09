#!/usr/bin/env python3
"""Fresh matched public-port backend proof of MUL capture plus delivered storage options.
No CPU/fabric/throughput or physical qualification. No IRQ/fault cases are executed.
"""
import argparse, hashlib, json, os, re, shutil, signal, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'fpga/common'))
import scala_compile_receipt
sys.path.insert(0,str(ROOT/'simulator/gsim'))
import run as common


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    p.add_argument('--phase',choices=['generate','execute'],required=True)
    a=p.parse_args(); receipt=scala_compile_receipt.verify_receipt(a.receipt,ROOT)
    gsim,cxx=common.setup(False)
    cp=os.pathsep.join(receipt['runClasspathEntries'])
    java=['java','-Xmx3g','-XX:ActiveProcessorCount=2','-Dchisel.project.root='+str(ROOT),'-cp',cp]
    out=a.out.resolve(); host=ROOT/'simulator/gsim/harness/mul_registered_load_capture'
    if a.phase=='generate':out.mkdir(parents=True,exist_ok=False)
    elif not (out/'generation.json').is_file():raise ValueError('Verified generated models required')
    commands=[]; report={'status':'RUNNING','phase':a.phase,'source_root':str(ROOT),'receipt_sha256':sha(a.receipt),'host_sha256':sha(host/'backend_host.cpp'),'oracle_sha256':sha(host/'pending_store_proof_reference.h'),'commands':commands,'limits':['Backend only; no current CPU/fabric runtime or performance claim','No fault/IRQ cases','Sampled process-group RSS, not cgroup hard limit']}
    cpus=sorted(os.sched_getaffinity(0))[:2]; report['cpus']=cpus
    env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0:abort_on_error=1','UBSAN_OPTIONS':'halt_on_error=1'}
    def run(name,cmd,timeout=900,expected=0):
        start=time.monotonic(); stdout=out/(name+'.stdout');stderr=out/(name+'.stderr')
        record={'name':name,'command':list(map(str,cmd)),'timeout_seconds':timeout,'exit':None,'peak_sampled_group_rss_bytes':0};commands.append(record)
        cmd=['taskset','-c',','.join(map(str,cpus)),*map(str,cmd)]
        failure=None
        with stdout.open('x') as so,stderr.open('x') as se:
            proc=subprocess.Popen(cmd,cwd=ROOT,stdout=so,stderr=se,env=env,start_new_session=True)
            while proc.poll() is None:
                rss=0
                for info in Path('/proc').glob('[0-9]*/stat'):
                    try:
                        fields=info.read_text().rsplit(')',1)[1].split()
                        if int(fields[2])==proc.pid:rss+=int(fields[21])*os.sysconf('SC_PAGE_SIZE')
                    except (OSError,ValueError,IndexError):pass
                record['peak_sampled_group_rss_bytes']=max(record['peak_sampled_group_rss_bytes'],rss)
                avail=int(re.search(r'MemAvailable:\s+(\d+)',Path('/proc/meminfo').read_text())[1])*1024
                if rss>4*1024**3:failure='sampled process-group RSS over 4 GiB'
                elif avail<512*1024**2 or shutil.disk_usage(out).free<512*1024**2:failure='reserve below 512 MiB'
                elif time.monotonic()-start>timeout:failure='timeout'
                if failure:
                    os.killpg(proc.pid,signal.SIGTERM)
                    try:proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
                    break
                time.sleep(.2)
            record['exit']=proc.wait()
        record.update(elapsed_seconds=time.monotonic()-start,stdout_sha256=sha(stdout),stderr_sha256=sha(stderr))
        if failure:raise RuntimeError(name+': '+failure)
        if record['exit']!=expected:raise RuntimeError(name+': unexpected exit '+str(record['exit']))
        return stdout.read_text(),stderr.read_text()
    try:
        if a.phase=='generate':
            for mode in ('off','on'):
                model=out/mode
                run(mode+'-emit',java+['ooo.MulLoadOperandCaptureBackendGsimMain',model,mode,'combined-storage'])
                fir=model/'MulLoadOperandCaptureBackendGsim.fir'
                run(mode+'-lower',[os.environ['FIRTOOL'],fir,'--verilog','--disable-all-randomization','--default-layer-specialization=enable','--verification-flavor=if-else-fatal','-o',model/'lowered.sv'])
                run(mode+'-generate',[gsim,'--threads=1','--cpp-max-size-KB=4096','--dir='+str(model),fir])
            report['status']='GENERATED_REQUIRES_PUBLIC_ABI_REVIEW'
        else:
            generation=json.loads((out/'generation.json').read_text())
            if generation['status']!='GENERATED_REQUIRES_PUBLIC_ABI_REVIEW' or generation['receipt_sha256']!=sha(a.receipt):raise ValueError('Generation receipt mismatch')
            review=json.loads((out/'public-abi-review.json').read_text())
            if review['status']!='PASS_PUBLIC_TAP_ABI':raise ValueError('Public ABI review required')
            descriptors=json.loads((host/'cases.json').read_text())
            accepted=[]
            for mode in ('off','on'):
                model=out/mode; header=model/'MulLoadOperandCaptureBackendGsim.h'
                if review['header_sha256'][mode]!=sha(header):raise ValueError('Reviewed header changed')
                flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(model),'-I'+str(host)]
                objects=[]
                for i,cpp in enumerate(sorted(model.glob('MulLoadOperandCaptureBackendGsim[0-9]*.cpp'))):
                    obj=model/('dut'+str(i)+'.o');run(mode+'-compile-'+str(i),[cxx,*flags,'-c',cpp,'-o',obj]);objects.append(obj)
                obj=model/'host.o';run(mode+'-host',[cxx,*flags,'-c',host/'backend_host.cpp','-o',obj]);objects.append(obj)
                run(mode+'-link',[cxx,'-fsanitize=address,undefined',*objects,'-ldl','-o',model/'run'])
                ds=[case['variants'][mode] for case in descriptors['positive_cases'] if case['name'] not in ('load-error','page-fault')]
                if mode=='on':ds+=descriptors['observer_cases']
                for d in ds:
                    so,se=run(d['id'],[model/'run',*d['args']],timeout=d['timeout_s'],expected=d['expected_exit'])
                    if any(x not in so+se for x in d.get('required',[])):raise ValueError('Missing witness '+d['id'])
                    if any(x in so+se for x in d.get('forbidden',[])):raise ValueError('Forbidden marker '+d['id'])
                    if d['kind']=='positive' and se:raise ValueError('Positive stderr '+d['id'])
                    regex=d.get('stderr_fullmatch')
                    if regex and not re.fullmatch(regex,se):raise ValueError('Negative stderr mismatch '+d['id'])
                    accepted.append(d['id'])
            report['accepted']=accepted;report['status']='PASS_MATCHED_BACKEND_DIRECTED'
        scala_compile_receipt.verify_receipt(a.receipt,ROOT)
    except BaseException as e:
        report.update(status='FAIL',error=type(e).__name__+': '+str(e));raise
    finally:
        (out/(a.phase+'-receipt.json')).write_text(json.dumps(report,indent=2)+'\n')
        if a.phase=='generate':(out/'generation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'commands':len(commands),'output':str(out)}))
if __name__=='__main__':main()
