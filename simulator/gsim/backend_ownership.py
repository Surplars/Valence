#!/usr/bin/env python3
"""One passive owner-qualified backend model/run, gated on exact selected RV64IMC equivalence."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import run as common
import throughput_perf as perf
from frontend_perf import verify_instruction_geometry, board_rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--reference', type=Path, default=common.BUILD/'frontend-rvc-pair-20261007')
    ap.add_argument('--firmware', type=Path, default=common.BUILD/'coremark-rvc-20261007/rv64imc')
    ap.add_argument('--resume-generation', action='store_true', help='Reuse exact emitted FIR after a generator failure')
    a = ap.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=a.resume_generation)
    reference=a.reference.resolve();firmware=a.firmware.resolve()
    previous=json.loads((reference/'receipt.json').read_text());selected=previous['runs']['combined32']
    assert previous['status']=='PASS_MATCHED_RV64IMC_PAIR'
    image=firmware/'coremark_board.bin'
    assert perf.sha256(image)==previous['firmware_bin_sha256']
    start,stop=(int(previous['roi'][key],16) for key in ('start','stop'))
    inputs=[Path(__file__),common.HERE/'harness/backend_ownership_ledger.h',common.HERE/'harness/backend_observer.h',
            common.HERE/'harness/backend_ownership_test.cpp',common.HERE/'harness/board_boot.cpp',
            common.HERE/'harness/frontend_observer.h',common.HERE/'harness/performance_observer.h',
            common.ROOT/'src/test/scala/ooo/BoardSocGsimMain.scala',image,reference/'receipt.json',reference/'combined32.log']
    before={str(p):perf.sha256(p) for p in inputs};hardware=perf.hardware_sources()
    if a.resume_generation:
        saved=json.loads((out/'receipt.json').read_text())
        assert saved['hardware_source_sha256']==hardware
        wrapper=str(common.ROOT/'src/test/scala/ooo/BoardSocGsimMain.scala')
        assert saved['measurement_input_sha256'][wrapper]==before[wrapper]
        (out/'initial-failure-receipt.json').write_text(json.dumps(saved,indent=2)+'\n')
    report={'status':'RUNNING','scope':'Observation only; FIFO ownership, StoreBuffer acceptance, LSU return; downstream stages unknown',
            'configuration':{'profile':'staged-fetch-turnover','instruction_cache_lines':32,'instruction_cache_bytes':2048,
                'issue_width':2,'isa':'rv64gc','fpu':True,'clock_hz':100000000,'uart_baud':460800,
                'ddr_bytes':2147483648,'data_cache_ways':2,'load_issue_forwarding':False},
            'firmware_bin_sha256':perf.sha256(image),'roi':previous['roi'],'hardware_source_sha256':hardware,
            'measurement_input_sha256':before,'reference_receipt_sha256':perf.sha256(reference/'receipt.json'),
            'limitations':['No functional optimization; no CAD, physical board, full regression or Linux.',
                'Retired buffered writes and fast-store physical draining are not tracked beyond local acceptance.',
                'Downstream unknown is not proven translation/cache wait.',
                'Nonmemory queued eligibility is exact; finer operand/issue/system causes remain unknown.',
                'Single fixed short CoreMark iteration is not an official CoreMark score.']}
    (out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    try:
        gsim,cxx=common.setup(False);report['toolchain_lock']=common.LOCK
        report['compiler_version']=subprocess.check_output([cxx,'--version'],text=True).splitlines()[0]
        flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all']
        env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'}
        unit=out/'ownership_test'
        common.run([cxx,*flags,common.HERE/'harness/backend_ownership_test.cpp','-o',unit],log=out/'unit-compile.log')
        common.run([unit],env=env,log=out/'unit.log')
        report['independent_unit_tests']=(out/'unit.log').read_text().strip()
        model=out/'board-model';model.mkdir(exist_ok=a.resume_generation)
        if not a.resume_generation:
            common.run(['mill','-i','IonSoC.test.runMain','ooo.BoardSocGsimMain',model,'ddr','100000000',
                    'staged-fetch-turnover','460800','2','2','1','rv64gc','2147483648','1','32','1'],log=model/'elaborate.log')
        fir=(model/'BoardSocGsim.fir').read_text()
        report['instruction_cache_geometry']=verify_instruction_geometry(fir,32)
        assert '0h100200000' in fir
        report['generator_options']=['--threads=1']
        common.run([gsim,'--threads=1','--dir='+str(model),model/'BoardSocGsim.fir'],log=model/'generate.log')
        flags+=['-I'+str(model),'-I'+str(common.HERE/'harness')]
        objects=[]
        for source in sorted(model.glob('BoardSocGsim[0-9]*.cpp')):
            obj=source.with_suffix('.o');common.run([cxx,*flags,'-c',source,'-o',obj],log=source.with_suffix('.compile.log'));objects.append(obj)
        text=(reference/'combined32.cpp').read_text()
        assert text.count('Test test(rom);')==1 and text.count('perf.report();')==1
        text=text.replace('#include "frontend_observer.h"','#include "frontend_observer.h"\n#include "backend_observer.h"')
        text=text.replace('Test test(rom);',f'BackendObserver backend; backend.startPc={start}ULL; backend.endPc={stop}ULL;\n        Test test(rom,BackendObserver::sample,&backend);')
        text=text.replace('perf.report();','perf.report();\n        backend.report();')
        driver=out/'board_coremark.cpp';driver.write_text(text);binary=out/'board_coremark'
        defines=['-DUART_DIVISOR=1','-DBOARD_CPU_HZ=100000000','-DBOARD_UART_BAUD=460800','-DUART_EXTRA_STOP_BITS=0',
                 '-DDDR_MODEL=1','-DBOARD_DDR_BYTES=2147483648ULL','-DAPP_TIMEBASE_HZ=50000000']
        common.run([cxx,*flags,*defines,*objects,driver,'-ldl','-o',binary],log=out/'driver-compile.log')
        trace=out/'retired-pcs.bin';log=out/'board_coremark.log'
        common.run([binary,image],env={**env,'FRONTEND_RETIRE_TRACE':str(trace)},log=log,timeout=600)
        current=log.read_text();old=(reference/'combined32.log').read_text()
        legacy='\n'.join(line for line in current.splitlines() if not line.startswith('BACKEND_OWNER_'))+'\n'
        assert legacy==old, 'Original guest output or existing counter output differs'
        assert trace.read_bytes()==(reference/'combined32.retired-pcs.bin').read_bytes(), 'Ordered retired PCs differ'
        assert perf.sha256(trace)==selected['retired_pc_stream_sha256']
        assert trace.stat().st_size//8==selected['retired_pc_stream_count']==360528
        counts=board_rows(current,True);assert counts==selected['counters']
        def rows(prefix):
            return [dict(x.split('=',1) for x in line.split()[1:]) for line in current.splitlines() if line.startswith(prefix+' ')]
        buckets=rows('BACKEND_OWNER_BUCKET');totals=rows('BACKEND_OWNER_TOTAL')[0]
        assert sum(int(r['cycles']) for r in buckets)==int(totals['cycles'])==counts[1]['cycles']
        assert sum(int(r['cycles']) for r in buckets if not r['category'].startswith('progress_'))==int(totals['zero_commit'])==counts[1]['zero_commit']
        assert int(totals['retired'])==counts[1]['retired']
        report.update(status='PASS_OWNER_ATTRIBUTION_AND_EXACT_EQUIVALENCE',existing_counters=counts,
            equivalence={'guest_and_all_prior_output':'BYTE_IDENTICAL','retired_pc_stream_sha256':perf.sha256(trace),
                'retired_instructions':trace.stat().st_size//8,'guest_ticks':selected['ticks']},
            buckets=buckets,totals=totals,ledger=rows('BACKEND_OWNER_LEDGER')[0])
    except Exception as error:
        report['status']='FAIL_OWNER_ATTRIBUTION';report['failure']=str(error);raise
    finally:
        after={str(p):perf.sha256(p) for p in inputs}
        report['source_unchanged_during_measurement']=before==after and hardware==perf.hardware_sources()
        if not report['source_unchanged_during_measurement']:report['status']='FAIL_INPUT_DRIFT'
        report['artifact_sha256']={str(p.relative_to(out)):perf.sha256(p) for p in out.rglob('*') if p.is_file() and p.name!='receipt.json'}
        (out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['status']!='PASS_OWNER_ATTRIBUTION_AND_EXACT_EQUIVALENCE':raise RuntimeError(report['status'])
    print(json.dumps({'status':report['status'],'equivalence':report['equivalence'],'buckets':report['buckets']},indent=2))

if __name__=='__main__':main()
