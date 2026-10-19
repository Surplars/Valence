#!/usr/bin/env python3
"""Bounded four-state reset/owner test of the actual two-master MSI arbiter.

Consumes existing compiled classes, emits unchanged common and legacy modules,
then runs the same external-port oracle against both. No Scala compilation,
RTL rewriting, internal-state injection, tool installation or broad regression.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from bringup import (Guard, ROOT, FLOOR_BYTES, sha, require, executable,
                     classpath_manifest, verify_classpath_unchanged)


def tool_manifest(iverilog, vvp, java, firtool):
    paths = dict(iverilog=iverilog, vvp=vvp, java=java, firtool=firtool)
    if iverilog.read_bytes()[:2] == b'#!':
        for line in iverilog.read_text().splitlines():
            if line.startswith('exec '):
                parts = shlex.split(line)
                paths['iverilog_engine'] = Path(parts[1])
                if '-B' in parts:
                    base = Path(parts[parts.index('-B')+1])
                    for name in ['ivl', 'ivlpp', 'vvp.tgt', 'vvp.conf']:
                        paths[name] = base/name
    return {name: dict(path=str(path.resolve()), sha256=sha(path)) for name,path in paths.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--java', required=True)
    parser.add_argument('--java-classpath-file', type=Path, required=True)
    parser.add_argument('--compile-receipt', type=Path, required=True)
    parser.add_argument('--firtool', required=True)
    parser.add_argument('--iverilog', required=True)
    parser.add_argument('--vvp', required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    require(not out.exists() and out.parent.is_dir(), 'fresh output directory required')
    require(shutil.disk_usage(out.parent).free >= FLOOR_BYTES, '4 GiB free disk floor')
    out.mkdir()
    guard = Guard(out)
    receipt = dict(status='RUNNING', scope='actual 8-owner MSI arbiter four-state reset and handshake only',
                   no_internal_state_injection=True, no_rtl_rewrite=True, scala_compilation=False,
                   same_testbench_for_common_and_legacy=True, steps=[])
    def save():
        receipt['steps'] = guard.records
        (out/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    try:
        compile_receipt = json.loads(args.compile_receipt.read_text())
        require(compile_receipt.get('exit') == 0 and compile_receipt.get('error') is None,
                'passing central compilation receipt required')
        receipt['compile_receipt'] = dict(path=str(args.compile_receipt.resolve()),
                                         sha256=sha(args.compile_receipt), content=compile_receipt)
        cp, compiled = classpath_manifest(args.java_classpath_file.resolve(),
                                          'platform.CommonRegisterArbiterResetMain')
        receipt['compiled'] = compiled
        inputs = [ROOT/'src/main/scala/ip/bus/TwoMasterRegisterArbiter.scala',
                  ROOT/'src/main/scala/ip/bus/RegisterPort.scala',
                  ROOT/'src/main/scala/platform/CommonInterruptFabric.scala',
                  ROOT/'src/test/scala/platform/CommonRegisterArbiterResetMain.scala',
                  ROOT/'build.mill', HERE.parent/'bringup.py', Path(__file__),
                  HERE/'register_arbiter_reset_tb.sv', HERE/'register_arbiter_reset_README.md']
        receipt['source_sha256'] = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
        java = executable(args.java, 'java')
        firtool = executable(args.firtool, 'firtool')
        iverilog = executable(args.iverilog, 'iverilog')
        vvp = executable(args.vvp, 'vvp')
        receipt['tools'] = tool_manifest(iverilog, vvp, java, firtool)
        env = dict(os.environ, CHISEL_FIRTOOL_PATH=str(firtool.parent))
        receipt['variants'] = {}
        save()
        for variant in ['common', 'legacy']:
            model = out/variant
            guard.run(variant+'-emit', [java, '-Xmx1g', '-XX:ActiveProcessorCount=2', '-cp', cp,
                'platform.CommonRegisterArbiterResetMain', model, variant], env=env, timeout=120)
            rtl = sorted(model.glob('*.sv'))
            require(rtl and (model/'TwoMasterRegisterArbiter.sv').exists(), 'missing real arbiter RTL')
            require(sum(p.stat().st_size for p in rtl) < 20*1024**2, 'small-module size bound exceeded')
            joined = '\n'.join(p.read_text() for p in rtl)
            require('$fatal' in joined, 'inline production assertions must remain enabled')
            require('RANDOMIZE_REG_INIT' not in joined, 'random register initialization forbidden')
            sim = model/'run.vvp'
            guard.run(variant+'-compile', [iverilog, '-g2012', '-s', 'register_arbiter_reset_tb',
                '-o', sim, HERE/'register_arbiter_reset_tb.sv', *rtl], timeout=60)
            result = guard.run(variant+'-run', [vvp, sim], timeout=20,
                               expected=0 if variant == 'common' else 1)
            if variant == 'common':
                require('REGISTER_ARBITER_RESET_PASS ' in result, 'positive oracle completion missing')
                require('cold_client1=1' in result and 'eight_owner=1' in result and
                        'fair_ii1=8' in result and 'reset_clear=1' in result,
                        'required positive coverage missing')
            else:
                require('ORACLE_UNKNOWN_REQUEST_READY client=1' in result and
                        'downstream_valid=1 downstream_ready=1' in result,
                        'legacy must fail directly on cold-start acceptance, not timeout or setup')
                require('REGISTER_ARBITER_RESET_PASS' not in result, 'legacy unexpectedly passed')
            receipt['variants'][variant] = dict(result=result.strip(),
                artifacts={str(p.relative_to(out)):sha(p) for p in [*rtl, sim]},
                status='PASS' if variant == 'common' else 'EXPECTED_ORACLE_REJECTION')
            save()
        verify_classpath_unchanged(compiled)
        require(all(sha(ROOT/p) == digest for p,digest in receipt['source_sha256'].items()),
                'source drift during verification')
        receipt['status'] = 'PASS_COMMON_MSI_RESET_NATIVE_WITH_LEGACY_NEGATIVE'
        receipt['minimum_free_bytes'] = min(step['minimum_free_bytes'] for step in guard.records)
        receipt['total_artifact_bytes'] = sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
        require(receipt['total_artifact_bytes'] < 20*1024**2, 'total evidence bound exceeded')
    except BaseException as error:
        receipt.update(status='FAIL', error=str(error))
        save()
        raise
    save()
    print(json.dumps(dict(status=receipt['status'], receipt=str(out/'receipt.json'))))


if __name__ == '__main__':
    main()
