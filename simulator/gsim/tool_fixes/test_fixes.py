#!/usr/bin/env python3
"""Small GSIM emitter regressions; uses a separately built candidate compiler."""
import argparse
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gsim', type=Path, required=True)
    parser.add_argument('--cxx', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    fixtures = Path(__file__).resolve().parent / 'fixtures'
    gsim = args.gsim.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    # LeakSanitizer is unavailable under ptrace in the recovery executor.
    # Caller can supply ASAN_OPTIONS to enable it on an unrestricted host.
    env.setdefault('ASAN_OPTIONS', 'detect_leaks=0')

    def run(command, log):
        with log.open('w') as stream:
            subprocess.run([str(arg) for arg in command], stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=120, env=env)

    for fixture in ('RecoveryInit', 'RecoveryVec', 'RecoverySignedWideVec'):
        model = output / fixture
        model.mkdir(exist_ok=True)
        # Fail rather than accidentally compile stale translation units.
        if list(model.glob('*.cpp')):
            raise SystemExit(f'Use a fresh output directory: {model}')
        run([gsim, '--threads=1', f'--dir={model}', fixtures / f'{fixture}.fir'],
            model / 'generate.log')
        if fixture == 'RecoveryInit':
            assert 'uint8_t narrow; // width = 8,' in (model / f'{fixture}.h').read_text()
        sources = sorted(model.glob('*.cpp'))
        assert sources, 'GSIM produced no translation units'
        for mode in ('normal', 'random'):
            defines = ['-DRANDOMIZE_INIT'] if mode == 'random' else []
            executable = model / f'{mode}-test'
            run([args.cxx, '-std=c++17', '-O1', '-g', '-fsanitize=address,undefined',
                 '-fno-sanitize-recover=all', *defines, f'-I{model}', *sources,
                 fixtures / f'{fixture}.cpp', '-o', executable], model / f'{mode}-compile.log')
            run([executable], model / f'{mode}-run.log')
            print(f'{fixture} {mode} PASS', flush=True)


if __name__ == '__main__':
    main()
