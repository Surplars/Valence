#!/usr/bin/env python3
"""Prepare a hash-bound four-source Mill fixture using already compiled unchanged dependencies."""
import argparse, hashlib, json, shutil
from pathlib import Path

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-root',type=Path,required=True)
    ap.add_argument('--dependency-root',type=Path,required=True)
    ap.add_argument('--toolchain-root',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();source=a.source_root.resolve();deps=a.dependency_root.resolve();tool=a.toolchain_root.resolve();out=a.output.resolve()
    sources=['src/main/scala/core/ooo/PendingVirtualStoreProof.scala',
        'src/main/scala/core/ooo/PendingStoreProofRobMapping.scala',
        'src/test/scala/ooo/FrozenPendingStoreRobMapping.scala',
        'src/test/scala/ooo/PendingStoreRobMappingGsim.scala']
    binding={};different=[]
    for p in sorted(source.glob('src/**/*.scala')):
        rel=str(p.relative_to(source));old=deps/rel
        if old.exists():
            if sha(old)!=sha(p):different.append(rel)
            else:binding[str(old)]=sha(old)
    assert set(different)=={'src/main/scala/core/ooo/PendingVirtualStoreProof.scala','src/main/scala/core/ooo/IntegerBackend.scala'},different
    # Only IntegerRequest is used from the changed backend file; its exact definition is unchanged.
    def request(path):
        text=path.read_text();return text[text.index('class IntegerRequest'):text.index('private[ooo] class IntegerIssueEntry')]
    assert request(source/'src/main/scala/core/ooo/IntegerBackend.scala')==request(deps/'src/main/scala/core/ooo/IntegerBackend.scala')
    for rel in ['build.mill','.mill-version','.mill-jvm-opts']:
        assert sha(source/rel)==sha(deps/rel),rel
        binding[str(deps/rel)]=sha(deps/rel)
    for p in deps.glob('third_party/**/*.scala'):binding[str(p)]=sha(p)
    for rel in ['IonSoC/compile.json','IonSoC/test/compile.json','IonSoC/scalacOptions.json',
                'IonSoC/test/scalacOptions.json','IonSoC/compileClasspath.json','IonSoC/test/compileClasspath.json']:
        p=deps/'out'/rel
        if p.is_file():binding[str(p)]=sha(p)
    out.mkdir(parents=True,exist_ok=False)
    copied={};omitted=[]
    for name,rel in [('main','IonSoC/compile.dest/classes'),('test','IonSoC/test/compile.dest/classes'),('hardfloat','HardFloatLib/compile.dest/classes')]:
        directory=deps/'out'/rel;assert directory.is_dir()
        for p in sorted(directory.rglob('*')):
            if not p.is_file():continue
            tail=p.relative_to(directory)
            if any(p.name.startswith(prefix) for prefix in ['PendingVirtualStoreProof','PendingStoreProofOwner','PendingStoreEarlyLoadCredit','LoadQueryReuse']):
                omitted.append(str(p));continue
            dst=out/'dependencies'/name/tail;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst)
            binding[str(p)]=sha(p);copied[str(dst)]=sha(dst)
    for rel in sources:binding[str(source/rel)]=sha(source/rel)
    binding[str(tool/'bin/mill')]=sha(tool/'bin/mill')
    binding[str(tool/'activate.sh')]=sha(tool/'activate.sh')
    build='''import mill.*, scalalib.*
object Fixture extends ScalaModule {
    def scalaVersion = "2.13.17"
    def mvnDeps = Seq(mvn"org.chipsalliance::chisel:7.3.0")
    def scalacPluginMvnDeps = Seq(mvn"org.chipsalliance:::chisel-plugin:7.3.0")
    def scalacOptions = Seq("-language:reflectiveCalls", "-deprecation", "-feature", "-Xcheckinit", "-Ymacro-annotations")
    def sources = Task.Sources(SOURCE_LIST)
    def dependencyClasses = Task.Sources(CLASSPATH_LIST)
    def unmanagedClasspath = Task { dependencyClasses() }
}
'''.replace('SOURCE_LIST',', '.join('os.Path('+json.dumps(str(source/rel))+')' for rel in sources)).replace('CLASSPATH_LIST',', '.join('os.Path('+json.dumps(str(out/'dependencies'/name))+')' for name in ['main','test','hardfloat']))
    (out/'build.mill').write_text(build)
    (out/'.mill-version').write_text('1.1.7\n')
    (out/'.mill-jvm-opts').write_text('-Dchisel.project.root=${PWD}\n-Xmx1536m\n')
    for name in ['build.mill','.mill-version','.mill-jvm-opts']:copied[str(out/name)]=sha(out/name)
    state={'schema':'pending-store-rob-map-compiled-dependencies-v1','source_root':str(source),
        'dependency_root':str(deps),'bindings':binding,'copied_files':copied,'excluded_cached_classes':omitted,
        'compiled_sources':sources,'actual_mill':str(tool/'bin/mill'),
        'limits':'Reuse immutable dependency classes only. Actual bank/helper classes are freshly compiled, constructor and loaded-resource hashes checked by the fixture. No CPU qualification.'}
    (out/'binding.json').write_text(json.dumps(state,indent=2)+'\n')
    binding_hash=sha(out/'binding.json')
    bridge='''#!/usr/bin/env python3
import hashlib,json,os,sys
from pathlib import Path
root=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert sha(root/'binding.json')==BINDING_SHA, 'cache binding drift'
s=json.loads((root/'binding.json').read_text())
for path,digest in {**s['bindings'],**s['copied_files']}.items():
    assert sha(path)==digest, 'bound dependency drift: '+path
args=sys.argv[1:]
assert 'IonSoC.test.runMain' in args, 'minimal bridge accepts only focused runMain'
args[args.index('IonSoC.test.runMain')]='Fixture.runMain'
os.chdir(root)
os.execv(s['actual_mill'],[s['actual_mill'],*args])
'''.replace('BINDING_SHA',repr(binding_hash))
    (out/'mill').write_text(bridge);(out/'mill').chmod(0o755)
    print(json.dumps({'status':'PREPARED_NOT_COMPILED','bridge':str(out/'mill'),'binding_sha256':binding_hash,'source_count':len(sources),'cached_files':len(copied),'excluded':len(omitted)},indent=2))
if __name__=='__main__':main()
