#!/usr/bin/env python3
"""Regenerate only the fixed original image and single corrected image."""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
sys.dont_write_bytecode = True
from directed_inputs import make_image, scenarios
HERE = Path(__file__).resolve().parent

def generated_guests():
    provenance = json.loads((HERE/'provenance.json').read_text())
    _, original = make_image()
    assert len(original) == provenance['guest_bytes']
    assert hashlib.sha256(original).hexdigest() == provenance['guest_sha256']
    corrected = bytearray(original)
    for pc, expected in [(0x8020006c, 7), (0x80200070, 8)]:
        offset = pc - 0x80200000
        word = int.from_bytes(corrected[offset:offset+4], 'little')
        assert (word >> 15) & 31 == expected and word & 0x707f == 0x13
        corrected[offset:offset+4] = ((word & ~(31 << 15)) | (2 << 15)).to_bytes(4, 'little')
    assert hashlib.sha256(corrected).hexdigest() == provenance['corrected_guest_sha256']
    return {'original.bin': original, 'corrected.bin': bytes(corrected)}

def generated_controls():
    manifest = json.loads((HERE/'inputs-manifest.json').read_text())
    image, _ = make_image()
    symbols = (json.dumps(image.labels, indent=2, sort_keys=True)+'\n').encode()
    assert hashlib.sha256(symbols).hexdigest() == manifest['symbols_sha256']
    selected = manifest['selected_original_cases']
    controls = {}
    for case in scenarios(image):
        if case['name'] not in selected: continue
        terminal, law = case['expected_terminal'], case['service']
        lines = [f'name {case["name"]}', f'family {case["family"]}', f'mode {case["mode"]}', f'phase {case["phase"]}', f'entry {case["entry"]:#x}', f'terminal {terminal["pc"]:#x}',
                 f'signature {terminal["signature_address"]:#x} {terminal["signature"]:#x}', f'sentinel {terminal["sentinel_address"]:#x} {terminal["sentinel"]:#x}', f'faults {terminal["fault_count_before_terminal_ecall"]}']
        if case['fault']:
            f = case['fault']
            lines.append(f'fault {f["pc"]:#x} {f["cause"]} {f["tval"]:#x} {f["resume"]:#x}')
        if law['delayed_line'] is not None: lines.append(f'delay {law["delayed_line"]:#x} {law["delayed_line_min_latency"]}')
        if law['error_line'] is not None: lines.append(f'error {law["error_line"]:#x}')
        lines += [f'seed {int(address,16):#x} {value:#x}' for address, value in sorted(case['initial_memory'].items(), key=lambda item: int(item[0],16))]
        lines += [f'role {role} {pc:#x}' for role, pc in sorted(case['roles'].items())]
        controls[case['name']] = ('\n'.join(lines)+'\n').encode()
    original = controls['D1-bare-p0'].decode()
    assert original.count('seed 0x80400000 0x10203040\n') == 1
    controls['D1-bare-p0-x2-gated'] = original.replace('name D1-bare-p0\n', 'name D1-bare-p0-x2-gated\n').replace('seed 0x80400000 0x10203040\n', 'seed 0x80400000 0x80400000\n').encode()
    assert set(controls) == set(manifest['inputs'])
    for name, data in controls.items():
        assert len(data) == manifest['inputs'][name]['bytes']
        assert hashlib.sha256(data).hexdigest() == manifest['inputs'][name]['sha256'], name
    return controls

def main():
    if sys.flags.optimize: raise SystemExit('Python assertions must remain enabled')
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', required=True, type=Path)
    out = p.parse_args().out.resolve()
    if out.is_relative_to(HERE): raise SystemExit('Runtime products must be outside the fixture source tree')
    guests, controls = generated_guests(), generated_controls()
    out.mkdir(parents=True, exist_ok=False)
    for name, data in guests.items(): (out/name).write_bytes(data)
    for name, data in controls.items(): (out/(name+'.txt')).write_bytes(data)
    print(json.dumps({'status': 'FIXED_GUESTS_REGENERATED_NO_MODEL_EXECUTION', 'sha256': {n: hashlib.sha256(b).hexdigest() for n, b in guests.items()}}))

if __name__ == '__main__': main()
