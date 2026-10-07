#!/usr/bin/env python3
"""Bounded, matched 2/4 KiB coherent D-cache capacity experiment. Defaults unchanged."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import shutil
import run as common
import throughput_perf as perf
from frontend_perf import board_rows, verify_instruction_geometry
from data_cache_geometry import verify, module
from memory_capacity_geometry import verify_memory_geometry
from analyze_frontend_perf import rows
from control_stage import negative

ENV={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'}
RVC_HASH='05b9a01d74a03389433ef942fef7056827331be18a91e0795f6456cee51fdac5'
PC_HASH='142a5aafefa1eabaa2b76f5d7c42baa1cb31de1c6fd95384652ea4e936aa84fa'
BASE=common.BUILD/'frontend-perf-combined32-20261007'

def hashes(paths): return {str(p):perf.sha256(p) for p in paths if p.is_file()}
def inputs():
    return hashes([*sorted((common.ROOT/'src/main/scala').rglob('*.scala')),
       common.ROOT/'src/test/scala/ooo/BoardSocGsimMain.scala',
       common.ROOT/'src/test/scala/ooo/CoherentCacheWaysGsim.scala',
       common.ROOT/'src/test/scala/ip/EthernetPacketDmaGsim.scala',
       common.HERE/'harness/coherent_cache_ways.cpp',common.HERE/'harness/data_cache_observer.h',
       common.HERE/'harness/data_cache_locality.cpp',common.HERE/'harness/ethernet_packet_dma.cpp',
       common.ROOT/'fpga/firmware/ddr_bench.c',common.ROOT/'fpga/firmware/build_ddr_bench.py',Path(__file__),common.HERE/'data_cache_geometry.py'])

def rejected(binary,args,expected,log):
    r=subprocess.run([str(binary),*map(str,args)],capture_output=True,text=True,env=ENV,timeout=120)
    log.write_text(r.stdout+r.stderr)
    assert r.returncode!=0 and expected in r.stdout+r.stderr, 'corruption negative not rejected'

def short_checks(out,gsim,cxx,report,reuse=None):
    if reuse:
        old=json.loads((reuse/'receipt.json').read_text())
        assert old['status']=='PASS_DCACHE_SHORT_CHECKS'
        for p,v in old['source_sha256'].items():
            if p.endswith('.scala'):assert perf.sha256(Path(p))==v, 'changed hardware/fixture source'
        assert all(perf.sha256(Path(p))==v for row in old['checks'].values() for p,v in row['artifacts'].items())
    def test(name,main,top,harness,parameters,defines):
        if not reuse:return common.test(gsim,cxx,str(out.relative_to(common.BUILD)/name),main,top,harness,parameters=parameters,defines=defines)
        directory=out/name;directory.mkdir()
        for p in (reuse/name).iterdir():
            if p.suffix in ('.fir','.cpp','.h'):shutil.copy2(p,directory/p.name)
        common.run([cxx,*flags(directory),*[f'-D{k}={v}' for k,v in defines.items()],
          *sorted(directory.glob(top+'[0-9]*.cpp')),common.HERE/'harness'/harness,'-ldl','-o',directory/'run'],log=directory/'compile.log')
        common.run([directory/'run'],env=ENV,log=directory/'test.log')
        return directory
    report['checks']={}
    for lines in (32,64):
        cache=test(f'cache-{lines}',
            'ooo.CoherentCacheWaysGsimMain','CoherentCacheWaysGsim','coherent_cache_ways.cpp',
            parameters=(2,lines),defines={'CACHE_WAYS':2,'CACHE_LINES':lines})
        geom=verify((cache/'CoherentCacheWaysGsim.fir').read_text(),lines,home=False)
        rejected(cache/'run',('--inject-corruption',),'CPU data mismatch',cache/'negative.log')
        dma=test(f'dma-{lines}',
            'ip.EthernetDmaCoherenceGsimMain','EthernetDmaCoherenceGsim','ethernet_packet_dma.cpp',
            parameters=(lines,),defines={'COHERENT_DMA':1,'DCACHE_CAPACITY':lines})
        verify((dma/'EthernetDmaCoherenceGsim.fir').read_text(),lines)
        rejected(dma/'run',('--inject-mismatch',),'TX independent byte oracle mismatch',dma/'negative.log')
        report['checks'][str(lines)]={'geometry':geom,'cache_log':(cache/'test.log').read_text(),
            'dma_log':(dma/'test.log').read_text(),'artifacts':hashes(p for d in (cache,dma) for p in d.iterdir() if p.is_file())}

def flags(model):
    return ['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
            '-I'+str(model),'-I'+str(common.HERE/'harness')]

def rdtime(elf,name):
    dis=subprocess.check_output(['riscv64-unknown-elf-objdump','-d',elf],text=True)
    block=dis.split('<'+name+'>:',1)[1].split('\n\n',1)[0]
    return int(re.search(r'^\s*([0-9a-f]+):.*\brdtime\b',block,re.M)[1],16)

def board(out,gsim,cxx,report,checks):
    check=json.loads(checks.read_text());assert check['status']=='PASS_DCACHE_SHORT_CHECKS'
    for p,v in check['source_sha256'].items():
        if p.endswith('.scala') or p.endswith(('coherent_cache_ways.cpp','ethernet_packet_dma.cpp')):
            assert perf.sha256(Path(p))==v, 'short-check hardware/fixture source drift'
    assert all(perf.sha256(Path(p))==v for row in check['checks'].values() for p,v in row['artifacts'].items())
    report['short_checks_receipt']={'path':str(checks),'sha256':perf.sha256(checks)}
    baseline=json.loads((BASE/'receipt.json').read_text())
    assert baseline['status']=='PASS_SHORT_PERFORMANCE_AND_FUNCTIONAL'
    assert baseline['profile']=='staged-fetch-turnover' and baseline['instruction_line_cache']['lines']==32
    assert baseline['issue_width']==2 and baseline['data_cache_ways']==2 and baseline['isa']=='rv64gc'
    assert baseline['ddr_bytes']==2147483648 and baseline['board_clock_hz']==100000000 and baseline['uart_baud']==460800
    base_model=BASE/'board-model';base_objects=sorted(base_model.glob('*.o'));assert base_objects
    assert all(baseline['executable_sha256'][str(p.relative_to(common.ROOT))]==perf.sha256(p) for p in base_objects)
    base_fir=(base_model/'BoardSocGsim.fir').read_text()
    report['baseline_geometry']=verify(base_fir,32,probes=True)
    verify_memory_geometry(base_fir,2);verify_instruction_geometry(base_fir,32)
    model=out/'board-model';model.mkdir()
    common.run(['mill','-i','IonSoC.test.runMain','ooo.BoardSocGsimMain',model,'ddr','100000000',
                'staged-fetch-turnover','460800','2','2','1','rv64gc','2147483648','1','32','0','64'],log=model/'elaborate.log')
    fir=(model/'BoardSocGsim.fir').read_text()
    report['candidate_geometry']=verify(fir,64,probes=True)
    report['memory_geometry']=verify_memory_geometry(fir,2)
    report['instruction_geometry']=verify_instruction_geometry(fir,32)
    assert '0h100200000' in fir
    # All existing top-level probes match. CoherentLineCache is unchanged except
    # geometry; generated scalar definitions are checked above on both models.
    common.run([gsim,'--threads=1','--dir='+str(model),model/'BoardSocGsim.fir'],log=model/'generate.log')
    objects=[]
    for source in sorted(model.glob('BoardSocGsim[0-9]*.cpp')):
        obj=source.with_suffix('.o');common.run([cxx,*flags(model),'-c',source,'-o',obj],log=source.with_suffix('.compile.log'));objects.append(obj)
    exact=common.BUILD/'coremark-rvc-20261007/rv64imc'
    image=exact/'coremark_board.bin';assert perf.sha256(image)==RVC_HASH
    start,stop=rdtime(exact/'coremark_board.elf','start_time'),rdtime(exact/'coremark_board.elf','stop_time')
    locality=common.BUILD/'dcache-locality-firmware-20261007'
    lstart,lstop=rdtime(locality/'ddr_bench.elf','locality_start'),rdtime(locality/'ddr_bench.elf','locality_stop')
    firmware=BASE/'firmware'
    report['firmware_sha256']=hashes([image,exact/'coremark_board.elf',locality/'ddr_bench.bin',locality/'ddr_bench.elf',firmware/'ddr_bench.bin',firmware/'rv64gc_smoke.bin'])
    report['runs']={}
    for label,m,objs in [('dcache2k',base_model,base_objects),('dcache4k',model,objects)]:
        report['runs'][label]={'model_object_sha256':hashes(objs),'workloads':{}}
        for stem,binfile in [('board_coremark',image),('ddr_bench_app',firmware/'ddr_bench.bin'),
                             ('rv64gc_board',firmware/'rv64gc_smoke.bin'),('data_cache_locality',locality/'ddr_bench.bin')]:
            text=(common.HERE/'harness'/(stem+'.cpp')).read_text()
            if stem!='data_cache_locality':
                assert text.count('#undef main')==text.count('Test test(rom);')==text.count('        return 0;')==1
                text=text.replace('#undef main','#undef main\n#include "data_cache_observer.h"')
                text=text.replace('Test test(rom);','Test test(rom);\n DataCacheObserver perf; perf.startPc='+str(start if stem=='board_coremark' else 0)+'ULL; perf.endPc='+str(stop if stem=='board_coremark' else 0)+'ULL;')
                anchor='        bool passed = false;' if stem=='rv64gc_board' else '        for (size_t offset'
                pos=text.index(anchor)
                chain='''        struct Observers { DataCacheObserver *perf; void (*old)(SBoardSocGsim &,void *); void *context; } observers{&perf,test.observer,test.observerContext};
        test.observer=[](SBoardSocGsim &d,void *p){auto &o=*static_cast<Observers*>(p);DataCacheObserver::sample(d,o.perf);if(o.old)o.old(d,o.context);}; test.observerContext=&observers;
'''
                text=text[:pos]+chain+text[pos:]
                text=text.replace('        return 0;','        perf.report();\n        return 0;')
            driver=out/(label+'-'+stem+'.cpp');driver.write_text(text);binary=driver.with_suffix('');log=binary.with_suffix('.log')
            common.run([cxx,*flags(m),'-DUART_DIVISOR=1','-DBOARD_CPU_HZ=100000000','-DBOARD_UART_BAUD=460800',
                '-DUART_EXTRA_STOP_BITS=0','-DDDR_MODEL=1','-DBOARD_DDR_BYTES=2147483648ULL','-DAPP_TIMEBASE_HZ=50000000',
                '-DLOCALITY_START_PC='+str(lstart)+'ULL','-DLOCALITY_STOP_PC='+str(lstop)+'ULL',*objs,driver,'-ldl','-o',binary],log=binary.with_suffix('.compile.log'))
            trace=binary.with_suffix('.retired-pcs.bin')
            env={**ENV,'FRONTEND_RETIRE_TRACE':str(trace)} if stem=='board_coremark' else ENV
            common.run([binary,binfile],env=env,log=log,timeout=900)
            output=log.read_text();record={'dcache':rows(output,'DCACHE'),'ipc':board_rows(output,stem=='board_coremark'),
               'log_sha256':perf.sha256(log),'executable_sha256':perf.sha256(binary)}
            if stem=='board_coremark':
                record['ticks']=int(re.search(r'Total ticks\s*:\s*(\d+)',output)[1]);record['retired_pc_sha256']=perf.sha256(trace)
                assert record['retired_pc_sha256']==PC_HASH and trace.stat().st_size//8==360528
                assert record['ipc'][1]['retired']==360528
                record['crc_lines']=[l for l in output.splitlines() if 'crc' in l.lower()]
                if label=='dcache2k':assert record['ticks']==486605
            if stem=='rv64gc_board':
                negative(binary,(binfile,),'firmware independent anchor/context failure',binary.with_suffix('.negative.log'))
            if stem=='data_cache_locality':
                negative(binary,(binfile,),'stream store/copy did not reach AXI backing memory',binary.with_suffix('.negative.log'))
                record['phases']=[{'bytes':int(b),'phase':p,'ticks':int(t)} for b,p,t in re.findall(r'LOCALITY size=(\d+) phase=(\w+) ticks=(\d+) PASS',output)]
                assert len(record['phases'])==len(record['dcache'])==32
                record['ipc']=rows(output,'BOARD_IPC')
                assert len(record['ipc'])==32
            report['runs'][label]['workloads'][stem]=record
            (out/'progress.json').write_text(json.dumps(report,indent=2)+'\n')
            print(label,stem,'PASS',flush=True)
    b=report['runs']['dcache2k']['workloads'];c=report['runs']['dcache4k']['workloads']
    assert b['board_coremark']['crc_lines']==c['board_coremark']['crc_lines']
    report['coremark_tick_reduction_percent']=100*(b['board_coremark']['ticks']-c['board_coremark']['ticks'])/b['board_coremark']['ticks']
    for x,y in zip(b['data_cache_locality']['phases'],c['data_cache_locality']['phases']):assert (x['bytes'],x['phase'])==(y['bytes'],y['phase'])
    report['locality_comparison']=[{**x,'candidate_ticks':y['ticks'],'tick_reduction_percent':100*(x['ticks']-y['ticks'])/x['ticks']} for x,y in zip(b['data_cache_locality']['phases'],c['data_cache_locality']['phases'])]

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--tag',required=True);ap.add_argument('--phase',choices=('checks','board'),required=True);ap.add_argument('--checks',type=Path)
    ap.add_argument('--reuse-check-models',type=Path)
    a=ap.parse_args();assert re.fullmatch(r'[A-Za-z0-9_-]+',a.tag)
    out=common.BUILD/('data-cache-'+a.phase+'-'+a.tag);out.mkdir(parents=True,exist_ok=False)
    report={'status':'RUNNING','source_sha256':inputs(),'profile':'staged-fetch-turnover','fixed':{'memory_entries':2,'issue':2,'rob':16,'prf':48,'predictor':32,'store_buffer':2,'icache_lines':32,'dcache_ways':2,'cpu_hz':100000000,'uart_baud':460800,'ddr_bytes':2147483648,'isa':'rv64gc','load_bypass':False},
      'coupling':'Coherent home owner-directory entries and sets grow with L1 capacity; engine/queue credits and cacheable range fixed',
      'semantics':'Miss classes partition accepted misses. Hits and misses count accepted cacheable ordinary requests. Dirty evictions exclude flush/probe; writeback C beats/lines include flush, probe_data_beats separate. Blocked and state events overlap retirement/other stalls; not an additive CPI stack. Locality warm means a preceding complete sweep; footprints larger than cache cannot stay resident. Copy footprint is two buffers. ROI includes both rdtime retirement cycles; guest ticks may differ.',
      'limitations':['Synthetic AXI timing; no measured FPGA speed/resource/Fmax or DDR PHY claim','Short real coherent DMA fixture, no asynchronous GMAC/CDC/physical network claim','CoreMark one iteration, not an official score','Default and signoff gates unchanged']}
    try:
        gsim,cxx=common.setup(False)
        if a.phase=='checks':short_checks(out,gsim,cxx,report,a.reuse_check_models)
        else:
            assert a.checks;board(out,gsim,cxx,report,a.checks.resolve())
        report['status']='PASS_DCACHE_SHORT_CHECKS' if a.phase=='checks' else 'PASS_MATCHED_DCACHE_CAPACITY'
    except Exception as e:report['status']='FAIL';report['failure']=str(e);raise
    finally:
        if report['source_sha256']!=inputs():report['status']='FAIL_SOURCE_DRIFT'
        report['artifacts']=hashes(p for p in out.rglob('*') if p.is_file() and p.name!='receipt.json')
        (out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    assert report['status'].startswith('PASS');print(out/'receipt.json',flush=True)
if __name__=='__main__':main()
