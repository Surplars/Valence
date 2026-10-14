#!/usr/bin/env python3
"""Launch original ready73 Tcl only after fresh r5 source/native/behavior gates."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True
from board_timing_r5 import CANDIDATE, HERE, equal, read, sha, verify, check_files


def qualification(path):
    q = read(path)
    pins = read(HERE / 'timing-r5-input-pins.json')
    equal(sha(path), pins['qualification_sha256'], 'qualification receipt bytes differ from verified r5 result')
    equal(q['candidate'], CANDIDATE, 'wrong qualification candidate')
    equal(q['schema'], 'valence-r5-structural-ready73-qualification-v1', 'wrong qualification schema')
    equal(q['status'], 'PASS_COMPONENT_AND_SEVEN_POSITIVE_EIGHT_NEGATIVE', 'r5 behavioral gate incomplete')
    for actual, expected in [('source_freeze_sha256', 'source_freeze_sha256'),
                             ('compile_receipt_sha256', 'compile_receipt_sha256'),
                             ('native_emission_receipt_sha256', 'native_receipt_sha256')]:
        equal(q[actual], pins[expected], 'qualification input differs: ' + actual)
    for key in ('physical_qualification', 'historical_cpu_qualification_inherited'):
        equal(q[key], False, 'qualification exceeds r5 behavioral scope: ' + key)
    files = q['evidence_files']
    if not files or not q['new_model_objects']:
        raise RuntimeError('missing actual r5 evidence/model objects')
    check_files(path.parent, files)
    # Exact pinned qualification binds objects verified on the build executor.
    # Physical consumption needs their emitted RTL, not copies of compiler objects.
    for key in ('short_tests_receipt_sha256', 'integration_receipt_sha256', 'integration_plan_sha256'):
        if q[key] not in files.values():
            raise RuntimeError('unbound behavioral evidence: ' + key)
    return q


def launch(vivado, source, export, binding, output, qualified):
    verify(source, export)
    qualification(qualified)
    if output.exists():
        raise RuntimeError('fresh physical output required')
    bound = {str(p): sha(p) for p in (qualified, export / 'r5-staging.json', binding,
             source / 'fpga/next/run_timing_ready73.tcl')}
    command = [str(vivado), '-mode', 'batch', '-source', str(source / 'fpga/next/run_timing_ready73.tcl'),
               '-tclargs', str(binding), str(output), str(export)]
    result = subprocess.run(command, check=False)
    if result.returncode:
        return result.returncode if result.returncode > 0 else 128 - result.returncode
    marker = output / 'evaluation-complete.txt'
    if not marker.is_file() or not marker.read_text().splitlines() or marker.read_text().splitlines()[0] != 'COMPLETED_SYNTH_OPT_PLACE_NOT_TIMING_SIGNOFF':
        return 1
    verify(source, export)
    qualification(qualified)
    for name, digest in bound.items():
        equal(sha(Path(name)), digest, 'physical run input changed: ' + name)
    # Bind the observed physical run to its reviewed local inputs, without a timing-PASS claim.
    receipt = {'schema': 'r5-physical-observation-v1', 'candidate': CANDIDATE,
        'status': 'COMPLETED_SYNTH_OPT_PLACE_NOT_TIMING_SIGNOFF',
        'qualification_sha256': sha(qualified), 'staging_sha256': sha(export / 'r5-staging.json'),
        'binding_sha256': sha(binding), 'driver_sha256': sha(source / 'fpga/next/run_timing_ready73.tcl'),
        'physical_qualification': False}
    (output / 'r5-observation.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return 0

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for key in ('source', 'export', 'binding', 'output', 'qualification'):
        p.add_argument('--' + key, required=True, type=Path)
    p.add_argument('--vivado', required=True)
    a = p.parse_args()
    raise SystemExit(launch(a.vivado, a.source.resolve(), a.export.resolve(), a.binding.resolve(), a.output.resolve(), a.qualification.resolve()))
