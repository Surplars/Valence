#!/usr/bin/env python3
"""Build and verify static RV64GC tools without touching a rootfs or hardware."""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import struct
import subprocess
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
CORE_REV='1f483d5b8316753a742cbf5590caf5bd0a4e4777'
CORE_FILES={'LICENSE.md','core_list_join.c','core_main.c','core_matrix.c','core_state.c','core_util.c','coremark.h'}

def clockmon_profiles():
    spec=importlib.util.spec_from_file_location('clockmon_profiles',HERE/'clockmon.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.SNAPSHOT_PROFILES


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def file_record(path):
    p=Path(path)
    return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}

def static_elf(path):
    data=path.read_bytes()
    if len(data)<64 or data[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',data,18)[0]!=243:
        raise RuntimeError('not an RV64 little-endian ELF')
    if struct.unpack_from('<I',data,48)[0]&6 != 4:
        raise RuntimeError('ELF is not LP64D')
    off=struct.unpack_from('<Q',data,32)[0]
    size,count=struct.unpack_from('<HH',data,54)
    if size<56 or not count or off+size*count>len(data):raise RuntimeError('invalid ELF headers')
    if any(struct.unpack_from('<I',data,off+i*size)[0] in (2,3) for i in range(count)):
        raise RuntimeError('not statically linked')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--cc',default='riscv64-linux-gnu-gcc')
    parser.add_argument('--host-cc',default='gcc')
    parser.add_argument('--readelf',default='riscv64-linux-gnu-readelf')
    parser.add_argument('--qemu',type=Path,required=True)
    parser.add_argument('--sysroot',type=Path,required=True)
    parser.add_argument('--coremark',type=Path,default=ROOT/'simulator/build/cloud-linux-image/coremark-official')
    parser.add_argument('--coremark-receipt',type=Path,default=ROOT/'simulator/build/cloud-linux-image/metadata/coremark-source-receipt.json')
    args=parser.parse_args()
    out=args.out.resolve(); out.mkdir(parents=True,exist_ok=True)
    # Never leave a stale success receipt on a failed rebuild.
    receipt=out/'tools-build.json'
    if receipt.exists():raise RuntimeError('Use a new output directory; an existing frozen receipt must not be replaced')
    for name in ('bin','lib','share','objects','tests','source'): (out/name).mkdir(exist_ok=True)
    env=dict(os.environ);env.pop('CPATH',None);env.pop('LIBRARY_PATH',None)
    commands=[];tests=[]
    def run(command,label,expected=0,timeout=120):
        command=[str(x) for x in command];started=time.monotonic()
        result=subprocess.run(command,cwd=ROOT,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout)
        log=out/'tests'/(label+'.log');log.write_text(result.stdout)
        row={'label':label,'command':command,'returncode':result.returncode,'expected_returncode':expected,
             'elapsed_seconds':round(time.monotonic()-started,6),'log':file_record(log)}
        commands.append(row)
        if result.returncode!=expected:raise RuntimeError(label+' failed; see '+str(log))
        return result.stdout
    original=json.loads(args.coremark_receipt.read_text())
    if (original.get('revision')!=CORE_REV or original.get('status')!='EXACT_SEVEN_FILES_MATCH' or
            set(original.get('files',{})) != CORE_FILES or original.get('upstream')!='https://github.com/eembc/coremark.git'):
        raise RuntimeError('Pinned CoreMark source receipt required')
    for name,entry in original['files'].items():
        p=args.coremark/name
        if p.stat().st_size!=entry['bytes'] or sha(p)!=entry['sha256']:raise RuntimeError('CoreMark changed: '+name)
    sources=sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    shared=[ROOT/'fpga/firmware/analyze_netboot_log.py',ROOT/'fpga/firmware/test_analyze_netboot_log.py']
    input_records=[file_record(p) for p in sources+shared]
    input_records += [file_record(args.coremark/name) for name in original['files']]
    initial={p['path']:p['sha256'] for p in input_records}
    cc_version=run([args.cc,'--version'],'compiler-version').splitlines()[0]
    qemu_version=run([args.qemu,'--version'],'qemu-version').splitlines()[0]
    link_inputs=[]
    for name in ('libc.a','libgcc.a','libgcc_eh.a','crt1.o','crti.o','crtn.o'):
        path=Path(run([args.cc,'-print-file-name='+name],'link-input-'+name).strip()).resolve()
        if not path.is_file() or args.sysroot.resolve() not in path.parents:
            raise RuntimeError('Unbound static runtime input: '+name)
        link_inputs.append(file_record(path))
    flags=['-march=rv64gc','-mabi=lp64d','-O2','-std=c11']
    compile_flags=flags+['-Wall','-Wextra','-Werror']
    specs=[('valence-mem-bench',['mem_bench.c']),('valence-fpu-test',['fpu_test.c','fp_context.S'])]
    for target, names in specs:
        objects=[]
        for name in names:
            obj=out/'objects'/(name+'.o')
            run([args.cc,*compile_flags,'-c',HERE/name,'-o',obj],target+'-compile-'+name)
            objects.append(obj)
        run([args.cc,*flags,'-static',*objects,'-o',out/'bin'/target],target+'-link')
        static_elf(out/'bin'/target)
    core_names=['core_main.c','core_list_join.c','core_matrix.c','core_state.c','core_util.c']
    objects=[]
    for source in [args.coremark/n for n in core_names]+[HERE/'coremark_port/core_portme.c']:
        obj=out/'objects'/(source.name+'.o')
        run([args.cc,*flags,'-DITERATIONS=0','-DPERFORMANCE_RUN=1','-I',HERE/'coremark_port','-I',args.coremark,
             '-c',source,'-o',obj],'coremark-compile-'+source.name)
        objects.append(obj)
    run([args.cc,*flags,'-static',*objects,'-o',out/'lib/coremark'],'coremark-link')
    static_elf(out/'lib/coremark')
    elf_attributes={}
    for name,path in [('mem',out/'bin/valence-mem-bench'),('fpu',out/'bin/valence-fpu-test'),('coremark',out/'lib/coremark')]:
        attrs=run([args.readelf,'-A',path],'elf-attributes-'+name)
        match=re.search(r'Tag_RISCV_arch: \"([^\"]+)\"',attrs)
        if not match:raise RuntimeError('Missing actual RISC-V architecture attributes')
        arch=match.group(1)
        allowed={'rv64i','m','a','f','d','c','zicsr','zifencei','zmmul','zaamo','zalrsc'}
        extensions={re.split(r'[0-9]',part,1)[0] if not part.startswith('rv64') else 'rv64i' for part in arch.split('_')}
        if not arch.startswith('rv64i') or extensions!=allowed:
            raise RuntimeError('Unexpected linked ISA requirement: '+arch)
        elf_attributes[name]=arch
    run(['python3',HERE/'test_tools.py','-v'],'python-tools-tests')
    run(['python3',shared[1],'-v'],'shared-netboot-analyzer-tests')
    host=out/'tests/mem-host'
    run([args.host_cc,'-std=c11','-O2','-Wall','-Wextra','-Werror',HERE/'mem_bench.c','-o',host],'mem-host-build')
    memargs=['--sizes-kib','4,32,256','--iterations','2','--eviction-mib','1']
    run([host,*memargs],'mem-host-positive')
    run([args.qemu,out/'bin/valence-mem-bench',*memargs],'mem-qemu-positive')
    for i,invalid in enumerate((['--iterations','0'],['--sizes-kib','-1'],['--sizes-kib','1,,2'],
                                ['--mode','cold'],['--eviction-mib','0'],['--unknown','1'])):
        run([host,*invalid],'mem-argument-negative-'+str(i),expected=2)
    run([args.host_cc,'-std=c11','-O2','-DVALENCE_TEST_CORRUPT',HERE/'mem_bench.c','-o',out/'tests/mem-corrupt'],'mem-corrupt-build')
    corrupt_log=run([out/'tests/mem-corrupt',*memargs],'mem-corruption-negative',expected=1)
    if 'MEM_BENCH_FAIL write word=0' not in corrupt_log:raise RuntimeError('memory negative did not reach its oracle')
    run([args.qemu,out/'bin/valence-fpu-test','--bench'],'fpu-qemu-positive')
    run([args.qemu,out/'bin/valence-fpu-test','--bad'],'fpu-argument-negative',expected=2)
    for macro,name in [('VALENCE_TEST_CORRUPT','corrupt'),('VALENCE_TEST_BAD_SYSCALL','syscall')]:
        negative=out/'tests'/('fpu-'+name)
        run([args.cc,*compile_flags,'-static','-D'+macro,HERE/'fpu_test.c',HERE/'fp_context.S','-o',negative],'fpu-'+name+'-build')
        negative_log=run([args.qemu,negative],'fpu-'+name+'-negative',expected=1)
        if 'F/D ARITHMETIC PASS' not in negative_log or 'LINUX FP CONTEXT FAIL' not in negative_log:
            raise RuntimeError('FPU negative did not reach its oracle')
    short=run([args.qemu,out/'lib/coremark','0','0','0x66','1000'],'coremark-qemu-short')
    valid=run([args.qemu,out/'lib/coremark','0','0','0x66','0'],'coremark-qemu-valid',timeout=90)
    spec=importlib.util.spec_from_file_location('coremark_evaluate',HERE/'coremark.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    if module.evaluate(short)['iterations_per_second'] is not None:raise RuntimeError('short CoreMark score not rejected')
    if module.evaluate(valid)['iterations_per_second'] is None:raise RuntimeError('long CoreMark not validated')
    # Bind actual test bytes, compiler products and shared parser before receipt generation.
    for path,digest in initial.items():
        if sha(path)!=digest:raise RuntimeError('source drift during build: '+path)
    installed=[]
    def install_record(source,relative,destination,kind,mode,linkage):
        target=out/relative
        if source.resolve()!=target.resolve():shutil.copyfile(source,target)
        target.chmod(int(mode,8))
        installed.append(dict(path=relative,destination=destination,sha256=sha(target),bytes=target.stat().st_size,
                              kind=kind,mode=mode,linkage=linkage,needed=[]))
    for name in ('valence-mem-bench','valence-fpu-test'):
        install_record(out/'bin'/name,'bin/'+name,'/usr/local/bin/'+name,'elf','0755','static')
    install_record(out/'lib/coremark','lib/coremark','/usr/local/lib/valence-tools/coremark','elf','0755','static')
    for source,name in ((HERE/'coremark.py','valence-coremark'),(HERE/'clockmon.py','valence-clockmon'),
                        (HERE/'dma_bench.py','valence-dma-bench'),(shared[0],'valence-netboot-report')):
        install_record(source,'bin/'+name,'/usr/local/bin/'+name,'python','0755','python3-stdlib')
    install_record(HERE/'README.md','share/README.md','/usr/local/share/valence-tools/README.md','document','0644','none')
    install_record(args.coremark/'LICENSE.md','share/CoreMark-LICENSE.md','/usr/local/share/valence-tools/CoreMark-LICENSE.md','license','0644','none')
    license=args.sysroot/'usr/share/doc/libc6-dev-riscv64-cross/copyright'
    install_record(license,'share/glibc-copyright','/usr/local/share/valence-tools/glibc-copyright','license','0644','none')
    # Preserve sources and object files for relinking these static binaries; not installed into target RAM.
    for p in sources:
        dest=out/'source/common_tools'/p.relative_to(HERE);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
    for p in shared:shutil.copyfile(p,out/'source'/p.name)
    for name in original['files']:
        dest=out/'source/coremark'/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(args.coremark/name,dest)
    test_receipt={'schema':1,'status':'PASS_HOST_AND_QEMU_USERMODE_ONLY','commands':commands,
                  'qualification':{'hardware_dma_executed':False,'hardware_clockmon_read':False,'soc_performance_measured':False,'target_kernel_fpu_context_qualified':False},
                  'source_inputs':input_records,'compiler':cc_version,'qemu':qemu_version}
    testfile=out/'tests/verification.json';testfile.write_text(json.dumps(test_receipt,indent=2)+'\n')
    record={'schema':1,'stage':'tools_ready_host_qemu_only','target':dict(architecture='riscv64',isa='rv64gc',abi='lp64d'),
            'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'compiler':cc_version,
            'flags':flags+['-static'],'linked_elf_architectures':elf_attributes,'static_link_inputs':link_inputs,'coremark_revision':CORE_REV,'coremark_source_receipt':file_record(args.coremark_receipt),
            'files':installed,'required_debian_packages':['python3','iperf3','iproute2','procps','time','gawk'],
            'clockmon_snapshot_profiles':clockmon_profiles(),
            'source_inputs':input_records,'verification':file_record(testfile),'qualification':test_receipt['qualification'],
            'static_relinking':'objects/ and source/ retained in build delivery; official libc copyright accompanies installed binaries'}
    receipt.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'receipt':str(receipt),'sha256':sha(receipt),'installed_files':len(installed),'installed_bytes':sum(x['bytes'] for x in installed),'tests':'PASS_HOST_AND_QEMU_USERMODE_ONLY'}))

if __name__=='__main__':main()
