#!/usr/bin/env python3
"""Check the independent R6 source/native/behavior evidence; never run hardware tools."""
import argparse
import hashlib
import json
from pathlib import Path

CANDIDATE = 'r6-publication-lsu-fetch-exact73'
HERE = Path(__file__).resolve().parent

def read(path):
    return json.loads(Path(path).read_text())

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def equal(actual, expected, label):
    if actual != expected:
        raise RuntimeError(label)

def files(root, manifest):
    for name, digest in manifest.items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or not name:
            raise RuntimeError('unsafe evidence member: ' + name)
        equal(sha(root / path), digest, 'changed evidence: ' + name)

def check(source, native, evidence, pins):
    equal(pins['candidate'], CANDIDATE, 'wrong pinned candidate')
    files(evidence, pins['evidence'])
    q = read(evidence / 'qualification.json')
    equal(q['schema'], 'r6-combined-cpu-qualification-v1', 'wrong qualification schema')
    equal(q['candidate'], CANDIDATE, 'wrong qualification candidate')
    equal(q['status'], 'PASS_COMBINED_COMPONENT_AND_SEVEN_POSITIVE_EIGHT_NEGATIVE', 'behavior gate incomplete')
    equal(q['historical_qualification_inherited'], False, 'old qualification inherited')
    equal((q['positive_cases'], q['negative_controls'], q['combined_parallel_controls']), (7, 8, 12), 'incomplete gate set')
    equal(q['new_source_classes_and_model'], True, 'old model')
    equal(q['reset_candidate_included'], False, 'unexpected reset candidate')
    files(evidence, q['evidence_files'])
    if not q['new_model_objects']:
        raise RuntimeError('missing model binding')
    supplement = read(evidence / 'qualification-supplement-r1.json')
    equal(supplement['status'], 'PASS_ACTUAL_BACKEND_RETAINED_PROOF_WITNESS', 'reserve witness incomplete')
    equal(supplement['candidate'], CANDIDATE, 'wrong reserve candidate')
    equal(supplement['base_qualification_sha256'], pins['evidence']['qualification.json'], 'reserve base mismatch')
    equal(supplement['native_receipt_sha256'], pins['evidence']['native-emission-r1.json'], 'reserve native mismatch')
    equal(supplement['source_freeze_sha256'], pins['evidence']['source-freeze.json'], 'reserve source mismatch')
    files(evidence, supplement['evidence_files'])
    freeze = read(evidence / 'source-freeze.json')
    equal(len(freeze['files']), pins['source_files'], 'source closure count')
    files(source, freeze['files'])
    compile_receipt = read(evidence / 'build/compile.json')
    equal(compile_receipt['status'], 'PASS_NEW_INDEPENDENT_CLASSES', 'compile incomplete')
    for name, digest in compile_receipt['sources'].items():
        equal(freeze['files'].get(name), digest, 'compile/source mismatch')
    emitted = read(evidence / 'native-emission-r1.json')
    equal(emitted['schema'], 'r6-native-source-binding-v1', 'wrong native schema')
    equal(emitted['candidate'], CANDIDATE, 'wrong native candidate')
    equal(emitted['status'], 'PASS_R6_NATIVE_ACTUAL_EMISSION_PENDING_STAGING', 'native incomplete')
    for key, member in [('source_freeze_sha256', 'source-freeze.json'), ('compile_receipt_sha256', 'build/compile.json'), ('combined_cpu_qualification_sha256', 'qualification.json')]:
        equal(emitted[key], pins['evidence'][member], 'native binding mismatch: ' + key)
    equal(emitted['physical_qualification'], False, 'unmeasured physical claim')
    equal(emitted['new_source_qualification_inherited'], False, 'old native qualification')
    actual = {p.relative_to(native).as_posix(): sha(p) for p in native.rglob('*') if p.is_file()}
    equal(actual, emitted['files'], 'native file closure changed')
    contract_path = source / 'fpga/next/timing-ready73-profile.json'
    equal(sha(contract_path), pins['parameter_contract_sha256'], 'parameter contract changed')
    equal(emitted['parameter_contract_sha256'], pins['parameter_contract_sha256'], 'native parameter pin')
    contract = read(contract_path)
    equal(read(native / 'profile.json'), contract['on_profile'], 'actual profile differs')
    equal((native / 'options.txt').read_text().splitlines(), contract['on_options'], 'ordered options differ')
    equal((len(contract['core_fields']), len(contract['profile_fields']), len(contract['on_options'])), (177, 94, 73), 'parameter counts')
    # Exact receipt pins bind all actual constructor audits. Re-running compilation or
    # distributing model objects is unnecessary for consuming this emitted RTL.
    return {'candidate': CANDIDATE, 'status': 'PASS_R6_BOUND_INPUT_REVIEW_ONLY',
            'release_state': pins['release_state'], 'source_identity_scope': 'exact frozen compile-input subset; release adapters checked separately', 'physical_qualification': False}

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ('source', 'native', 'evidence'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(check(a.source, a.native, a.evidence, read(HERE / 'timing-r6-input-pins.json')), sort_keys=True))
