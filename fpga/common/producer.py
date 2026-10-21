#!/usr/bin/env python3
"""Small producer contract/receipt helper; does not invent generated RTL or PASS evidence."""
import argparse
import json
import re
from pathlib import Path
import sys
import manifest as gate
import board_inputs


def validate(root, m):
    p = m.get('producer')
    gate.require(isinstance(p, dict) and p.get('schema') == 'common-board-producer-v1',
                 'actual common-board producer configuration required')
    for name in board_inputs.PUBLIC_INPUTS:
        gate.require(name in m['inputs'], 'unfrozen public board dependency: ' + name)
    board_inputs.emission(root, m)
    c = m['configuration']; hz = c['clocks_hz']; roles = m['roles']
    gate.require(c['top'] == 'soc_top_common_ddr' and c['features'] == {'mac': True, 'network_dma': True},
                 'board producer requires shared full-MAC/DMA board wrapper')
    gate.require(hz == gate.reviewed_board_clocks(c['cpu'], c.get('clock_profile', 'production')),
                 'unreviewed board clock profile')
    for name in ('simulation_filelist', 'post_synth_constraints', 'post_opt_constraints', 'media_scenarios', 'rom_coe'):
        gate.require(roles.get(name) in m['inputs'], 'missing reviewed producer role: ' + name)
    gate.require(len(roles['ip']) == 1 and roles['ip'][0].endswith('.xci'), 'supply exactly one actual MIG XCI')
    gate.require(p.get('simulation_suite') == 'common-physical-boundaries-v1', 'reviewed BSCAN65/tri-speed boundary suite required')
    gate.require(p.get('media_rates_mbps') == [10, 100, 1000], 'all three physical media scenarios required')
    for role in ('rtl_filelist', 'simulation_filelist'):
        paths = gate.file_at(root, roles[role]).read_text().splitlines()
        gate.require(paths and len(paths) == len(set(paths)), 'empty/duplicate filelist: ' + role)
        expected = board_inputs.BOARD_RTL if role == 'rtl_filelist' else board_inputs.SIM_RTL
        gate.require(set(expected).issubset(paths), 'missing real board/simulation dependency in ' + role)
        for path in paths:
            gate.require(path in m['inputs'] and path.endswith(('.v', '.sv')), 'unfrozen producer RTL: ' + path)
    rom = gate.file_at(root, roles['rom']).read_bytes()
    coe = gate.file_at(root, roles['rom_coe']).read_text()
    match = re.fullmatch(r'\s*memory_initialization_radix\s*=\s*16\s*;\s*memory_initialization_vector\s*=\s*([0-9a-fA-F,\s]+);\s*', coe, re.I)
    gate.require(match is not None, 'unrecognized ROM COE format')
    words = [w.strip() for w in match[1].split(',')]
    gate.require(len(rom) == 131072 and len(words) == 32768 and all(re.fullmatch('[0-9a-fA-F]{8}', w) for w in words), 'ROM/COE must be exactly 128 KiB')
    gate.require(b''.join(int(w, 16).to_bytes(4, 'little') for w in words) == rom, 'ROM binary and COE content mismatch')
    return p


def receipt(manifest, phase, records):
    root, m, profile = gate.preflight(manifest)
    validate(root, m)
    out = root / 'local-run' / phase
    tools = gate.read(records)
    for record in tools.values():
        record['evidence']['sha256'] = gate.sha(gate.file_at(out, record['evidence']['path']))
    result = dict(status='PASS', phase=phase, profile_sha256=profile, tools=tools,
                  outputs_sha256={name: gate.sha(gate.file_at(out, name)) for name in m['stages'][phase]['outputs']})
    (out / 'stage-receipt.json').write_text(json.dumps(result, indent=2) + '\n')
    gate.check_stage(root, m, profile, phase, out)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', required=True, type=Path)
    p.add_argument('--phase', required=True, choices=gate.STAGES)
    p.add_argument('--records', required=True, type=Path)
    a = p.parse_args()
    try:
        receipt(a.manifest, a.phase, a.records)
    except (ValueError, OSError, KeyError, TypeError) as e:
        print('COMMON_PRODUCER_BLOCKED: ' + str(e), file=sys.stderr)
        sys.exit(1)
