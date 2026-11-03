#!/usr/bin/env python3
"""Rebuild the pinned second-batch complete I1 reference inside build/, without editing the current worktree."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[3]
BASE='391d931b420bfd4da95684ad937f11fd25fa8a00'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'build'):
        parser.error('fresh output below repository build/ required')
    if os.environ.get('VALENCE_WORK_ROOT')!=str(ROOT):
        parser.error('source the worktree .local-dev/env.sh first so caches/tmp stay inside it')
    subprocess.run(['git','cat-file','-e',BASE+'^{commit}'],cwd=ROOT,check=True)
    source=output/'source';source.mkdir(parents=True)
    archive=subprocess.Popen(['git','archive','--format=tar',BASE],cwd=ROOT,stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=archive.stdout,mode='r|') as data:
            data.extractall(source,filter='data')
    finally:
        archive.stdout.close()
    if archive.wait()!=0:raise RuntimeError('pinned source archive failed')
    argv=['mill','-i','-j','2','OrbitalI1.compile']
    with (output/'compile.log').open('w') as stream:
        result=subprocess.run(argv,cwd=source,stdout=stream,stderr=subprocess.STDOUT,
            env={**os.environ,'PWD':str(source)})
    result.check_returncode()
    classes=output/'classes/soc/core/inorder';classes.parent.mkdir(parents=True)
    shutil.copytree(source/'out/OrbitalI1/compile.dest/classes/soc/core/inorder',classes)
    hashes={str(path.relative_to(output/'classes')):sha(path) for path in sorted(classes.rglob('*.class'))}
    if len(hashes)<200:raise RuntimeError('incomplete pinned production class tree')
    manifest={'head':BASE,'reference_classes':str(output/'classes'),'class_sha256':hashes,
        'source_sha256':{str(path.relative_to(source)):sha(path) for path in
            sorted((source/'src/main/scala/core/inorder').glob('*.scala'))},'compile_command':argv,
        'scope':'entire pinned production I1 classes; prepend before current test runtime'}
    (output/'reference.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(output/'reference.json')


if __name__=='__main__':main()
