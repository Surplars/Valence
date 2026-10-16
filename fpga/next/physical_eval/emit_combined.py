"""Explicit fresh native export wrapper; never runs Vivado or a simulator.

Use only after committing the final source. Tool paths and expected versions are
explicit; all emitted artifacts and the clean source closure are sealed together.
"""
import argparse
import os
import re
import shlex
from pathlib import Path
import subprocess
import sys
from combined_contract import info, require, source_closure, write


def normalized_version(text):
    """JVM option echoes can contain proxy credentials; version lines cannot need them."""
    return '\n'.join(line for line in text.splitlines() if not re.match(
        r'^(Picked up (JAVA_TOOL_OPTIONS|_JAVA_OPTIONS):|NOTE: Picked up JDK_JAVA_OPTIONS:)', line)).strip()


def bind_mill_distribution(launcher, distribution):
    launcher, distribution = Path(launcher).resolve(strict=True), Path(distribution).resolve(strict=True)
    if launcher != distribution:
        expected = b'#!/usr/bin/env bash\nexec bash "$(dirname -- "$0")/mill-dist" "$@"\n'
        require(launcher.read_bytes() == expected and distribution == launcher.parent/'mill-dist',
                'Unrecognized Mill launcher/distribution binding; review actual launcher before export')
    return dict(path=str(distribution), **info(distribution))


def verify_tool_bytes(toolchain):
    for name in ('mill', 'millDistribution', 'firtool', 'java'):
        require(info(toolchain[name]['path']) == {key: toolchain[name][key] for key in ('sha256', 'bytes')},
                'Tool changed during native emission: '+name)


def emission_environment(args):
    return dict(os.environ, CHISEL_FIRTOOL_PATH=str(args.firtool.resolve().parent),
                JAVA_HOME=str(args.java.resolve().parent.parent))


def safe_environment(env):
    """Allowlisted paths/options only; never publish proxy addresses or secret values."""
    result = {key: env[key] for key in ('JAVA_HOME', 'CHISEL_FIRTOOL_PATH', 'HOME',
              'XDG_CACHE_HOME', 'COURSIER_CACHE') if key in env}
    for key in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS'):
        options = shlex.split(env.get(key, ''))
        result[key] = [option if re.fullmatch(r'-Xmx[0-9]+[kKmMgG]|-XX:ActiveProcessorCount=[0-9]+', option)
                       else '<redacted-option>' for option in options]
    result['repositorySelection'] = 'explicit environment; values redacted' if 'COURSIER_REPOSITORIES' in env else 'tool default'
    result['proxySelection'] = 'environment present; endpoints and credentials redacted' if any(
        key in env for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy')) else 'none recorded'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--native-root', required=True, type=Path)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--mill-distribution', required=True, type=Path,
                        help='Actual Mill distribution; same as launcher for standalone, adjacent mill-dist for supported shell wrapper')
    for name in ('mill', 'firtool', 'java'):
        parser.add_argument('--'+name, required=True, type=Path)
        parser.add_argument('--'+name+'-version', required=True,
                            help='Exact version output excluding JVM option echo lines; java uses -version, others --version')
    args = parser.parse_args()
    source, out = args.source_root.resolve(), args.native_root.resolve()
    require(not out.exists() and source not in out.parents and out not in source.parents,
            'Native export must be a fresh external directory')
    require(Path(__file__).resolve().parent == source/'fpga/next/physical_eval',
            'Execute emission wrapper from selected source checkout')
    before = source_closure(source)
    require(before['commit'] == args.commit, 'Commit differs from requested source')
    env = emission_environment(args)
    toolchain = dict(millDistribution=bind_mill_distribution(args.mill, args.mill_distribution))
    for name in ('mill', 'firtool', 'java'):
        path = getattr(args, name).resolve(strict=True)
        result = subprocess.run([str(path), '-version' if name == 'java' else '--version'],
                                cwd=source, env=env, capture_output=True, text=True, check=True)
        version = normalized_version(result.stdout+result.stderr)
        require(version == normalized_version(getattr(args, name+'_version')), 'Unexpected '+name+' version')
        toolchain[name] = dict(path=str(path), **info(path), version=version)
        if name == 'mill':
            require('java.home: '+env['JAVA_HOME'] in version.splitlines(),
                    'Mill did not use the explicitly selected JDK')
    toolchain['python'] = dict(path=sys.executable, **info(sys.executable), version=sys.version)
    toolchain['build'] = {name: info(source/name) for name in ('build.mill', '.mill-version', '.mill-jvm-opts')}
    toolchain['environment'] = safe_environment(env)
    verify_tool_bytes(toolchain)
    command = [str(args.mill.resolve()), '-i', 'IonSoC.test.runMain', 'ooo.CombinedBandwidthNativeMain', str(out), 'native']
    subprocess.run(command, cwd=source, env=env, check=True)
    require(source_closure(source) == before, 'Source changed during native emission; reject output')
    verify_tool_bytes(toolchain)
    write(out/'emission-toolchain.json', toolchain)
    artifacts = {p.relative_to(out).as_posix(): info(p) for p in out.rglob('*') if p.is_file()}
    write(out/'export-provenance.json', dict(schema='combined-bandwidth-export-provenance-v1',
          status='PASS_FRESH_NATIVE_EXPORT_ONLY', sourceClosure=before, toolchain=toolchain,
          command=command, artifacts=artifacts, physicalQualification=False))
    print('PASS_FRESH_NATIVE_EXPORT_ONLY: independent experimental evidence; no physical qualification')


if __name__ == '__main__':
    main()
