#!/usr/bin/env python3
"""Audit final matched evidence after the documented pre-locality firmware refinement.

Never edits the original receipt, hides a failing workload, or rebuilds hardware.
The accepted drift is exactly ddr_bench.c and its locality C++ driver, frozen before
any locality driver existed. All hardware, scalar counters and other inputs match.
"""
import argparse
import difflib
import json
from pathlib import Path
import re
import subprocess
import data_cache_capacity as exp
from analyze_frontend_perf import rows
from data_cache_geometry import verify


def normalized_modules(path):
    text=path.read_text();result={}
    for m in re.finditer(r'^  (?:(?:public )?module|extmodule) (\w+) .*?(?=^  (?:(?:public )?module|extmodule) |\Z)',text,re.M|re.S):
        body=re.sub(r' @\[[^\n]*?\]','',m[0])
        result[m[1]]=re.sub(r'Assertion failed at (\w+\.scala):\d+',r'Assertion failed at \1:LINE',body)
    return result


def compare_models(base,candidate):
    b,c=normalized_modules(base),normalized_modules(candidate)
    assert b.keys()==c.keys()
    changed=sorted(n for n in b if b[n]!=c[n])
    assert changed==['BoardSocGsim','CoherentLineCache','CoherentLineHome']
    added=[]
    for line in difflib.ndiff(b['BoardSocGsim'].splitlines(),c['BoardSocGsim'].splitlines()):
        assert not line.startswith('- '),'unexpected removed top-level logic'
        if line.startswith('+ '):
            v=line[2:];added.append(v)
            assert re.fullmatch(r'    (?:output (?:memoryLiveSlots|backend\w+|dataPath\w+) : UInt<\d+>|connect (?:memoryLiveSlots|backend\w+|dataPath\w+), (?:UInt<1>\(0h0\)|reset))',v),v
    verify(base.read_text(),32,probes=True);verify(candidate.read_text(),64,probes=True)
    return {'baseline_sha256':exp.perf.sha256(base),'candidate_sha256':exp.perf.sha256(candidate),
            'identical_module_count':len(b)-len(changed),'changed_modules':changed,
            'disabled_top_observer_additions':added,
            'normalization':'source annotations and assertion diagnostic Scala line numbers only'}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--raw',type=Path,required=True)
    ap.add_argument('--frozen-inputs',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();assert not a.out.exists()
    raw=json.loads(a.raw.read_text());frozen=json.loads(a.frozen_inputs.read_text())
    assert raw['status']=='FAIL_SOURCE_DRIFT' and 'failure' not in raw
    assert frozen['captured_before_any_locality_driver_exists']
    assert frozen['source_sha256']==exp.inputs(), 'frozen measurement source changed'
    drift=sorted(p for p,v in raw['source_sha256'].items() if frozen['source_sha256'][p]!=v)
    assert drift==sorted(str(exp.common.ROOT/p) for p in ('fpga/firmware/ddr_bench.c','simulator/gsim/harness/data_cache_locality.cpp'))
    for group in ('additional_compiled_inputs','final_locality_firmware'):
        assert all(exp.perf.sha256(Path(p))==v for p,v in frozen[group].items()),group+' changed'
    assert all(exp.perf.sha256(Path(p))==v for p,v in raw['artifacts'].items()),'raw result changed'
    parent=a.raw.parent
    comparison=compare_models(exp.BASE/'board-model/BoardSocGsim.fir',parent/'board-model/BoardSocGsim.fir')
    original=json.loads((exp.BASE/'receipt.json').read_text())
    for name in ('CoherentLineCache','CoherentLineHome'):
        p=Path('src/main/scala/core/ooo')/(name+'.scala')
        assert exp.perf.sha256(exp.common.ROOT/p)==original['hardware_source_sha256'][str(p)]
    finals={}
    for label in ('dcache2k','dcache4k'):
        run=raw['runs'][label]['workloads'];assert set(run)=={'board_coremark','ddr_bench_app','rv64gc_board','data_cache_locality'}
        assert run['board_coremark']['retired_pc_sha256']==exp.PC_HASH
        assert run['board_coremark']['ipc'][1]['retired']==360528
        for name in run:
            text=(parent/(label+'-'+name+'.log')).read_text()
            assert 'PASS' in text and not re.search(r'\bFAIL\b',text)
            for row in rows(text,'DCACHE'):
                assert row['misses']==row['empty']+row['replacements']==row['read_miss']+row['write_miss']
                assert sum(row['state_'+str(i)] for i in range(12))==row['cycles']
                if row['name']=='whole_run':assert row['writeback_beats']==8*row['writeback_lines']
        log=(parent/(label+'-data_cache_locality.log')).read_text()
        totals=rows(log,'COMPLETE');assert len(totals)==8
        assert [(r['size'],r['phase']) for r in totals]==[(b,p) for b in (1024,2048,4096,8192) for p in ('write','copy')]
        for index,total in enumerate(totals):
            size_index=index//2;phase_index=2 if total['phase']=='write' else 4
            kernel,flush=run['data_cache_locality']['phases'][size_index*8+phase_index:size_index*8+phase_index+2]
            assert total['ticks']>=kernel['ticks']+flush['ticks'], 'enclosing interval excludes substage cycles'
        # Actual driver contains final firmware/host protocol; final ELF marker
        # addresses must equal the constants used in both compiled command logs.
        driver=parent/(label+'-data_cache_locality.cpp')
        assert exp.perf.sha256(driver)==frozen['source_sha256'][str(exp.common.HERE/'harness/data_cache_locality.cpp')], 'generated locality driver differs from frozen source'
        elf=exp.common.BUILD/'dcache-locality-firmware-20261007/ddr_bench.elf'
        driver_build=(Path('/workspace/shared/valence-dcache-20261007/board.log')).read_text()
        for name,flag in [('locality_start','START'),('locality_stop','STOP')]:
            assert f'-DLOCALITY_{flag}_PC={exp.rdtime(elf,name)}ULL' in driver_build
        negative=(parent/(label+'-data_cache_locality.negative.log')).read_text()
        assert 'stream store/copy did not reach AXI backing memory' in negative
        finals[label]=totals
    final={**raw,'status':'PASS_AUDITED_MATCHED_DCACHE_CAPACITY','source_sha256':frozen['source_sha256'],
      'final_measurement_inputs':frozen,'model_comparison':comparison,'continuous_completion_intervals':finals,
      'input_epoch_reconciliation':{'raw_receipt':str(a.raw),'raw_sha256':exp.perf.sha256(a.raw),
        'raw_status':raw['status'],'changed_paths':drift,'final_snapshot':str(a.frozen_inputs),
        'final_snapshot_sha256':exp.perf.sha256(a.frozen_inputs),
        'reason':'User-requested continuous kernel-through-flush totals and neutral locality banner were completed before either locality harness was generated. No hardware/scalar-observer/CoreMark change. Raw pre-locality firmware/source snapshot is superseded only for those files; original receipt is preserved.'},
      'finalizer_sha256':exp.perf.sha256(Path(__file__))}
    final['firmware_sha256']=dict(raw['firmware_sha256'])
    for p,v in frozen['final_locality_firmware'].items():
        matches=[key for key in final['firmware_sha256'] if Path(key).resolve()==Path(p).resolve()]
        for key in matches:final['firmware_sha256'][key]=v
        if not matches:final['firmware_sha256'][p]=v
    final['continuous_completion_comparison']=[{**b,'candidate_ticks':c['ticks'],
       'tick_reduction_percent':100*(b['ticks']-c['ticks'])/b['ticks']} for b,c in zip(finals['dcache2k'],finals['dcache4k'])]
    a.out.write_text(json.dumps(final,indent=2)+'\n');print(a.out)
if __name__=='__main__':main()
