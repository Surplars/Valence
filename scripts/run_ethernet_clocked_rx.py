#!/usr/bin/env python3
"""Network-only Icarus exception: exact clocked MAC/CDC/DMA fixture; CPU stays GSIM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cases():
    smoke = [(60, 1, 0, 0, 0), (67, 16, 1, 1000, 0),
             (1514, 4, 0, 1700, 0), (1511, 64, 2, 4500, 1),
             (61, 16, 1, 1000, 0), (62, 16, 1, 1000, 0), (65, 64, 2, 1000, 0)]
    negative = [(1, 'independent byte oracle mismatch'),
                (2, 'completion before all write acknowledgements'),
                (3, 'duplicate generation or failed completion'),
                (4, 'Assertion failed at GmiiFrameRx.scala:52')]
    for mac, dma in [(0, 0), (0, 1), (1, 0), (1, 1)]:
        for length, latency, law, phase, reset in smoke:
            yield mac, dma, f'smoke-{length}-{latency}-{law}-{phase}-{reset}', {
                'length': length, 'frames': 32, 'latency': latency,
                'law': law, 'phase': phase, 'resetcase': reset}, None
        for mutation, anchor in negative:
            yield mac, dma, f'negative-{mutation}', {
                'length': 60, 'frames': 16, 'mutation': mutation}, anchor
    # Every positive/negative short check precedes the 4096-frame matrix.
    for mac, dma in [(0, 0), (0, 1), (1, 0), (1, 1)]:
        for length in [60, 1514]:
            for latency, law in [(1, 0), (64, 2)]:
                yield mac, dma, f'primary-{length}-{latency}-{law}', {
                    'length': length, 'frames': 4096, 'latency': latency,
                    'law': law, 'phase': 1700}, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True, help='New, non-existing output directory')
    for name in ['mill', 'firtool', 'iverilog', 'vvp']:
        parser.add_argument('--' + name, default=os.environ.get(name.upper()),
                            help=f'Existing executable path, or {name.upper()} environment variable')
    parser.add_argument('--manifest', type=Path, default=Path(__file__).with_name('ethernet_clocked_rx_sources.json'))
    parser.add_argument('--min-free-mib', type=int, default=800)
    parser.add_argument('--timeout-seconds', type=int, default=3600)
    parser.add_argument('--dry-run', action='store_true', help='Print exact plan; do not inspect tools, build, or simulate')
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.out.resolve()
    tools = {name: getattr(args, name) or f'<{name.upper()}>' for name in ['mill', 'firtool', 'iverilog', 'vvp']}
    tb = repo / 'simulator/gsim/harness/ethernet_clocked_rx_tb.sv'
    plan = []
    for mac, dma in [(0, 0), (0, 1), (1, 0), (1, 1)]:
        model = out / f'mac{mac}-dma{dma}'
        plan.extend([
            {'kind': 'emit', 'cwd': str(repo), 'directory': str(model), 'command': [tools['mill'], '-i', 'IonSoC.test.runMain', 'ip.EthernetClockedRxMain', str(model), str(mac), str(dma)]},
            {'kind': 'firtool', 'cwd': str(model), 'directory': str(model), 'command': [tools['firtool'], str(model / 'EthernetClockedRx.fir'), '--format=fir', '--verilog', '--disable-all-randomization', '--lowering-options=disallowLocalVariables', '--default-layer-specialization=enable', '-o', str(model / 'dut.sv')]},
            {'kind': 'iverilog', 'cwd': str(model), 'directory': str(model), 'command': [tools['iverilog'], '-g2012', '-s', 'tb', '-o', str(model / 'run'), str(model / 'dut.sv'), str(tb)]}])
    for mac, dma, name, params, anchor in cases():
        model = out / f'mac{mac}-dma{dma}'
        directory = model / name
        plan.append({'kind': 'case', 'cwd': str(directory), 'directory': str(directory),
                     'mac': mac, 'dma': dma, 'name': name, 'parameters': params,
                     'expected_failure': anchor, 'command': [tools['vvp'], str(model / 'run')] + [f'+{k}={v}' for k, v in params.items()]})
    if args.dry_run:
        print(json.dumps({'source_manifest': str(args.manifest), 'build_commands': 12,
                          'positive_smoke': 28, 'negative_controls': 16, 'primary_4096': 16,
                          'commands': plan}, indent=2))
        return
    if args.timeout_seconds <= 0 or args.min_free_mib < 0:
        parser.error('timeout must be positive and free-space floor nonnegative')
    if out.exists():
        parser.error('Output directory already exists; refuse to overwrite or duplicate a run')
    for name, executable in tools.items():
        found = shutil.which(executable)
        if found is None:
            parser.error(f'Supply an existing {name.upper()} executable; this runner installs nothing')
        tools[name] = str(Path(found).resolve())
    # Rebind plan executables to the verified absolute paths.
    for row in plan:
        row['command'][0] = tools['vvp' if row['kind'] == 'case' else 'mill' if row['kind'] == 'emit' else row['kind']]
    manifest = json.loads(args.manifest.read_text())

    def validate_sources():
        for relative, expected in manifest['source_sha256'].items():
            path = repo / relative
            if digest(path) != expected:
                raise RuntimeError(f'Frozen source hash mismatch: {relative}; requalification required')

    def guard():
        ancestor = out
        while not ancestor.exists():
            ancestor = ancestor.parent
        if shutil.disk_usage(ancestor).free < args.min_free_mib * 1024**2:
            raise RuntimeError('Free disk below requested floor; no new stage started')

    def run(row):
        guard()
        directory = Path(row['directory'])
        directory.mkdir(parents=True, exist_ok=True)
        label = 'test' if row['kind'] == 'case' else row['kind']
        (directory / (label + '.command.json')).write_text(json.dumps(row, indent=2) + '\n')
        start = time.monotonic()
        with (directory / (label + '.log')).open('w') as log:
            process = subprocess.Popen(row['command'], cwd=row['cwd'], stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = process.wait(timeout=args.timeout_seconds)
            except BaseException:
                # Own process group only: also stop a timed-out Mill/Java child.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise
        text = (directory / (label + '.log')).read_text()
        expected = row.get('expected_failure')
        if expected:
            if code == 0 or expected not in text:
                raise RuntimeError(f'Negative control did not fail at expected anchor: {directory}')
        elif code != 0 or (row['kind'] == 'case' and 'CLOCKED_RX_PASS ' not in text):
            raise RuntimeError(f'Stage failed or incomplete: {directory}/{label}.log')
        return {'stage': row, 'seconds': time.monotonic() - start, 'returncode': code,
                'log_sha256': digest(directory / (label + '.log'))}

    validate_sources()
    guard()
    out.mkdir(parents=True)
    (out / 'source-binding.json').write_text(json.dumps({'manifest': manifest,
        'tool_sha256': {name: digest(Path(path)) for name, path in tools.items()},
        'runner_sha256': digest(Path(__file__)), 'scope': __doc__}, indent=2) + '\n')
    results = []
    for row in plan:
        results.append(run(row))
        if row['kind'] == 'firtool':
            sv = (Path(row['directory']) / 'dut.sv').read_text()
            match = re.search(r'mac([01])-dma([01])$', row['directory'])
            expected = 9 + 3 * int(match[1]) + 5 * int(match[2])
            if sv.count('$fatal;') != expected or '  bind ' in sv or 'automatic logic' in sv:
                raise RuntimeError('Inlined production-assertion/emission contract changed')
        (out / 'progress.json').write_text(json.dumps(results, indent=2) + '\n')
    validate_sources()
    artifacts = {str(p.relative_to(out)): digest(p) for p in out.rglob('*') if p.is_file()}
    (out / 'receipt.json').write_text(json.dumps({'status': 'PASS', 'positive_smoke': 28,
        'negative_controls': 16, 'primary_4096': 16, 'results': results,
        'artifact_sha256': artifacts}, indent=2) + '\n')
    print(f'PASS: 28 short checks, 16 expected negative failures, 16 complete 4096-frame cases. {out}')


if __name__ == '__main__':
    main()
