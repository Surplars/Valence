#!/usr/bin/env python3
"""Kill narrow BSCAN control/reset mutants with the independent pin-event bench.

Only staged test copies change. Compilation failures never count as killed
mutants; each run must reach its own exact behavioral oracle and no PASS.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import shutil

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("bscan_qualification_run", HERE/"bscan_qualification_run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)

MUTANTS = {
    "negative_handoff": ([('always @(posedge bscan_tck or negedge source_reset_n)',
                              'always @(negedge bscan_tck or negedge source_reset_n)')],
                            'QUAL positive handoff bundle'),
    "sampled_overrun": ([('    wire accept_dmi =',
                           '    reg sampled_overrun;\n'
                           '    always @(posedge bscan_tck or negedge source_reset_n)\n'
                           '        if (!source_reset_n) sampled_overrun <= 0;\n'
                           '        else sampled_overrun <= update_overrun;\n'
                           '    wire accept_dmi ='),
                          ('!protocol_error && !update_overrun && source_ready',
                           '!protocol_error && !sampled_overrun && source_ready')],
                         'QUAL late overrun did not fail closed'),
    "self_reset_hard": ([('wire hard_reset_n = hard_release[2];',
                          'wire hard_reset_n = update_release[2];')],
                         'QUAL hard reset assertion'),
    "latched_free": ([('update_ack <= update_seen;', 'update_ack <= update_toggle == update_seen;'),
                      ('if (update_toggle == update_ack)', 'if (update_ack)')],
                     'QUAL duplicate UPDATE overwrote held frame'),
    "raw_sel": ([('end else if (update_selected)', 'end else if (bscan_sel && source_reset_n)')],
                'QUAL UPDATE accepted before qualification'),
    "raw_reset_release": ([('wire update_reset_n = update_release[2];', 'wire update_reset_n = work_reset_n;')],
                          'QUAL positive fence early'),
    "negative_qualifier": ([('always @(posedge bscan_tck or negedge update_reset_n)',
                             'always @(negedge bscan_tck or negedge update_reset_n)')],
                           'QUAL fourth positive edge must sample selected/released'),
    "wrong_length": ([('shift_count == 64', 'shift_count == 63')], 'QUAL first legal 64-bit command'),
    "synchronous_assertion": ([('always @(posedge bscan_tck or negedge work_reset_n)',
                               'always @(posedge bscan_tck)')], 'QUAL positive fence early'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists():
        parser.error('use a fresh output directory')
    iverilog, vvp = shutil.which('iverilog'), shutil.which('vvp')
    if not iverilog or not vvp:
        parser.error('existing Icarus/vvp required')
    rtl = run.ROOT/run.BSCAN
    original = rtl.read_text()
    sources = [run.DTM, run.BSCAN, 'simulator/jtag/bscan_qualification_tb.sv',
               'simulator/jtag/bscan_qualification_run.py', 'simulator/jtag/bscan_qualification_mutations.py']
    before = {name: run.sha(run.ROOT/name) for name in sources}
    out.mkdir(parents=True)
    report = dict(schema='valence-bscan-mutations-v1', status='RUNNING', input_sha256=before,
                  mutants=[], physical_qualification=False, vendor_primitive_executed=False)
    code = 0
    try:
        for name, (edits, oracle) in MUTANTS.items():
            directory = out/name
            directory.mkdir()
            text = original
            for old, new in edits:
                if text.count(old) != 1:
                    raise RuntimeError('mutation anchor mismatch: ' + name)
                text = text.replace(old, new)
            staged = directory/'mutant.sv'
            staged.write_text(text)
            binary = directory/'test.vvp'
            row = dict(name=name, oracle=oracle, staged_rtl_sha256=run.sha(staged), stages=[], status='RUNNING')
            report['mutants'].append(row)
            compile_cmd = [iverilog, '-g2012', '-s', 'bscan_qualification_tb', '-o', str(binary),
                           str(run.ROOT/run.DTM), str(staged), str(HERE/'bscan_qualification_tb.sv')]
            result = run.bounded(compile_cmd, directory/'compile.log')
            row['stages'].append(dict(stage='compile', **result))
            if result['exit'] or result['timed_out']:
                raise RuntimeError('compile failure is not a killed mutant: ' + name)
            result = run.bounded([vvp, str(binary)], directory/'run.log')
            row['stages'].append(dict(stage='run', **result))
            log = (directory/'run.log').read_text()
            fatals = re.findall(r'^FATAL:[^\n]*', log, re.MULTILINE)
            if result['timed_out'] or len(fatals) != 1 or oracle not in fatals[0] or 'PASS BSCAN_QUALIFICATION' in log:
                raise RuntimeError('mutant did not reach its exact behavioral oracle: ' + name)
            row['status'] = 'EXPECTED_ORACLE_REJECTION'
        if {name: run.sha(run.ROOT/name) for name in sources} != before:
            raise RuntimeError('source changed during mutant checks')
        report['status'] = 'PASS_ALL_MUTANTS_KILLED'
    except Exception as error:
        code = 1
        report.update(status='FAILED', error=str(error))
    (out/'receipt.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
