#!/usr/bin/env python3
"""Stage the one source-bound r5 native emission; never elaborate or qualify CPU."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
CANDIDATE = 'timing-r5-structural-ready73-r1'
RELEASE_FILES = ('board_timing_r5.py', 'run_timing_r5.py', 'timing-r5-input-pins.json',
                 'test_timing_r5_entry.py', 'timing-r5-entry.md')

def release_inventory():
    return {n: sha(HERE / n) for n in RELEASE_FILES}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read(path):
    return json.loads(Path(path).read_text())

def equal(actual, expected, reason):
    if json.dumps(actual, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True, allow_nan=False):
        raise RuntimeError(reason)

def module(source, filename):
    path = source / 'fpga/next' / filename
    spec = importlib.util.spec_from_file_location('r5_' + path.stem, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

def inventory(directory):
    return {p.relative_to(directory).as_posix(): sha(p) for p in sorted(directory.rglob('*')) if p.is_file()}

def check_files(directory, files):
    for name, digest in files.items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or not name or not (directory / path).is_file():
            raise RuntimeError('unsafe/missing input: ' + name)
        equal(sha(directory / path), digest, 'changed input: ' + name)

def inputs(source, evidence):
    pins = read(HERE / 'timing-r5-input-pins.json')
    equal(pins['candidate'], CANDIDATE, 'wrong candidate')
    names = {'source-freeze-r1.json': 'source_freeze_sha256', 'compile.json': 'compile_receipt_sha256',
             'native-emission-r1.json': 'native_receipt_sha256'}
    for name, key in names.items():
        equal(sha(evidence / name), pins[key], 'wrong r5 evidence: ' + name)
    freeze = read(evidence / 'source-freeze-r1.json')
    equal(len(freeze['files']), pins['source_files'], 'incomplete frozen source')
    check_files(source, freeze['files'])
    prior = module(source, 'resident_memory_source_bridge.py')
    source_names = {p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()
        and not any(x in prior.ARTIFACT_COMPONENTS for x in p.relative_to(source).parts)
        and p.suffix != '.pyc'}
    extras = {'fpga/next/' + n for n in RELEASE_FILES if (source / 'fpga/next' / n).is_file()}
    equal(sorted(source_names), sorted(set(freeze['files']) | extras), 'unknown or missing final source leaf')
    for name in extras:
        equal(sha(source / name), sha(HERE / Path(name).name), 'published adapter differs')
    compile_receipt = read(evidence / 'compile.json')
    equal(compile_receipt['status'], 'PASS_COMPILE_ONLY', 'compile not complete')
    for name, digest in compile_receipt['sources'].items():
        equal(freeze['files'].get(name), digest, 'compile/source mismatch: ' + name)
    native = read(evidence / 'native-emission-r1.json')
    equal(native['schema'], 'r5-native-source-binding-v1', 'wrong native schema')
    equal(native['candidate'], CANDIDATE, 'wrong native candidate')
    equal(native['status'], 'PASS_R5_NATIVE_ACTUAL_EMISSION_PENDING_STAGING', 'native incomplete')
    for key in ('source_freeze_sha256', 'compile_receipt_sha256', 'parameter_contract_sha256'):
        equal(native[key], pins[key], 'native input identity differs: ' + key)
    equal(native['new_source_qualification_inherited'], False, 'historical qualification inherited')
    equal(native['physical_qualification'], False, 'native claims physical qualification')
    profile_path = source / 'fpga/next/timing-ready73-profile.json'
    equal(sha(profile_path), pins['parameter_contract_sha256'], 'parameter contract changed')
    return freeze, native, read(profile_path)

def actual(source, native, profile):
    # Reuse pure comparators only, never old load_profile/source bridge/qualification.
    old = module(source, 'board_timing_ready73.py')
    equal(read(native / 'profile.json'), profile['on_profile'], 'actual 177/94 profile differs')
    equal(read(native / 'actual-product-field-order.json'),
          {k: profile[k + '_fields'] for k in ('core', 'profile')}, 'actual ordered fields differ')
    equal(read(native / 'actual-timing-closure.json'), old.expected(profile, 'on', 'timing_audit'), 'actual timing audit differs')
    for name, key in [('actual-held-alu-forwarding.json', 'held'), ('actual-resident-memory.json', 'resident'), ('actual-mac-raw-handoff.json', 'mac')]:
        equal(read(native / name), old.expected(profile, 'on', 'existing_audits')[key], 'actual audit differs: ' + key)
    equal(read(native / 'timing-ready73-entry.json'), old.completion(profile), 'native parameter-only completion differs')
    equal((native / 'options.txt').read_text(), ''.join(x + '\n' for x in profile['on_options']), 'ordered73 options differ')

def stage(source, native, evidence, output):
    freeze, emitted, profile = inputs(source, evidence)
    equal(inventory(native), emitted['files'], 'native emission file closure differs')
    actual(source, native, profile)
    if output.exists():
        raise RuntimeError('fresh staging directory required')
    output.mkdir(parents=True)
    shutil.copytree(native, output / 'rtl')
    shutil.copytree(evidence, output / 'r5-evidence')
    exporter = module(source, 'export.py')
    board = output / 'board'
    board.mkdir()
    wrapper_source = source / 'fpga/next/soc_top_fpga_next_ddr.sv'
    wrapper = exporter.bscan_board_wrapper(wrapper_source.read_text())
    count = exporter.check_wrapper_ports(wrapper, (native / 'FpgaNextSocTop.sv').read_text())
    path = board / wrapper_source.name
    path.write_text(wrapper)
    receipt = {'schema': 'valence-fpga-next-export-v1', 'status': 'RUNNING', 'named_entry': CANDIDATE,
        'source_sha256': freeze['files'], 'source_identity': {'kind': 'r5-frozen-compile-inputs', 'sha256': sha(evidence / 'source-freeze-r1.json')},
        'physical_qualification': False, 'synthesis': False, 'historical_cpu_qualification_inherited': False,
        'cpu_qualification': 'PENDING_R5_INTEGRATION_RECEIPT',
        'board_wrapper': {'path': 'board/' + path.name, 'sha256': sha(path),
            'source': 'fpga/next/' + path.name, 'source_sha256': sha(wrapper_source),
            'media': 'experimental-trispeed', 'named_ports_checked': count, 'qualified': False}}
    receipt['tri_speed_native_integration'] = exporter.media_integration.stage(source, output)
    shutil.copy2(source / 'fpga/next/check_jtag_chain.tcl', board / 'check_jtag_chain.tcl')
    (board / 'require_jtag_chain.tcl').write_text(
        'source [file join [file dirname [info script]] check_jtag_chain.tcl]\n'
        'if {![info exists VALENCE_JTAG_OWN_CELL]} {error {Set exact VALENCE_JTAG_OWN_CELL from the open synthesized design}}\n'
        'valence_assert_jtag_chain 2 $VALENCE_JTAG_OWN_CELL\n')
    receipt['bscan_timing_candidate'] = exporter.bscan_integration.stage(source, output, 2)
    listed = [x.strip() for x in (native / 'filelist.f').read_text().splitlines() if x.strip() and not x.strip().startswith('#')]
    for name in ('ValenceJtagDebugPort.sv', 'ValenceBscanDebugPort.sv', 'ValenceMacRawFallingSample.sv'):
        if not (native / name).is_file():
            raise RuntimeError('missing required resource: ' + name)
        if name not in listed:
            listed.append(name)
    check_files(native, {n: emitted['files'].get(n) for n in listed})
    (output / 'synthesis-files.f').write_text(''.join('rtl/' + n + '\n' for n in listed))
    receipt['synthesis_filelist_sha256'] = sha(output / 'synthesis-files.f')
    receipt['rtl_sha256'] = {'rtl/' + n: h for n, h in emitted['files'].items()}
    receipt['native_mac_mode'] = exporter.board_t1.stage(source, output, True, True)
    receipt['status'] = 'PASS_RTL_EXPORT_ONLY'
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    exporter.board_t1.verify(output)
    inputs(source, evidence)
    # No circular identity: only newly added release files, separate from frozen RTL inputs.
    release = release_inventory()
    seal = {'schema': 'r5-staged-physical-input-v1', 'candidate': CANDIDATE,
        'files': inventory(output), 'release_files': release,
        'physical_qualification': False, 'cpu_qualification': 'PENDING_R5_INTEGRATION_RECEIPT'}
    (output / 'r5-staging.json').write_text(json.dumps(seal, indent=2) + '\n')
    return seal

def verify(source, output):
    seal = read(output / 'r5-staging.json')
    equal(seal['schema'], 'r5-staged-physical-input-v1', 'wrong staging schema')
    equal(seal['candidate'], CANDIDATE, 'wrong staged candidate')
    files = inventory(output)
    del files['r5-staging.json']
    equal(files, seal['files'], 'staged files changed or unbound')
    equal(release_inventory(), seal['release_files'], 'release adapter changed')
    _, emitted, profile = inputs(source, output / 'r5-evidence')
    equal(inventory(output / 'rtl'), emitted['files'], 'staged RTL differs from unique native emission')
    actual(source, output / 'rtl', profile)
    module(source, 'board_t1.py').verify(output)
    return seal

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument('--source', required=True, type=Path)
    p.add_argument('--native', required=True, type=Path)
    p.add_argument('--evidence', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    stage(a.source.resolve(), a.native.resolve(), a.evidence.resolve(), a.output.resolve())
    print('PASS_R5_STAGING_ONLY_NO_CPU_OR_PHYSICAL_QUALIFICATION')
