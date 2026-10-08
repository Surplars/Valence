#!/usr/bin/env python3
"""Equal-capacity I-cache data-bank packing proof; no physical RAM count or timing claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import run as common
from data_cache_geometry import module

CASES=[('selected-two',2,512,False,True,0x80200000,1<<31),
       ('wide-four',4,512,False,True,0x80010000,None),
       ('wide-prefetch',4,512,True,True,0x80010000,None),
       ('selected-prefetch',2,512,True,True,0x80200000,1<<31),
       ('cross4g-two',2,512,False,True,0xffff0000,131072),
       ('tiny-full-tags',4,4,False,False,0x80010000,None)]


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--tag',required=True)
    ap.add_argument('--build-run',action='store_true');a=ap.parse_args()
    if not a.build_run:
        print(json.dumps({'status':'PREFLIGHT_ONLY','cases':CASES,'timing_tradeoff':'tag-selected way becomes SRAM address MSB',
            'physical_mapping':'UNMEASURED'},indent=2));return
    out=common.BUILD/a.tag;out.mkdir(parents=True,exist_ok=False)
    paths=sorted((common.ROOT/'src').rglob('*.scala'))+[Path(__file__),common.HERE/'run.py',common.HERE/'data_cache_geometry.py',
        common.HERE/'config/toolchain.json',common.ROOT/'build.mill',common.HERE/'harness/instruction_line_cache.cpp',
        common.HERE/'harness/instruction_line_prefetch.cpp',common.HERE/'harness/instruction_hit_stability.cpp']
    def hashes():return {str(p.relative_to(common.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report={'status':'RUNNING','source_sha256':hashes(),'cases':{},'physical_mapping':'UNMEASURED',
            'scope':'latency/II/ownership and logical memory geometry; no routed timing or mapped BRAM result'}
    try:
        gsim,cxx=common.setup(False)
        for name,words,lines,prefetch,compact,base,size in CASES:
            pair={}
            for packed in (False,True):
                layout='packed' if packed else 'parallel-ways';harness='instruction_line_prefetch.cpp' if prefetch else 'instruction_line_cache.cpp'
                parameters=('prefetch' if prefetch else 'off',words,f'lines={lines}','--banked-cache-tags',
                    *(('compact-tags',) if compact else ()),*(('--banked-instruction-data',) if packed else ()),
                    f'--ram-base={base}',*((f'--ram-bytes={size}',) if size else ()))
                definitions={'PACKET_WORDS':words,'CACHE_LINES':lines,'CACHE_BASE':str(base)+'ULL'}
                if compact:definitions['COMPACT_TAG_TEST']=1
                if not prefetch and size and base < (1<<32) < base+size:definitions['CROSS4G_TEST']=1
                d=out/f'{name}-{layout}'; d.mkdir()
                common.run(['mill','-i','IonSoC.test.runMain','ooo.InstructionLineCacheGsimMain',d,*parameters],
                    log=d/'elaborate.log')
                common.run([gsim,'--threads=1','--dir='+str(d),d/'InstructionLineCacheGsim.fir'],log=d/'generate.log')
                flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(d)]
                objects=[]
                for cpp in sorted(d.glob('InstructionLineCacheGsim[0-9]*.cpp')):
                    obj=cpp.with_suffix('.o'); objects.append(obj)
                    common.run([cxx,*flags,'-c',cpp,'-o',obj],log=cpp.with_suffix('.compile.log'))
                common.run([cxx,*flags,*[f'-D{k}={v}' for k,v in definitions.items()],*objects,
                    common.HERE/'harness'/harness,'-ldl','-o',d/'run'],log=d/'compile.log')
                initial_binary=hashlib.sha256((d/'run').read_bytes()).hexdigest()
                common.run([d/'run'],log=d/'test.log',timeout=180,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
                body=module((d/'InstructionLineCacheGsim.fir').read_text(),'InstructionLineCache')
                if packed:
                    banks=re.findall(r'smem (dataBanks_\d+) : UInt<(\d+)>\[(\d+)\]',body)
                    assert len(banks)==8 and all(int(bits)==64 and int(depth)==lines for _,bits,depth in banks)
                    assert not re.search(r'smem data_\d+ :',body)
                    assert re.search(r'node hitPacket_readIndex = cat\((?:hitWay|hits\[1\]), requestSet\)', body), \
                        'way must be selected before banked SRAM read edge'
                else:
                    banks=re.findall(r'smem (data_\d+) : UInt<(\d+)>\[(\d+)\]',body)
                    assert len(banks)==2 and all(int(bits)==512 and int(depth)==lines//2 for _,bits,depth in banks)
                assert sum(int(bits)*int(depth) for _,bits,depth in banks)==lines*512
                negative=subprocess.run([d/'run','--inject-mismatch'],capture_output=True,text=True,timeout=180,
                    env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
                (d/'negative.log').write_text(negative.stdout+negative.stderr)
                anchor='prefetched instruction line returned wrong code' if prefetch else 'instruction cache returned incorrect code'
                assert negative.returncode!=0 and anchor in negative.stdout+negative.stderr
                seeded_logs = {}
                if not prefetch:
                    for seed in (7,31,127):
                        log=d/f'seed-{seed}.log'
                        common.run([d/'run','--seed',str(seed)],log=log,timeout=180,
                            env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
                        seeded_logs[str(seed)]=log.read_text()
                    mutation=subprocess.run([d/'run','--corrupt-last-bank'],capture_output=True,text=True,timeout=180,
                        env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
                    (d/'last-bank-negative.log').write_text(mutation.stdout+mutation.stderr)
                    assert mutation.returncode!=0 and 'resident bank sweep returned stale or reordered bytes' in mutation.stderr
                held_log = None
                if prefetch:
                    exe=d/'held-hit-run'
                    common.run([cxx,*flags,*[f'-D{k}={v}' for k,v in {**definitions,'PREFETCH_ENABLED':1}.items()],
                        *objects,common.HERE/'harness/instruction_hit_stability.cpp','-ldl','-o',exe],log=d/'held-hit-compile.log')
                    held_sha=hashlib.sha256(exe.read_bytes()).hexdigest()
                    common.run([exe],log=d/'held-hit.log',timeout=180,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
                    held_log=(d/'held-hit.log').read_text()
                    mutation=subprocess.run([exe,'--bypass-hit-snapshot'],capture_output=True,text=True,timeout=180,
                        env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
                    (d/'held-hit-negative.log').write_text(mutation.stdout+mutation.stderr)
                    assert mutation.returncode!=0 and 'held-hit immutable byte oracle mismatch' in mutation.stderr
                    assert hashlib.sha256(exe.read_bytes()).hexdigest()==held_sha
                assert hashlib.sha256((d/'run').read_bytes()).hexdigest()==initial_binary
                native = None
                if name == 'selected-two':
                    candidates=sorted((Path(os.environ.get('XDG_CACHE_HOME',str(Path.home()/'.cache')))/'llvm-firtool').glob('*/bin/firtool'))
                    firtool=os.environ.get('FIRTOOL') or shutil.which('firtool') or (str(candidates[-1]) if candidates else None)
                    assert firtool, 'cached firtool is required for selected native memory census'
                    rtl=d/'native';rtl.mkdir()
                    command=[firtool,str(d/'InstructionLineCacheGsim.fir'),'--split-verilog',
                        '--disable-all-randomization','--strip-debug-info','--default-layer-specialization=disable',
                        '-o',str(rtl)]
                    common.run(command,log=d/'native-export.log',timeout=180)
                    helper_name='dataBanks_512x64' if packed else 'data_256x512'
                    helper=rtl/(helper_name+'.sv'); helper_text=helper.read_text()
                    width,depth=(64,512) if packed else (512,256)
                    assert re.search(r'reg\s+\['+str(width-1)+r':0\]\s+Memory\[0:'+str(depth-1)+r'\]',helper_text)
                    assert 'always @(posedge R0_clk)' in helper_text and 'always @(posedge W0_clk)' in helper_text
                    assert 'R1_' not in helper_text and 'W1_' not in helper_text
                    cache_native=(rtl/'InstructionLineCache.sv').read_text()
                    count=len(re.findall(r'(?m)^\s*'+helper_name+r'\s+',cache_native))
                    assert count==(8 if packed else 2), (layout,count)
                    native={'helper':helper_name,'instances':count,'width_bits':width,'depth':depth,
                        'read_ports':1,'write_ports':1,'read_latency':1,
                        'timing_tradeoff':'way-tag hit feeds read address MSB' if packed else 'set-only read address; way selects read enable and output',
                        'command':command,'firtool_sha256':hashlib.sha256(Path(firtool).read_bytes()).hexdigest(),
                        'sv_sha256':{str(p.relative_to(d)):hashlib.sha256(p.read_bytes()).hexdigest() for p in rtl.rglob('*') if p.is_file()}}
                pair[layout]={'log':(d/'test.log').read_text(),'seeded_logs':seeded_logs,'held_hit_log':held_log,'native_geometry':native,'logical_data_banks':[
                    {'name':bank,'width_bits':int(bits),'depth':int(depth)} for bank,bits,depth in banks],
                    'negative':'PASS','model_directory':str(d.relative_to(common.ROOT)),
                    'artifacts_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in d.iterdir()
                        if p.is_file()}}
                report['cases'][name]=pair;(out/'progress.json').write_text(json.dumps(report,indent=2)+'\n')
            assert pair['parallel-ways']['log']==pair['packed']['log'],(name,'cycle/traffic outcomes differ')
            assert pair['parallel-ways']['seeded_logs']==pair['packed']['seeded_logs'],(name,'seeded hit behavior differs')
            assert pair['parallel-ways']['held_hit_log']==pair['packed']['held_hit_log'],(name,'prefetch held-hit behavior differs')
        assert hashes()==report['source_sha256'],'source drift';report['status']='PASS'
    except BaseException as error:report['status']='FAIL';report['error']=str(error);raise
    finally:(out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
