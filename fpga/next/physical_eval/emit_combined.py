"""Explicit fresh native export wrapper; never runs Vivado or a simulator.

Use only after committing the final source. Tool paths and expected versions are
explicit; all emitted artifacts and the clean source closure are sealed together.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
from combined_contract import info, require, source_closure, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--native-root', required=True, type=Path)
    parser.add_argument('--commit', required=True)
    for name in ('mill', 'firtool', 'java'):
        parser.add_argument('--'+name, required=True, type=Path)
        parser.add_argument('--'+name+'-version', required=True,
                            help='Exact trimmed version output; java uses -version, others --version')
    args = parser.parse_args()
    source, out = args.source_root.resolve(), args.native_root.resolve()
    require(not out.exists() and source not in out.parents and out not in source.parents,
            'Native export must be a fresh external directory')
    require(Path(__file__).resolve().parent == source/'fpga/next/physical_eval',
            'Execute emission wrapper from selected source checkout')
    before = source_closure(source)
    require(before['commit'] == args.commit, 'Commit differs from requested source')
    toolchain = {}
    for name in ('mill', 'firtool', 'java'):
        path = getattr(args, name).resolve(strict=True)
        result = subprocess.run([str(path), '-version' if name == 'java' else '--version'],
                                cwd=source, capture_output=True, text=True, check=True)
        version = (result.stdout+result.stderr).strip()
        require(version == getattr(args, name+'_version'), 'Unexpected '+name+' version')
        toolchain[name] = dict(path=str(path), **info(path), version=version)
    toolchain['python'] = dict(path=sys.executable, **info(sys.executable), version=sys.version)
    toolchain['build'] = {name: info(source/name) for name in ('build.mill', '.mill-version', '.mill-jvm-opts')}
    env = dict(os.environ, CHISEL_FIRTOOL_PATH=str(args.firtool.resolve().parent),
               JAVA_HOME=str(args.java.resolve().parent.parent))
    command = [str(args.mill.resolve()), '-i', 'IonSoC.test.runMain', 'ooo.CombinedBandwidthNativeMain', str(out), 'native']
    subprocess.run(command, cwd=source, env=env, check=True)
    require(source_closure(source) == before, 'Source changed during native emission; reject output')
    for name in ('mill', 'firtool', 'java'):
        require(info(toolchain[name]['path']) == {key: toolchain[name][key] for key in ('sha256', 'bytes')},
                'Tool changed during native emission')
    write(out/'emission-toolchain.json', toolchain)
    artifacts = {p.relative_to(out).as_posix(): info(p) for p in out.rglob('*') if p.is_file()}
    write(out/'export-provenance.json', dict(schema='combined-bandwidth-export-provenance-v1',
          status='PASS_FRESH_NATIVE_EXPORT_ONLY', sourceClosure=before, toolchain=toolchain,
          command=command, artifacts=artifacts, physicalQualification=False))
    print('PASS_FRESH_NATIVE_EXPORT_ONLY: independent experimental evidence; no physical qualification')


if __name__ == '__main__':
    main()
