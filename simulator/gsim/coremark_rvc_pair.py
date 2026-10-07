#!/usr/bin/env python3
"""Matched RV64IMC/lp64 CoreMark A/B using two already-built board model objects."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import struct
import run as common
import throughput_perf as perf
from frontend_perf import board_rows
from analyze_frontend_perf import rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline', type=Path, required=True)
    ap.add_argument('--candidate', type=Path, required=True)
    ap.add_argument('--firmware', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    out = a.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    firmware = a.firmware.resolve(); image = firmware/'coremark_board.bin'; elf = firmware/'coremark_board.elf'
    dis = subprocess.check_output(['riscv64-unknown-elf-objdump','-d',elf],text=True)
    def rdtime(name):
        block=dis.split('<'+name+'>:',1)[1].split('\n\n',1)[0]
        return int(re.search(r'^\s*([0-9a-f]+):.*\brdtime\b',block,re.M)[1],16)
    start, stop = rdtime('start_time'), rdtime('stop_time')
    attributes = subprocess.check_output(['riscv64-unknown-elf-readelf','-h',elf],text=True)
    assert 'RVC, soft-float ABI' in attributes
    ops=re.findall(r'^\s*[0-9a-f]+:\s+([0-9a-f]+)\s+([^\s]+)',dis,re.M)
    assert any(len(bits)==4 for bits,op in ops)
    assert not any(op.startswith('f') and not op.startswith('fence') for bits,op in ops)
    report={'status':'RUNNING','scope':'Separate matched RV64IMC binary; never compare these cycles as original RV64IM results',
            'firmware_bin_sha256':perf.sha256(image),'firmware_elf_sha256':perf.sha256(elf),
            'roi':{'start':hex(start),'stop':hex(stop)},'abi':'lp64 soft-float',
            'static_instructions':len(ops),'static_compressed_instructions':sum(len(bits)==4 for bits,op in ops),
            'hardware_models_rebuilt':False,'runs':{}}
    tracked = [Path(__file__),common.HERE/'harness/frontend_observer.h',common.HERE/'harness/performance_observer.h',
               common.HERE/'harness/board_boot.cpp',common.ROOT/'fpga/firmware/build_coremark.py',
               common.ROOT/'fpga/firmware/coremark_port/core_portme.h',image,elf]
    inputs={str(p):perf.sha256(p) for p in tracked}
    cxx, version = common.compiler(); report['cxx_version']=version
    try:
        for label,directory,profile,lines in [('baseline8',a.baseline,'staged-fetch-feedback',8),('combined32',a.candidate,'staged-fetch-turnover',32)]:
            directory=directory.resolve(); source_receipt=json.loads((directory/'receipt.json').read_text())
            assert source_receipt['status']=='PASS_SHORT_PERFORMANCE_AND_FUNCTIONAL'
            assert source_receipt['profile']==profile and source_receipt['instruction_line_cache']['lines']==lines
            assert source_receipt['issue_width']==2 and source_receipt['isa']=='rv64gc'
            assert source_receipt['board_clock_hz']==100000000 and source_receipt['uart_baud']==460800
            assert source_receipt['ddr_bytes']==2147483648 and not source_receipt['effective_instruction_line_prefetch']
            model=directory/'board-model'; objects=sorted(model.glob('*.o')); assert objects
            for obj in objects:
                assert source_receipt['executable_sha256'][str(obj.relative_to(common.ROOT))]==perf.sha256(obj)
            driver_text=(directory/'board_coremark.cpp').read_text()
            driver_text,n=re.subn(r'perf.startPc=\d+ULL; perf.endPc=\d+ULL;',f'perf.startPc={start}ULL; perf.endPc={stop}ULL;',driver_text)
            assert n==1
            driver=out/(label+'.cpp'); driver.write_text(driver_text)
            binary=out/label; trace=out/(label+'.retired-pcs.bin'); log=out/(label+'.log')
            flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                   '-I'+str(model),'-I'+str(common.HERE/'harness'),'-DUART_DIVISOR=1','-DBOARD_CPU_HZ=100000000',
                   '-DBOARD_UART_BAUD=460800','-DUART_EXTRA_STOP_BITS=0','-DDDR_MODEL=1','-DBOARD_DDR_BYTES=2147483648ULL',
                   '-DAPP_TIMEBASE_HZ=50000000']
            common.run([cxx,*flags,*objects,driver,'-ldl','-o',binary],log=out/(label+'-compile.log'))
            common.run([binary,image],env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0','FRONTEND_RETIRE_TRACE':str(trace)},log=log,timeout=600)
            text=log.read_text(); counters=board_rows(text,True)
            assert len(counters)==2 and trace.stat().st_size>0 and trace.stat().st_size%8==0
            for name,counter in zip(('whole_run','coremark_roi'),counters):
                zero=[r for r in rows(text,'BACKEND_ZERO_COMMIT') if r['name']==name]
                assert sum(r['cycles'] for r in zero)==counter['zero_commit']
                state=[r for r in rows(text,'ICACHE_STATE') if r['name']==name]
                assert sum(r['cycles'] for r in state)==counter['cycles']
                wait=next(r for r in rows(text,'FRONTEND_EVENT') if r['name']==name and r['event']=='physical_wait_no_reply')
                assert sum(r['physical_wait_no_reply'] for r in state)==wait['cycles']
            report['runs'][label]={'ticks':int(re.search(r'Total ticks\s*:\s*(\d+)',text)[1]),'counters':counters,
                'crc_lines':[l for l in text.splitlines() if 'crc' in l.lower()],
                'retired_pc_stream_sha256':perf.sha256(trace),'retired_pc_stream_count':trace.stat().st_size//8,
                'source_receipt_sha256':perf.sha256(directory/'receipt.json'),
                'model_object_sha256':{str(p):perf.sha256(p) for p in objects},'executable_sha256':perf.sha256(binary),
                'probe_counters':{prefix:rows(text,prefix) for prefix in ('FRONTEND_HIST','FRONTEND_EVENT','ICACHE_EVENT','ICACHE_STATE','ICACHE_LATENCY','BACKEND_ZERO_COMMIT','BACKEND_EXECUTING','BACKEND_REQUEST')}}
        b,c=report['runs']['baseline8'],report['runs']['combined32']
        assert b['crc_lines']==c['crc_lines']
        assert (out/'baseline8.retired-pcs.bin').read_bytes()==(out/'combined32.retired-pcs.bin').read_bytes(), 'ordered retired PC stream differs'
        assert b['counters'][1]['retired']==c['counters'][1]['retired']
        instruction_widths={int(pc,16):len(bits)//2 for pc,bits in re.findall(r'^\s*([0-9a-f]+):\s+([0-9a-f]+)\s+',dis,re.M)}
        retired_pcs=[pc for pc, in struct.iter_unpack('<Q',(out/'baseline8.retired-pcs.bin').read_bytes())]
        assert all(pc in instruction_widths for pc in retired_pcs), 'retired PC absent from independent objdump'
        report['dynamic_compressed_retired']=sum(instruction_widths[pc]==2 for pc in retired_pcs)
        report['dynamic_retired_pc_count']=len(retired_pcs)
        report['guest_cycle_reduction_percent']=100*(b['ticks']-c['ticks'])/b['ticks']
        report['status']='PASS_MATCHED_RV64IMC_PAIR'
    except Exception as e:
        report['status']='FAIL_MATCHED_RV64IMC_PAIR';report['failure']=str(e);raise
    finally:
        report['input_sha256']=inputs
        if inputs!={str(p):perf.sha256(p) for p in tracked}:report['status']='FAIL_INPUT_DRIFT'
        report['artifact_sha256']={str(p.relative_to(out)):perf.sha256(p) for p in out.iterdir() if p.is_file() and p.name!='receipt.json'}
        (out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['status']!='PASS_MATCHED_RV64IMC_PAIR':raise RuntimeError(report['status'])
    print(json.dumps({'status':report['status'],'guest_cycle_reduction_percent':report['guest_cycle_reduction_percent']},indent=2))

if __name__=='__main__':main()
