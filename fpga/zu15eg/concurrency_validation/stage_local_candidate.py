#!/usr/bin/env python3
"""Stage verified RTL and existing IP/ROM inside a fresh build directory; no Vivado."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from verify_dev_sources import verify_dev_sources
from verify_local_inputs import verify


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_file(root, name, digest):
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts:
        raise RuntimeError('unsafe manifest path: ' + name)
    path = root / relative
    linked = any(root.joinpath(*relative.parts[:i]).is_symlink() for i in range(1, len(relative.parts) + 1))
    if linked or not path.is_file() or sha(path) != digest:
        raise RuntimeError('input identity mismatch: ' + name)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--existing', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rtl', type=Path, required=True)
    parser.add_argument('--variant', choices=('baseline', 'resource', 'integrated-off', 'integrated-on'), required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--route-reference', type=Path)
    args = parser.parse_args()
    helpers = Path(__file__).resolve().parent
    repo, existing, rtl, output = (p.resolve() for p in (args.repo, args.existing, args.rtl, args.output))
    if output.exists() or output.is_relative_to(existing) or output.is_relative_to(rtl) or output.is_relative_to(helpers):
        raise RuntimeError('choose a fresh build output outside input/RTL/helper roots')
    # Even historical RTL is assembled with exactly identified current board scripts.
    binding = verify_dev_sources(repo, args.commit, helpers / 'integrated-source-sha256.json')
    contract = json.loads((helpers / 'EXPORT-RECEIPT.json').read_text())
    expected = json.loads((helpers / 'expected-local-inputs.json').read_text())
    evidence = verify(existing, expected)
    if evidence['failures']:
        print(json.dumps(evidence, indent=2))
        raise RuntimeError('immutable IP/ROM mismatch; staging blocked')
    variant = contract['variants'][args.variant]
    actual = {p.name for p in rtl.glob('*.sv')}
    if actual != set(variant['rtl_sha256']):
        raise RuntimeError('native RTL inventory differs from selected variant')
    for name, digest in variant['rtl_sha256'].items():
        checked_file(rtl, name, digest)
    sources = {}
    for target, entry in contract['source_map'].items():
        source = checked_file(repo, entry['repo_path'], entry['sha256'])
        blob = subprocess.check_output(['git', '-C', str(repo), 'show', args.commit + ':' + entry['repo_path']])
        if hashlib.sha256(blob).hexdigest() != entry['sha256']:
            raise RuntimeError('committed board/script source differs: ' + entry['repo_path'])
        sources[target] = source
    if args.route_reference and sha(args.route_reference) != expected['route_hint_only']['sha256']:
        raise RuntimeError('optional old route-reference hash mismatch')
    output.mkdir(parents=True)
    for name, digest in expected['sha256'].items():
        source = checked_file(existing, name, digest)
        target = output / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if sha(target) != digest: raise RuntimeError('copy verification failed: ' + name)
    for name, source in sources.items():
        target = output / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if sha(target) != sha(source): raise RuntimeError('source copy failed: ' + name)
    (output / 'rtl').mkdir()
    for name, digest in variant['rtl_sha256'].items():
        shutil.copy2(rtl / name, output / 'rtl' / name)
        checked_file(output / 'rtl', name, digest)
    state = {'status': 'STAGED_VERIFIED_INPUTS_NOT_IMPLEMENTED', 'variant': args.variant,
             'cpu_precheck': variant['cpu_precheck'], 'source_binding': binding,
             'rtl_matches_final_dev': args.variant.startswith('integrated-'),
             'local_verification': evidence, 'bitstream_generated': False,
             'optional_old_route_hint': str(args.route_reference) if args.route_reference else None,
             'candidate_sha256': {p.relative_to(output).as_posix(): sha(p) for p in sorted(output.rglob('*')) if p.is_file()}}
    (output / 'staged-inputs.json').write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps({'status': state['status'], 'variant': args.variant, 'output': str(output)}, indent=2))


if __name__ == '__main__':
    main()
