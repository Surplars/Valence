#!/usr/bin/env python3
"""Bounded source-bound phased fault regression; pin events, not STA/vendor proof."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result
run = module('qualification_helpers', HERE/'bscan_qualification_run.py')
DTM = ROOT/'src/main/resources/debug/ValenceJtagDebugPort.sv'
RTL = ROOT/'src/main/resources/debug/ValenceBscanDebugPort.sv'
BENCH = HERE/'bscan_fault_phase_tb.sv'
MUTANTS = {
    'negative_handoff': ([('always @(posedge bscan_tck or negedge source_reset_n)',
                           'always @(negedge bscan_tck or negedge source_reset_n)')], 'QUAL positive handoff bundle'),
    'self_reset_hard': ([('wire hard_reset_n = hard_release[2];','wire hard_reset_n = update_release[2];')], 'PHASE hard reset fault epoch'),
    'latched_free': ([('update_ack <= update_seen;', 'update_ack <= update_toggle == update_seen;'),
                      ('if (update_toggle == update_ack)', 'if (update_ack)')], 'QUAL duplicate UPDATE overwrote held frame'),
    'raw_sel': ([('end else if (update_selected)', 'end else if (bscan_sel && source_reset_n)')], 'QUAL UPDATE accepted before qualification'),
    'raw_reset_release': ([('wire update_reset_n = update_release[2];','wire update_reset_n = work_reset_n;')], 'QUAL positive fence early'),
    'negative_qualifier': ([('always @(posedge bscan_tck or negedge update_reset_n)',
                            'always @(negedge bscan_tck or negedge update_reset_n)')], 'QUAL fourth positive edge must sample selected/released'),
    'wrong_length': ([('shift_count == 64', 'shift_count == 63')], 'QUAL first legal 64-bit command'),
    'synchronous_assertion': ([('always @(posedge bscan_tck or negedge work_reset_n)',
                              'always @(posedge bscan_tck)')], 'QUAL positive fence early'),
    'lost_independent_sticky': ([('if (fault_sample && !hard_reset_command) protocol_error <= 1;',
                                'if (consume_update && fault_sample && !hard_reset_command) protocol_error <= 1;')], 'PHASE independent sticky F4 without UPDATE'),
    'sample_zero': ([('fault_sample <= update_overrun;', 'fault_sample <= 0;')], 'QUAL overrun did not fail closed'),
    'clear_wins': ([('if (fault_sample && !hard_reset_command) protocol_error <= 1;',
                    'if (fault_sample && !hard_reset_command && !(consume_update && request_op == 3 && request_address == 1)) protocol_error <= 1;')], 'PHASE CLEAR defeated fault'),
    'early_ack': ([('update_ack <= update_seen;', 'update_ack <= handoff_toggle;')], 'QUAL late duplicate held frame'),
    'stale_fault_reset': ([('            fault_sample <= 0;', '            fault_sample <= 1;')], 'QUAL asynchronous reset isolation'),
    'capability_fault_bypass': ([('visible_error || fault_sample || !source_ready', 'visible_error || !source_ready')], 'PHASE sampled fault admitted capability'),
}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mutants-only', action='store_true')
    parser.add_argument('--skip-mutants', action='store_true')
    parser.add_argument('--loader-fixture', type=Path)
    args=parser.parse_args()
    out=args.output.resolve()
    if out.exists(): parser.error('use a fresh output directory')
    iv,vvp=shutil.which('iverilog'),shutil.which('vvp')
    if not iv or not vvp: parser.error('existing Icarus/vvp required')
    paths=[RTL,DTM,BENCH,HERE/'bscan_fault_phase_run.py', HERE/'bscan_qualification_run.py',
           HERE/'bscan_user_tb.sv', HERE/'dmi_cdc_tb.sv', HERE/'evidence/bscan-prephase/bscan_qualification_tb.sv',
           HERE/'evidence/bscan-prephase/ValenceBscanDebugPort.sv',
           HERE/'evidence/bscan-prephase/bscan_qualification_mutations.py',
           HERE/'evidence/bscan-prephase/qualified-mutations-receipt.json']
    if args.loader_fixture:
        fixture=args.loader_fixture.resolve()
        fixture_script=fixture.parent/'prepare_fixture.py'
        fixture_module=module('bound_loader_fixture',fixture_script)
        loader_binding=fixture_module.verify(fixture,ROOT)
        if loader_binding['prepare_script_sha256'] != run.sha(fixture_script):
            parser.error('loader fixture preparation script changed')
        paths += [fixture/'JtagRamLoader.sv',fixture/'JtagRamLoader.original.sv',fixture/'binding.json',
                  fixture_script,HERE/'bscan_loader_fault_tb.sv',HERE/'lower_board_loader_for_icarus.py']
        paths += [ROOT/name for name in loader_binding['source_identities']]
        paths += [Path(name) for name in loader_binding['provenance_files']]
    before={str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p):run.sha(p) for p in paths}
    out.mkdir(parents=True)
    report=dict(schema='valence-bscan-fault-phase-v1', status='RUNNING', input_sha256=before, cases=[],
                physical_qualification=False, vendor_primitive_executed=False, logical_pin_event_model_only=True,
                original_immediate_revocation='PRESERVED_OLD_CONTRACT_COUNTEREXAMPLE_NOT_NEW_PASS',
                tools={k:dict(path=v,sha256=run.sha(Path(v))) for k,v in [('iverilog',iv),('vvp',vvp)]})
    def execute(name,top,sources,marker=None,oracle=None,params=()):
        directory=out/name;directory.mkdir()
        binary=directory/'test.vvp'
        row=dict(name=name,top=top,expected_oracle=oracle,status='RUNNING',stages=[])
        report['cases'].append(row)
        for stage,argv in [('compile',[iv,'-g2012','-Wall','-s',top,'-o',str(binary),*params,*map(str,sources)]),('run',[vvp,str(binary)])]:
            result=run.bounded(argv,directory/(stage+'.log'));row['stages'].append(dict(stage=stage,**result))
            if result['timed_out'] or (result['exit'] and (stage=='compile' or not oracle)):
                raise RuntimeError(name+' '+stage+' failed; compilation is never an oracle rejection')
        log=(directory/'run.log').read_text()
        fatals=re.findall(r'^FATAL:[^\n]*',log,re.MULTILINE)
        if oracle:
            if not row['stages'][-1]['exit'] or len(fatals)!=1 or oracle not in fatals[0] or 'PASS ' in log:
                raise RuntimeError(name+' missed exact oracle '+oracle)
            row['status']='PRESERVED_OLD_CONTRACT_COUNTEREXAMPLE' if name=='prephase_immediate_revoke' else 'EXPECTED_ORACLE_REJECTION'
        elif marker not in log or fatals or 'ERROR' in log:
            raise RuntimeError(name+' missing clean PASS')
        else:row['status']='PASS'
        row['binary_sha256']=run.sha(binary)
    code=0
    try:
        if not args.mutants_only:
            execute('phase','bscan_fault_phase_tb',[DTM,RTL,BENCH],'PASS BSCAN_FAULT_PHASE')
            execute('transport','bscan_user_tb',[DTM,RTL,HERE/'bscan_user_tb.sv'],'PASS BSCAN_USER')
            execute('cdc','dmi_cdc_tb',[DTM,HERE/'dmi_cdc_tb.sv'],'PASS CDC requests=101')
            execute('prephase_immediate_revoke','bscan_qualification_tb',[DTM,RTL,HERE/'evidence/bscan-prephase/bscan_qualification_tb.sv'],
                    oracle='QUAL late overrun did not fail closed')
            if args.loader_fixture:
                for bad in (0,1):
                    execute('loader_bad_owner' if bad else 'loader','bscan_loader_fault_tb',
                            [DTM,RTL,fixture/'JtagRamLoader.sv',HERE/'bscan_loader_fault_tb.sv'],
                            marker='BSCAN_LOADER_FAULT_PASS', oracle='DRAIN_OWNER_ORACLE' if bad else None,
                            params=['-Pbscan_loader_fault_tb.BAD_RESET_OWNER='+str(bad)])
        if not args.skip_mutants:
            original=RTL.read_text()
            for name,(edits,oracle) in MUTANTS.items():
                text=original
                for old,new in edits:
                    if text.count(old)!=1:raise RuntimeError('mutation anchor mismatch: '+name)
                    text=text.replace(old,new)
                staged=out/(name+'.sv');staged.write_text(text)
                execute(name,'bscan_fault_phase_tb',[DTM,staged,BENCH],oracle=oracle)
        after={str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p):run.sha(p) for p in paths}
        if before!=after:raise RuntimeError('source changed during checks')
        if args.loader_fixture:fixture_module.verify(fixture,ROOT)
        report['status']='PASS_PHASED_LOGICAL_CONTRACT_ONLY'
    except Exception as error:
        report.update(status='FAILED',error=str(error));code=1
    (out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return code
if __name__=='__main__':raise SystemExit(main())
