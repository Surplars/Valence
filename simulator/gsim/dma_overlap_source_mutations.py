#!/usr/bin/env python3
"""Rebuild isolated, source-mutated DMA RTL and require explicit checked rejection.

Uses the existing GSIM tool cache only. Never edits the working DUT or runs CAD.
Source mutations are deliberately broken designs, not selectable production flags.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
MUTATIONS = {
    'destination-order': (
        'src/main/scala/ip/dma/MemoryCopyDma.scala',
        'destination + (offsets(selectedSlot) << 3), nextSource)',
        'destination + (writesSent << 3), nextSource)',
        '--smoke', 'DMA independent destination byte oracle mismatch'),
    'reply-tag-swap': (
        'src/main/scala/core/ooo/MixedCoherentLineHome.scala',
        'line.response.bits.tag := Mux(chooseWrite, writeTag, readTag)',
        'line.response.bits.tag := Mux(chooseWrite, writeTag, readTag) ^ 1.U',
        '--smoke', 'protocol line read independent byte oracle mismatch'),
    'skip-line-hazard': (
        'src/main/scala/core/ooo/MixedCoherentLineHome.scala',
        'maintenance === mLineHazard && !olderSameLine && !releaseBusy && !releaseOffer',
        'maintenance === mLineHazard && !releaseBusy && !releaseOffer',
        '--protocol-only', 'younger same-address transport crossed retained owner'),
    'truncate-write-tag': (
        'src/main/scala/core/ooo/MixedCoherentLineHome.scala',
        '(writebackEntries + 1).U(writeTagBits.W) + accessTag',
        '(writebackEntries + 1).U + accessTag',
        '--smoke', 'DMA write tag overlaps release/probe tag class'),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_worker(name):
    import run as common
    _, _, _, runtime_arg, expected = MUTATIONS[name]
    out = common.BUILD / 'source-mutation'
    sources = sorted((ROOT / 'src/main/scala').rglob('*.scala')) + [
        ROOT / 'src/test/scala/ooo/DmaPipelineGsim.scala',
        ROOT / 'simulator/gsim/harness/dma_overlap.cpp',
        ROOT / 'simulator/gsim/harness/dma_pipeline_ddr.h',
        ROOT / 'simulator/gsim/harness/dma_overlap_metrics.h',Path(__file__),ROOT / 'simulator/gsim/run.py']
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    gsim, cxx = common.setup(False)
    try:
        common.test(gsim, cxx, 'source-mutation', 'ooo.DmaPipelineGsimMain',
                    'DmaPipelineGsim', 'dma_overlap.cpp', parameters=(0,2),
                    defines={'DMA_LINE_ENABLED': 1,'DMA_LINE_ENTRIES':2},
                    runtime_args=tuple([runtime_arg] if runtime_arg else []), timeout=1200)
    except RuntimeError:
        log = (out / 'test.log').read_text() if (out / 'test.log').exists() else ''
        if expected not in log:
            raise
    else:
        raise RuntimeError('Source mutation escaped the independent oracle')
    if hashes != {str(p.relative_to(ROOT)): digest(p) for p in sources}:
        raise RuntimeError('Mutation inputs drifted during build/run')
    result = {'status': 'PASS_REJECTED', 'mutation': name, 'expected_rejection': expected,
              'detector': 'DUT ownership assertion' if name == 'truncate-write-tag' else 'independent host oracle',
              'source_sha256': hashes, 'runtime_arg': runtime_arg,
              'artifacts_sha256': {str(p.relative_to(out)): digest(p)
                 for p in out.rglob('*') if p.is_file() and p.name != 'mutation-result.json'}}
    (out / 'mutation-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('SOURCE_MUTATION_REJECTED ' + expected)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path)
    ap.add_argument('--worker', choices=MUTATIONS)
    ap.add_argument('--mutations', nargs='+', choices=MUTATIONS, default=list(MUTATIONS))
    a = ap.parse_args()
    if a.worker:
        run_worker(a.worker)
        return
    if not a.output:
        ap.error('--output is required')
    output = a.output.resolve()
    if output.exists():
        ap.error('Choose a new output directory; old evidence is never overwritten')
    output.mkdir(parents=True)
    archive = subprocess.check_output(['git', 'archive', 'HEAD'], cwd=ROOT)
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    untracked = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
    # Overlay the complete current source, including uncommitted/new test files.
    # Generated/ignored build trees and other independent workspaces are omitted.
    source_files = [p for p in set(tracked + untracked) if p and (ROOT / p).is_file()]
    inventory = {p: digest(ROOT / p) for p in sorted(source_files)}
    manifest = {'source_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'source_sha256': inventory, 'mutations': {}}
    for name in a.mutations:
        path, old, new, runtime_arg, expected = MUTATIONS[name]
        work = output / name
        work.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as archive_file:
            archive_file.extractall(work, filter='data')
        for relative in source_files:
            destination = work / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((ROOT / relative).read_bytes())
        source = work / path
        text = source.read_text()
        if text.count(old) != 1:
            raise RuntimeError('Mutation anchor changed; re-review ' + name)
        source.write_text(text.replace(old, new))
        command = [sys.executable, '-B', 'simulator/gsim/dma_overlap_source_mutations.py', '--worker', name]
        with (output / (name + '.log')).open('w') as log:
            subprocess.run(command, cwd=work, env=os.environ.copy(), stdout=log,
                           stderr=subprocess.STDOUT, check=True, timeout=1800)
        manifest['mutations'][name] = {'source': path, 'before': inventory[path], 'after': digest(source),
            'expected_rejection': expected, 'runtime_arg': runtime_arg,
            'result_sha256': digest(work / 'build/gsim/source-mutation/mutation-result.json')}
        (output / 'mutations.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('PASS_SOURCE_MUTATIONS ' + str(output / 'mutations.json'))


if __name__ == '__main__':
    main()
