"""Source-only coherent PAD/RX adapter. No physical qualification is granted."""
import argparse
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BOARD = 'soc_top_fpga_next_ddr.sv'
SCHEMA = 'combined-network-source-candidate-v1'
BASE_BOARD_SHA256 = '5d40ba7a8b2a7b8ef2feced2d6c3db135470703170e58c5c12c2f7cc4b39556d'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sources():
    paths = [ROOT / 'fpga/next' / BOARD]
    paths += [p for p in (ROOT / 'fpga/zu15eg').rglob('*')
              if p.is_file() and p.suffix in ('.sv', '.tcl', '.xdc', '.py')]
    return {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in sorted(paths)}


def load_adapter(name):
    path = HERE.parent / name / 'export_board.py'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def merge_edits(base, variants):
    """Apply nonoverlapping line edits against ONE original, never sequential exports."""
    lines = base.splitlines(keepends=True)
    edits = []
    for variant in variants:
        changed = variant.splitlines(keepends=True)
        for tag, i, j, a, b in difflib.SequenceMatcher(None, lines, changed, autojunk=False).get_opcodes():
            if tag != 'equal':
                edits.append((i, j, changed[a:b]))
    edits.sort(key=lambda e: (e[0], e[1]))
    for previous, current in zip(edits, edits[1:]):
        if current[0] < previous[1] or current[0] == previous[0]:
            raise ValueError('Overlapping adapter edits; explicit integration required')
    result = list(lines)
    for i, j, replacement in reversed(edits):
        result[i:j] = replacement
    return b''.join(result)


def ports(data):
    # Exact pinned ANSI declaration region, excluding the two parameter defaults.
    if data.count(b')(\n') != 1:
        raise ValueError('Unsupported board module header')
    return data.split(b')(\n', 1)[1].split(b'\n);', 1)[0]


def build(pad=False, rx=False, serializer_profile=None):
    if type(pad) is not bool or type(rx) is not bool:
        raise ValueError('Mode flags must be booleans')
    if serializer_profile != ('t1-selected' if pad else None):
        raise ValueError('PAD requires explicit t1-selected; non-PAD takes no profile')
    baseline = (ROOT / 'fpga/next' / BOARD).read_bytes()
    if digest(baseline) != BASE_BOARD_SHA256:
        raise ValueError('Board source differs from reviewed 3554932 baseline')
    result = {}
    variants = []
    with tempfile.TemporaryDirectory() as temp:
        for name, enabled in [('pad_reset_candidate', pad), ('rx_capture_candidate', rx)]:
            if not enabled:
                continue
            output = Path(temp) / name
            adapter = load_adapter(name)
            if name == 'pad_reset_candidate':
                adapter.export(output, True, serializer_profile)
            else:
                adapter.export(output, True)
            variants.append((output / BOARD).read_bytes())
            for path in output.glob('*.sv'):
                if path.name != BOARD:
                    if path.name in result:
                        raise ValueError('Duplicate module output')
                    result[path.name] = path.read_bytes()
    result[BOARD] = merge_edits(baseline, variants)
    if ports(baseline) != ports(result[BOARD]):
        raise ValueError('External port declaration changed')
    return result


def contract(pad, rx, profile, inputs, outputs):
    return dict(schema=SCHEMA, padDomainReset=pad, rxCaptureSibling=rx,
                serializerProfile=profile, defaultOff=True, sourceSha256=inputs,
                outputSha256={name: digest(data) for name, data in sorted(outputs.items())},
                externalPortsSha256=digest(ports(outputs[BOARD])),
                physicalQualification=False, completeNativeExport=False,
                constraints=dict(owner='future combined physical integration',
                    unchangedSourceFiles=[name for name in inputs if name.endswith(('.xdc', '.tcl'))],
                    applied=False, legacyTopologyAuditCompatible=not (pad or rx),
                    required=['fresh source-bound clock/pin ownership audit',
                              'related RX clocks; no asynchronous groups or false paths',
                              'both edges, all pins, all three rates setup and hold',
                              'PAD reset recovery/removal and vendor route legality']),
                remainingGates=['physical timing and vendor primitive qualification',
                                'separate IDELAY readiness-loss integration',
                                'fresh full native inventory and combined mode audit'])


def export(out, pad=False, rx=False, serializer_profile=None):
    before = sources()
    outputs = build(pad, rx, serializer_profile)
    if sources() != before:
        raise ValueError('Source changed during export')
    record = contract(pad, rx, serializer_profile, before, outputs)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    for name, data in outputs.items():
        (out / name).write_bytes(data)
    (out / 'source-candidate.json').write_text(json.dumps(record, indent=2) + '\n')
    audit(out)
    return record


def audit(out):
    out = Path(out)
    record = json.loads((out / 'source-candidate.json').read_text())
    before = sources()
    outputs = build(record['padDomainReset'], record['rxCaptureSibling'], record['serializerProfile'])
    expected = contract(record['padDomainReset'], record['rxCaptureSibling'],
                        record['serializerProfile'], before, outputs)
    if record != expected:
        raise ValueError('Source, mode, ownership, or receipt mismatch')
    if {p.name for p in out.iterdir()} != set(outputs) | {'source-candidate.json'}:
        raise ValueError('Missing or extra output')
    for name, data in outputs.items():
        path = out / name
        if path.is_symlink() or path.read_bytes() != data:
            raise ValueError('Output mismatch: ' + name)
    if sources() != before:
        raise ValueError('Source changed during audit')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--enable-pad-domain-reset', action='store_true')
    parser.add_argument('--enable-rx-capture-sibling', action='store_true')
    parser.add_argument('--serializer-profile', choices=['t1-selected'])
    parser.add_argument('--audit', action='store_true')
    args = parser.parse_args()
    if args.audit and (args.enable_pad_domain_reset or args.enable_rx_capture_sibling or args.serializer_profile):
        parser.error('Audit mode reads sealed flags; do not supply export flags')
    print(json.dumps(audit(args.output) if args.audit else export(args.output,
        args.enable_pad_domain_reset, args.enable_rx_capture_sibling, args.serializer_profile), indent=2))
