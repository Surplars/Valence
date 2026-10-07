#!/usr/bin/env python3
"""One passive full-token physical data-path model/run, gated on exact selected RV64IMC equivalence."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import hashlib
import tarfile
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
    baseline=common.BUILD/'backend-ownership-20261007-r2'
    baseline_receipt=json.loads((baseline/'receipt.json').read_text())
    assert baseline_receipt['status']=='PASS_OWNER_ATTRIBUTION_AND_EXACT_EQUIVALENCE'
    for name,digest in baseline_receipt['artifact_sha256'].items():
        assert perf.sha256(baseline/name)==digest, 'Prior artifact changed: '+name
    assert (baseline/'retired-pcs.bin').read_bytes()==(reference/'combined32.retired-pcs.bin').read_bytes()
    snapshot=Path('/workspace/shared/valence-data-path-20261007/starting-source.tar.gz')
    manifest_path=snapshot.with_name('starting-source-manifest.json')
    manifest=json.loads(manifest_path.read_text())['files']
    with tarfile.open(snapshot,'r:gz') as archive:
        for name,digest in manifest.items():
            assert hashlib.sha256(archive.extractfile(name).read()).hexdigest()==digest, name
    for name,digest in baseline_receipt['hardware_source_sha256'].items():
        assert manifest[name]==digest, 'Original hardware source differs from snapshot: '+name
    for name,digest in baseline_receipt['measurement_input_sha256'].items():
        path=Path(name)
        if path.is_relative_to(common.ROOT):
            relative=str(path.relative_to(common.ROOT))
            if relative in manifest:
                assert manifest[relative]==digest, 'Original measurement source differs: '+relative
    allowed_changes={'src/main/scala/core/ooo/MappedMachineCore.scala',
        'src/test/scala/ooo/BoardSocGsimMain.scala','simulator/gsim/harness/backend_observer.h'}
    actual_changes={name for name,digest in manifest.items() if perf.sha256(common.ROOT/name)!=digest}
    assert actual_changes <= allowed_changes, 'Unexpected source edits: '+str(actual_changes-allowed_changes)

    previous=json.loads((reference/'receipt.json').read_text());selected=previous['runs']['combined32']
    assert previous['status']=='PASS_MATCHED_RV64IMC_PAIR'
    image=firmware/'coremark_board.bin'
    assert perf.sha256(image)==previous['firmware_bin_sha256']
    start,stop=(int(previous['roi'][key],16) for key in ('start','stop'))
    inputs=[Path(__file__),common.HERE/'run.py',common.HERE/'throughput_perf.py',common.HERE/'frontend_perf.py',
            common.ROOT/'build.mill',common.ROOT/'.mill-version',common.ROOT/'.mill-jvm-opts',
            common.ROOT/'scripts/cloud/env.sh',common.HERE/'harness/data_path_sample.h',common.HERE/'harness/data_path_ownership_ledger.h',
            common.HERE/'harness/data_path_ownership_test.cpp',baseline/'receipt.json',baseline/'board_coremark.log',common.HERE/'harness/backend_ownership_ledger.h',common.HERE/'harness/backend_observer.h',
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
    report={'status':'RUNNING','scope':'Observation only; persistent StoreBuffer writes, full translation queue lineage, ordered fault placeholders and relocated response buffer; physical router/cache service unknown',
            'configuration':{'profile':'staged-fetch-turnover','instruction_cache_lines':32,'instruction_cache_bytes':2048,
                'issue_width':2,'isa':'rv64gc','fpu':True,'clock_hz':100000000,'uart_baud':460800,
                'ddr_bytes':2147483648,'data_cache_ways':2,'load_issue_forwarding':False},
            'baseline_receipt_sha256':perf.sha256(baseline/'receipt.json'),'baseline_artifacts_verified':True,
            'starting_snapshot_sha256':perf.sha256(snapshot),'starting_manifest_sha256':perf.sha256(manifest_path),
            'baseline_sources_verified_against_snapshot':True,'changed_existing_sources':sorted(actual_changes),
            'baseline_hardware_source_sha256':baseline_receipt['hardware_source_sha256'],
            'firmware_bin_sha256':perf.sha256(image),'roi':previous['roi'],'hardware_source_sha256':hardware,
            'measurement_input_sha256':before,'reference_receipt_sha256':perf.sha256(reference/'receipt.json'),
            'limitations':['No functional optimization; no CAD, physical board, full regression or Linux.',
                'Physical service after translation is unknown: no router/cache owner stage attribution.',
                'Capacity probe covers the actual selected younger load, not every unselected ready reservation.',
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
        data_unit=out/'data_path_test'
        common.run([cxx,*flags,common.HERE/'harness/data_path_ownership_test.cpp','-o',data_unit],log=out/'data-unit-compile.log')
        common.run([data_unit],env=env,log=out/'data-unit.log')
        report['independent_data_path_tests']=(out/'data-unit.log').read_text().strip()
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
        defines=['-DDATA_PATH_OWNERSHIP_PROBES=1','-DUART_DIVISOR=1','-DBOARD_CPU_HZ=100000000','-DBOARD_UART_BAUD=460800','-DUART_EXTRA_STOP_BITS=0',
                 '-DDDR_MODEL=1','-DBOARD_DDR_BYTES=2147483648ULL','-DAPP_TIMEBASE_HZ=50000000']
        common.run([cxx,*flags,*defines,*objects,driver,'-ldl','-o',binary],log=out/'driver-compile.log')
        trace=out/'retired-pcs.bin';log=out/'board_coremark.log'
        common.run([binary,image],env={**env,'FRONTEND_RETIRE_TRACE':str(trace)},log=log,timeout=600)
        current=log.read_text();old=(reference/'combined32.log').read_text()
        without_data='\n'.join(line for line in current.splitlines() if not line.startswith('DATA_PATH_'))+'\n'
        assert without_data==(baseline/'board_coremark.log').read_text(), 'Prior owner counters/output changed'
        legacy='\n'.join(line for line in without_data.splitlines() if not line.startswith('BACKEND_OWNER_'))+'\n'
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
        data_buckets=rows('DATA_PATH_BUCKET')
        assert sum(int(r['cycles']) for r in data_buckets)==486606
        assert sum(int(r['cycles']) for r in rows('DATA_PATH_SERIAL'))==10931
        assert selected['ticks']==486605
        report.update(status='PASS_DATA_PATH_ATTRIBUTION_AND_EXACT_EQUIVALENCE',existing_counters=counts,
            equivalence={'guest_and_all_prior_output':'BYTE_IDENTICAL','retired_pc_stream_sha256':perf.sha256(trace),
                'retired_instructions':trace.stat().st_size//8,'guest_ticks':selected['ticks']},
            buckets=buckets,totals=totals,ledger=rows('BACKEND_OWNER_LEDGER')[0],
            data_path_buckets=data_buckets,data_path_serial=rows('DATA_PATH_SERIAL'),
            data_path_capacity=rows('DATA_PATH_CAPACITY')[0],data_path_ledger=rows('DATA_PATH_LEDGER'),
            prior_owner_output_equivalence='BYTE_IDENTICAL')
    except Exception as error:
        report['status']='FAIL_OWNER_ATTRIBUTION';report['failure']=str(error);raise
    finally:
        after={str(p):perf.sha256(p) for p in inputs}
        report['source_unchanged_during_measurement']=before==after and hardware==perf.hardware_sources()
        if not report['source_unchanged_during_measurement']:report['status']='FAIL_INPUT_DRIFT'
        report['artifact_sha256']={str(p.relative_to(out)):perf.sha256(p) for p in out.rglob('*') if p.is_file() and p.name!='receipt.json'}
        (out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['status']!='PASS_DATA_PATH_ATTRIBUTION_AND_EXACT_EQUIVALENCE':raise RuntimeError(report['status'])
    print(json.dumps({'status':report['status'],'equivalence':report['equivalence'],'data_path_buckets':report['data_path_buckets']},indent=2))

if __name__=='__main__':main()
