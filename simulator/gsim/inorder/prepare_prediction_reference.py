#!/usr/bin/env python3
"""Rebuild the pinned first-batch predictor reference inside build/, without editing the current worktree."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[3]
BASE='e2039094f3665af5e9ab73876f94e041a3319179'


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
    classes=output/'reference-classes/soc/core/inorder';classes.mkdir(parents=True)
    hashes={}
    for path in sorted((source/'out/OrbitalI1/compile.dest/classes/soc/core/inorder').glob('FiveStageBranchPredictor*.class')):
        target=classes/path.name;shutil.copy2(path,target)
        hashes[str(target.relative_to(output/'reference-classes'))]=sha(target)
    if len(hashes)!=3:raise RuntimeError('review changed reference predictor class set')
    names=('src/main/scala/core/inorder/FiveStageBranchPredictor.scala','src/main/scala/core/inorder/FiveStageCore.scala',
           'src/main/scala/core/inorder/FiveStageConfig.scala','build.mill')
    manifest={'head':BASE,'reference_classes':str(output/'reference-classes'),'class_sha256':hashes,
        'source_sha256':{name:sha(source/name) for name in names},'compile_command':argv,
        'scope':'pinned first-batch predictor only; prepend before current test runtime; all other CPU/cache/MDU classes stay matched'}
    (output/'reference.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(output/'reference.json')


if __name__=='__main__':main()
