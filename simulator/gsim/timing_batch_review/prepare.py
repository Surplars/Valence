#!/usr/bin/env python3
"""Prepare a historical timing-batch source checkout; never build hardware.

Default: verify portable inputs and print a plan. --execute creates a new local
checkout. The repository supplied by the caller remains read-only. A committed
review overlay is not itself the historical qualified source tree.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repository, *args):
    return subprocess.check_output(
        ['git', '--no-optional-locks', '-c', 'core.hooksPath=/dev/null', '-C', str(repository), *args],
        text=True, stderr=subprocess.PIPE
    ).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--repository', required=True, type=Path, help='clean local repository containing pinned base')
    parser.add_argument('--destination', required=True, type=Path, help='new checkout path outside the input repository')
    parser.add_argument('--variant', choices=('baseline', 'r2'), default='r2')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    manifest = json.loads((HERE / 'source.json').read_text())
    patch = HERE / 'combined-source-r2.patch'
    assert sha(patch) == manifest['patch_sha256'], 'complete frozen patch hash mismatch'
    assert args.repository.is_dir(), 'repository must be an existing local directory'
    repository = args.repository.resolve()
    repository = Path(git(repository, 'rev-parse', '--show-toplevel')).resolve()
    assert not git(repository, 'status', '--porcelain', '--untracked-files=normal'), 'input repository is dirty'
    base = manifest['base_commit']
    assert git(repository, 'rev-parse', base + '^{commit}') == base, 'pinned base absent'
    assert git(repository, 'rev-parse', base + '^{tree}') == manifest['base_tree'], 'base tree mismatch'
    destination = args.destination.absolute()
    assert not destination.exists() and not destination.is_symlink(), 'destination must not exist'
    destination = destination.resolve()
    assert not destination.is_relative_to(repository), 'destination must be outside input repository'
    assert destination.parent.is_dir(), 'destination parent must already exist'
    # Also refuse to create generated files in the checkout that carries this overlay.
    try:
        carrier = Path(git(HERE, 'rev-parse', '--show-toplevel')).resolve()
    except subprocess.CalledProcessError:
        carrier = None
    assert carrier is None or not destination.is_relative_to(carrier), 'destination must be outside overlay checkout'
    tree = manifest['source_tree'] if args.variant == 'r2' else manifest['base_tree']
    plan = {'schema': 'timing-batch-source-replay-v1', 'status': 'PLAN_ONLY',
            'repository': str(repository), 'destination': str(destination),
            'variant': args.variant, 'base_commit': base, 'expected_tree': tree,
            'patch_sha256': manifest['patch_sha256'] if args.variant == 'r2' else None,
            'hardware_commands_run': False,
            'scope': 'Historical source reconstruction only; no clean-checkout runtime qualification claim.'}
    if args.execute:
        subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', 'clone', '--no-hardlinks',
                        '--no-checkout', '--', str(repository), str(destination)], check=True)
        git(destination, 'checkout', '--detach', base)
        if args.variant == 'r2':
            git(destination, 'apply', '--check', str(patch))
            git(destination, 'apply', '--index', str(patch))
            for name, digest in manifest['changed_source_files'].items():
                assert sha(destination / name) == digest, 'replayed source mismatch: ' + name
        assert git(destination, 'write-tree') == tree, 'complete replayed tree mismatch'
        assert not git(destination, 'diff', '--name-only'), 'unexpected unstaged replay changes'
        assert git(destination, 'rev-parse', 'HEAD') == base, 'historical HEAD differs'
        plan['status'] = 'SOURCE_REPLAY_VERIFIED'
        # Preserve failed checkouts on exceptions; successful receipt lives outside tracked source.
        receipt = destination / '.git' / 'timing-batch-source-replay.json'
        receipt.write_text(json.dumps(plan, indent=2) + '\n')
    print(json.dumps(plan, indent=2))


if __name__ == '__main__':
    main()
