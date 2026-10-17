#!/usr/bin/env python3
"""Build one focused Ethernet RX GSIM model with explicitly supplied, existing tools.

No setup/install is performed. --dry-run prints the plan without generating files.
Run the resulting executable with the documented host arguments.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

PINNED_GSIM = 'f00067c6158db342927ad0d746109ad745298fd4ebe9707fd951998069587116'

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kind', choices=('tier-a', 'home'), required=True)
    p.add_argument('--mac-prefetch', type=int, choices=(0, 1), default=0)
    p.add_argument('--dma-prefetch', type=int, choices=(0, 1), default=0)
    p.add_argument('--axis', type=int, choices=(0, 1), default=0)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--mill', default='mill')
    p.add_argument('--gsim', type=Path, required=True)
    p.add_argument('--cxx', required=True)
    p.add_argument('--jobs', type=int, choices=(1, 2), default=2)
    p.add_argument('--min-free-mib', type=int, default=800)
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    # Resolve explicit relative tool paths before switching to repository cwd.
    a.mill = str(Path(a.mill).resolve()) if '/' in a.mill else a.mill
    a.cxx = str(Path(a.cxx).resolve()) if '/' in a.cxx else a.cxx
    root = Path(__file__).resolve().parents[2]
    out = a.output.resolve()
    if a.kind == 'home' and a.axis:
        p.error('Home fixture has no AXIS bypass')
    model, entry, host = ('EthernetRxPrefetchGsim', 'ip.EthernetRxPrefetchGsimMain', 'ethernet_rx_prefetch.cpp') if a.kind == 'tier-a' else ('EthernetHomeRxGsim', 'ooo.EthernetHomeRxGsimMain', 'ethernet_home_rx.cpp')
    params = [str(a.mac_prefetch), str(a.dma_prefetch)] + ([str(a.axis)] if a.kind == 'tier-a' else [])
    emit = [a.mill, '-i', 'IonSoC.test.runMain', entry, str(out), *params]
    generate = [str(a.gsim.resolve()), '--threads=1', '--cpp-max-size-KB=1024', '--dir='+str(out), str(out/(model+'.fir'))]
    flags = ['-std=c++20', '-O1', '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I'+str(out), '-I'+str(root/'simulator/gsim/harness')]
    plan = {'kind': a.kind, 'emit': emit, 'generate': generate, 'compiler': a.cxx, 'flags': flags, 'host': str(root/'simulator/gsim/harness'/host), 'jobs': a.jobs, 'gsim_required_sha256': PINNED_GSIM}
    if a.dry_run:
        print(json.dumps(plan, indent=2)); return
    if out.exists() and any(out.iterdir()):
        p.error('output must be new or empty; preserve existing evidence')
    if hashlib.sha256(a.gsim.read_bytes()).hexdigest() != PINNED_GSIM:
        p.error('GSIM hash differs from the qualified repaired binary; do not silently substitute tools')
    out.mkdir(parents=True, exist_ok=True)
    def guard():
        if shutil.disk_usage(out).free < a.min_free_mib*1024**2:
            raise RuntimeError('free-space floor reached')
    def run(name, cmd):
        guard()
        (out/(name+'.command.json')).write_text(json.dumps(cmd, indent=2)+'\n')
        with (out/(name+'.log')).open('w') as f:
            subprocess.run(cmd, cwd=root, stdout=f, stderr=subprocess.STDOUT, check=True)
        guard()
    bound = sorted((root/'src/main/scala').rglob('*.scala')) + sorted((root/'src/test/scala').rglob('*Ethernet*Gsim.scala')) + [root/'simulator/gsim/harness'/host, root/'simulator/gsim/harness/gmii_reference.h', root/'simulator/gsim/harness/dma_coherent_ddr.h', Path(__file__).resolve()]
    hashes = lambda: {str(x.relative_to(root)): hashlib.sha256(x.read_bytes()).hexdigest() for x in bound}
    source_hashes = hashes()
    run('emit', emit); run('generate', generate)
    sources = sorted(out.glob(model+'[0-9]*.cpp')) + [root/'simulator/gsim/harness'/host]
    if len(sources) < 2:
        raise RuntimeError('GSIM emitted no model translation units')
    def compile_one(src):
        obj = out/(src.stem+'.o')
        run('compile-'+src.stem, [a.cxx, *flags, '-c', str(src), '-o', str(obj)])
        return str(obj)
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as pool:
        objects = list(pool.map(compile_one, sources))
    run('link', [a.cxx, *flags, *objects, '-ldl', '-o', str(out/'run')])
    if hashes() != source_hashes:
        raise RuntimeError('source changed during build')
    receipt = {'source_sha256': source_hashes, 'plan': plan, 'files': {x.name: hashlib.sha256(x.read_bytes()).hexdigest() for x in out.iterdir() if x.is_file()}, 'run_environment': {'ASAN_OPTIONS': 'detect_leaks=0'}}
    (out/'build-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(out/'run')

if __name__ == '__main__':
    main()
