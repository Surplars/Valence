#!/usr/bin/env python3
"""Source proposal: read-only admission of a fresh MAC bundle; never run tools.

Called via native_mac_session's explicitly configured Unix/WSL Python route.
This checks evidence consistency, not the honesty of a claimed build receipt.
The source-to-DCP production record and pin-role contract need prior review.
"""
import hashlib
import json
from pathlib import Path
import sys


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def verify(contract_path, binding_path, checkpoint_path):
    root = binding_path.resolve().parent

    def artifact(record):
        require(set(record) == {'path', 'sha256'}, 'malformed artifact record')
        relative = Path(record['path'])
        require(not relative.is_absolute() and '..' not in relative.parts,
                'artifact path must stay inside the fresh bundle')
        path = (root / relative).resolve()
        require(path.is_relative_to(root) and path.is_file(), 'missing/escaped artifact')
        require(sha(path) == record['sha256'], f'artifact hash mismatch: {relative}')
        return path

    b = read(binding_path)
    require(b['schema'] == 'fresh-mac-handoff-binding-v1', 'old/unknown binding schema')
    require(type(b['enabled']) is bool, 'mode must be Boolean')
    mode = b['enabled']
    require(artifact(b['contract']) == contract_path.resolve(), 'role contract substitution')
    require(artifact(b['checkpoint']) == checkpoint_path.resolve(), 'checkpoint substitution')
    manifests = {}
    for key in ('source_manifest', 'rtl_manifest', 'constraints_manifest'):
        manifest = read(artifact(b[key]))
        require(type(manifest) is dict and bool(manifest), f'empty {key}')
        for record in manifest.values():
            artifact(record)
        manifests[key] = manifest
    expected = read(Path(__file__).with_name('source_expected.json'))
    for logical, digest in expected.items():
        require(manifests['source_manifest'][logical]['sha256'] == digest,
                f'unreviewed source change: {logical}')
    p = read(artifact(b['parameters']))
    require(p['schema'] == 'mac-raw-handoff-export-parameters-v1', 'wrong parameter schema')
    require(type(p['triSpeedRawClockHandoff']) is bool and p['triSpeedRawClockHandoff'] == mode,
            'parameter mode mismatch')
    require(p['ingress_delay_cycles'] == 128 and p['profileFields'] == 89 and p['coreFields'] == 172,
            'wrong original128/platform/core shape')
    actual = read(artifact(b['actual_constructor']))
    require(actual['schema'] == 'actual-mac-raw-handoff-platform-v1' and
            actual['scope'] == 'actual-constructor-only', 'actual constructor evidence missing')
    for name, expected_value in (
            ('triSpeedRawClockHandoff', mode), ('actualHandoffPresent', mode),
            ('actualTriSpeedMac', True), ('mappedFfCountVerified', False),
            ('physicalQualification', False)):
        require(type(actual[name]) is bool and actual[name] == expected_value,
                f'actual constructor field mismatch: {name}')
    for name, expected_value in (
            ('profileFields', 89), ('coreFields', 172),
            ('expectedRawFallingScalarBits', 12 if mode else 0),
            ('expectedManagedRxScalarBits', 11 if mode else 0)):
        require(type(actual[name]) is int and actual[name] == expected_value,
                f'actual constructor shape mismatch: {name}')
    rtl = manifests['rtl_manifest']
    helpers = [record for record in rtl.values()
               if Path(record['path']).name == 'ValenceMacRawFallingSample.sv']
    require(len(helpers) == int(mode), 'default-OFF/helper resource mismatch')
    if mode:
        require(helpers[0]['sha256'] == expected['src/main/resources/ethernet/ValenceMacRawFallingSample.sv'],
                'emitted falling resource differs from reviewed source')
    filelist = artifact(b['synthesis_filelist']).read_text(encoding='utf-8').splitlines()
    require(len(filelist) == len(set(filelist)) and set(filelist) == {r['path'] for r in rtl.values()},
            'synthesis file list differs from exact emitted RTL closure')
    provenance = read(artifact(b['provenance']))
    require(provenance['schema'] == 'fresh-mac-handoff-build-v1' and
            provenance['review'] == 'REVIEWED_SOURCE_TO_DCP', 'fresh build provenance missing')
    require(provenance['stage'] in ('synth', 'postopt') and
            isinstance(provenance['build_id'], str) and bool(provenance['build_id']) and
            isinstance(provenance['invocation'], list) and bool(provenance['invocation']),
            'missing fresh invocation identity')
    require(type(provenance['enabled']) is bool and provenance['enabled'] == mode,
            'build mode mismatch')
    for key in ('source_manifest', 'rtl_manifest', 'constraints_manifest', 'parameters',
                'actual_constructor', 'checkpoint', 'synthesis_filelist'):
        require(provenance[key + '_sha256'] == b[key]['sha256'], f'build receipt mismatch: {key}')
    # All reports are evidence for this exact binding; never an old exact64 pass.
    return f'{sha(binding_path)} {int(mode)}'


if __name__ == '__main__':
    require(len(sys.argv) == 4, 'usage: verify_binding.py CONTRACT BINDING CHECKPOINT')
    print(verify(*(Path(arg) for arg in sys.argv[1:])))
