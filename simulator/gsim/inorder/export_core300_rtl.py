#!/usr/bin/env python3
"""Re-export an already accepted I1 batch with explicit masked-memory lowering."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[3]
WINDOWS = Path('/mnt/e/VM/Share/Valence-rtl/Valence-InOrder')
BASE = '391d931b420bfd4da95684ad937f11fd25fa8a00'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--acceptance', type=Path, required=True)
    parser.add_argument('--reuse-export', type=Path, help='Reuse accepted core/cached RTL and identical reference simulation; emit only candidate simulation')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(WINDOWS) or os.environ.get('VALENCE_WORK_ROOT') != str(ROOT):
        parser.error('source local env; fresh output inside designated Windows root required')
    reference, accepted = json.loads(args.reference.read_text()), json.loads(args.acceptance.read_text())
    if reference['head'] != BASE or accepted['status'] != 'PASS_I1_CORE300_SHORT_FUNCTIONAL_ONLY':
        raise RuntimeError('unexpected functional/reference evidence')
    for name, digest in accepted['source_sha256'].items():
        if name.startswith('src/main/') or name.startswith('simulator/gsim/harness/'):
            if sha(ROOT/name) != digest:
                raise RuntimeError('accepted functional source drift: '+name)
    ref = Path(reference['reference_classes'])
    for name, digest in reference['class_sha256'].items():
        if sha(ref/name) != digest:
            raise RuntimeError('frozen reference class drift: '+name)
    values = json.loads((ROOT/'out/OrbitalI1/test/runClasspath.json').read_text())['value']
    paths = [Path(value.split(':', 3)[3]) for value in values]
    runtime = os.pathsep.join(str(path) for path in paths if path.exists())
    source = sorted((ROOT/'src/main/scala/core/inorder').glob('*.scala'))
    source += sorted((ROOT/'src/test/scala/inorder').glob('*.scala'))
    frozen = {str(path.relative_to(ROOT)): sha(path) for path in source}
    receipt = dict(status='RUNNING', baseline_commit=BASE, reference_sha256=sha(args.reference),
                   acceptance_sha256=sha(args.acceptance), source_sha256=frozen,
                   firtool='1.135.0', lowering=['--split-verilog', '--lower-memories',
                   '--lowering-options=disallowLocalVariables,disallowPackedArrays'], commands=[])
    previous = json.loads(args.reuse_export.read_text()) if args.reuse_export else None
    if previous:
        if previous['status'] != 'PASS_I1_ACCEPTED_BATCH_MASKED_RAM_RTL_EXPORT':
            raise RuntimeError('prior export did not pass')
        for name in ['src/test/scala/inorder/I1PerformanceCoreMain.scala', 'src/test/scala/inorder/I1VivadoMain.scala']:
            if previous['source_sha256'][name] != frozen[name]:
                raise RuntimeError('reference simulation fixture changed: '+name)
        # Current reference core/cached were freshly emitted from pinned classes
        # by acceptance. Identical RTL also proves current argument/config parsing.
        for name,digest in accepted['rtl_sha256'].items():
            if name.startswith('reference/') and previous['rtl_sha256'].get(name) != digest:
                raise RuntimeError('reference RTL changed; full export required: '+name)
        receipt['reuse_export_sha256']=sha(args.reuse_export)
        receipt['reused_rtl']=[]
    receipt['exporter_sha256']=sha(Path(__file__))
    output.mkdir(parents=True)
    def save():
        (output/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    try:
        for role in ['reference', 'candidate', 'candidate-hashed']:
            flags = ['64', '--pipeline=fpga8', '--timing-cuts', '--dsp-tiled', '--predictor=128',
                     '--icache=32768', '--dcache=32768']
            if role == 'candidate-hashed':
                flags += ['--hashed-branch-index']
            cp = (str(ref)+os.pathsep if role == 'reference' else '')+runtime
            for name, entry in [('core', 'I1Core300Main'), ('cached', 'FiveStageCachedRtlMain'),
                                ('simulation', 'I1PerformanceCachedRtlMain')]:
                folder = output/role/name
                if previous and role=='candidate-hashed' and name=='simulation':
                    continue  # No hashed physical/xsim claim in this batch.
                if previous and (name in ['core','cached'] or role=='reference'):
                    source = (Path(accepted['rtl_root'])/role/name if name in ['core','cached']
                              else args.reuse_export.parent/role/name)
                    expected = accepted['rtl_sha256'] if name in ['core','cached'] else previous['rtl_sha256']
                    source_files=list(source.rglob('*.sv'))
                    if not source_files:raise RuntimeError('missing reusable RTL')
                    for path in source_files:
                        key=role+'/'+name+'/'+str(path.relative_to(source))
                        if expected.get(key)!=sha(path):raise RuntimeError('reusable RTL drift: '+key)
                    shutil.copytree(source,folder)
                    receipt['reused_rtl'].append(dict(role=role,entry=name,source=str(source),files=len(source_files)))
                    save()
                    continue
                folder.mkdir(parents=True)
                origins = folder/'classes.log'
                cmd = ['java', '-Xlog:class+load=info:file='+str(origins), '-cp', cp,
                       'inorder.'+entry, str(folder), *flags]
                receipt['commands'].append(cmd)
                save()
                with (folder/'emit.log').open('w') as log:
                    subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
                marker = 'soc.core.inorder.FiveStageWordCache source: '
                actual = [Path(unquote(urlparse(line.split(marker,1)[1].strip()).path)).resolve()
                          for line in origins.read_text().splitlines() if marker in line]
                expected = ref if role == 'reference' else ROOT/'out/OrbitalI1/compile.dest/classes'
                if actual != [expected]:
                    raise RuntimeError('wrong production class origin: '+role)
                # Byte memories must have no packed multi-granularity write-mask port.
                data = list(folder.glob('data_*x8.sv'))
                if not data or any('W0_mask' in path.read_text() for path in data):
                    raise RuntimeError('explicit byte memory lowering missing: '+str(folder))
        for name, digest in frozen.items():
            if sha(ROOT/name) != digest:
                raise RuntimeError('source changed during export: '+name)
        receipt['rtl_sha256'] = {str(path.relative_to(output)): sha(path) for path in sorted(output.rglob('*.sv'))}
        receipt['status'] = 'PASS_I1_ACCEPTED_BATCH_MASKED_RAM_RTL_EXPORT'
    except BaseException as error:
        receipt.update(status='FAIL', error=repr(error))
        raise
    finally:
        save()
    print(json.dumps(dict(status=receipt['status'], receipt=str(output/'receipt.json'))))


if __name__ == '__main__':
    main()
