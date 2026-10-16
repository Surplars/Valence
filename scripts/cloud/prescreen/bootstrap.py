#!/usr/bin/env python3
"""Restore pinned, isolated Yosys/sv2v/RapidWright tools. Never invokes Vivado."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LOCK = json.loads((HERE / 'downloads.lock.json').read_text())


def run(args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def java_bin(name):
    if os.environ.get('JAVA_HOME'):
        candidate = Path(os.environ['JAVA_HOME']) / 'bin' / name
        if candidate.is_file():
            return candidate
    if shutil.which(name):
        return Path(shutil.which(name))
    cached = sorted((ROOT / 'simulator/build/cloud-env/cache/coursier/arc').glob('**/bin/' + name))
    if cached:
        return cached[-1]
    raise RuntimeError(f'{name} unavailable; restore scripts/cloud/bootstrap.py first or set JAVA_HOME')


def restore(out, smoke):
    downloads = out / 'downloads'
    downloads.mkdir(parents=True, exist_ok=True)
    for name, spec in LOCK['artifacts'].items():
        target = downloads / name
        if not target.exists():
            partial = target.with_suffix(target.suffix + '.partial')
            run(['curl', '-fSL', '--retry', '2', '--max-time', '240', spec['url'], '-o', partial])
            if digest(partial) != spec['sha256']:
                raise RuntimeError(f'Download checksum mismatch: {name}')
            partial.replace(target)
        if digest(target) != spec['sha256']:
            raise RuntimeError(f'Cached checksum mismatch: {name}')
    for name in ('yosys_0.52-2_amd64.deb', 'yosys-abc_0.52-2_amd64.deb'):
        run(['dpkg-deb', '-x', downloads / name, out / 'sysroot'])
    with zipfile.ZipFile(downloads / 'sv2v-Linux.zip') as z:
        for name in z.namelist():
            if Path(name).is_absolute() or '..' in Path(name).parts:
                raise RuntimeError('Unsafe archive path')
        z.extractall(out)
    (out / 'sv2v-Linux/sv2v').chmod(0o755)
    rw = out / 'rapidwright'
    jar = downloads / 'rapidwright-2025.1.3-standalone-lin64.jar'
    with zipfile.ZipFile(jar) as z:
        # Do not unpack bundled unrelated devices or invoke the jar's installer.
        for name in ('LICENSE', 'LICENSE.TXT', 'data/parts.db', 'data/unisim_data.dat'):
            dest = rw / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(name))
    device = rw / 'data/devices/zynquplus/xczu15eg_db.dat'
    device.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(downloads / device.name, device)
    shutil.copyfile(HERE / 'RapidWrightSmoke.java', out / 'RapidWrightSmoke.java')
    (out / 'env.sh').write_text('''# Source after scripts/cloud/env.sh when both toolchains are needed.
_PRESCREEN_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PATH="${_PRESCREEN_ROOT}/sysroot/usr/bin:${_PRESCREEN_ROOT}/sv2v-Linux:${PATH}"
export RAPIDWRIGHT_PATH="${_PRESCREEN_ROOT}/rapidwright"
export RAPIDWRIGHT_JAR="${_PRESCREEN_ROOT}/downloads/rapidwright-2025.1.3-standalone-lin64.jar"
unset _PRESCREEN_ROOT
''')
    receipt = {'status': 'TOOLS_PREPARED', 'artifacts': LOCK['artifacts'],
               'part': 'xczu15eg-ffvb1156-2-i', 'scope': 'Tool smoke only, not actual DCP or timing qualification'}
    if smoke:
        env = {**os.environ, 'RAPIDWRIGHT_PATH': str(rw),
               'PATH': str(out / 'sysroot/usr/bin') + os.pathsep + os.environ.get('PATH', '')}
        sv = out / 'smoke.sv'
        sv.write_text('module top(input logic a, input logic b, output logic y); always_comb y = a ^ b; endmodule\n')
        with (out / 'smoke.v').open('w') as log:
            run([out / 'sv2v-Linux/sv2v', sv], stdout=log, env=env)
        yosys = out / 'sysroot/usr/bin/yosys'
        for label, command in [('sat', 'prep -top top; sat -set a 1 -set b 0 -prove y 1 -verify'),
                               ('abc', 'synth -top top; stat')]:
            with (out / f'yosys-{label}-smoke.log').open('w') as log:
                run([yosys, '-Q', '-T', '-p', f'read_verilog smoke.v; {command}'],
                    cwd=out, stdout=log, stderr=subprocess.STDOUT, env=env)
        run([java_bin('javac'), '-cp', jar, out / 'RapidWrightSmoke.java'], env=env)
        with (out / 'rapidwright-device-smoke.log').open('w') as log:
            run([java_bin('java'), '-Xmx2g', '-cp', str(jar) + os.pathsep + str(out),
                 'RapidWrightSmoke', 'device'], stdout=log, stderr=subprocess.STDOUT, env=env)
        receipt['status'] = 'PASS_TOOL_SMOKES_ONLY'
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(f"{receipt['status']}: source {out / 'env.sh'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=ROOT / 'simulator/build/cloud-prescreen')
    ap.add_argument('--smoke', action='store_true', help='Run bounded SAT/ABC and exact-device load smokes')
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    receipt_path = out / 'receipt.json'
    # Preserve previous evidence before replacing logs, and invalidate old PASS
    # before downloading, extracting, compiling, or executing any current run.
    old_evidence = list(out.glob('*.log'))
    if receipt_path.exists():
        old_evidence.append(receipt_path)
    if old_evidence:
        history = out / 'history'
        history.mkdir(exist_ok=True)
        index = 1
        while (history / f'run-{index:04d}').exists():
            index += 1
        archive = history / f'run-{index:04d}'
        archive.mkdir()
        for path in old_evidence:
            shutil.copyfile(path, archive / path.name)
    receipt_path.write_text(json.dumps({'status': 'RUNNING', 'smoke_requested': args.smoke}, indent=2) + '\n')
    try:
        restore(out, args.smoke)
    except BaseException as error:
        receipt_path.write_text(json.dumps({'status': 'FAILED_PRESERVE_EVIDENCE',
            'smoke_requested': args.smoke, 'error': str(error)}, indent=2) + '\n')
        raise


if __name__ == '__main__':
    main()
