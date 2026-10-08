#!/usr/bin/env python3
"""Recheck the head-token option guard and prove selected models byte-identical."""
import argparse,hashlib,json
from pathlib import Path
import run as common

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qualified',type=Path,required=True);parser.add_argument('--tag',required=True)
    parser.add_argument('--fpu-qualified',type=Path,required=True)
    args=parser.parse_args();prior=args.qualified.resolve();out=common.BUILD/args.tag;out.mkdir(parents=True,exist_ok=False)
    qualified=json.loads((prior/'receipt.json').read_text())
    if qualified['status']!='PASS_PROTECTED_HEAD_ABLATION':raise RuntimeError('qualified A/B receipt required')
    paths=sorted((common.ROOT/'src').rglob('*.scala'))+sorted((common.ROOT/'third_party/berkeley-hardfloat/src/main/scala').rglob('*.scala'))
    paths += [common.ROOT/'build.mill',common.ROOT/'.mill-version',Path(__file__).resolve()]
    sources={str(p.relative_to(common.ROOT)):sha(p) for p in paths}
    fpReceipt=args.fpu_qualified.resolve();fp=json.loads(fpReceipt.read_text())
    if fp['status']!='PASS_FUNCTIONAL_RESOURCE_CANDIDATE':raise RuntimeError('qualified FPU dependency receipt required')
    dependencies={name:digest for name,digest in sources.items() if name.startswith('third_party/')}
    if not dependencies or any(fp['source_sha256'].get(name)!=digest for name,digest in dependencies.items()):raise RuntimeError('pinned HardFloat sources differ from qualified FPU receipt')
    changed=[name for name,digest in sources.items() if name.startswith('src/') and qualified['inputs'].get(name)!=digest]
    expected=['src/main/scala/core/ooo/OooParams.scala','src/test/scala/ooo/ProtectedHeadPayloadSpec.scala']
    if sorted(changed)!=expected:raise RuntimeError('unexpected source delta: '+str(changed))
    params=(common.ROOT/expected[0]).read_text().replace(' && fastHeadSystemRecovery),', '),').replace(
        'protected head payload sharing requires banked storage, compressed FP and the protected head-token observation',
        'protected head payload sharing requires banked issue storage and compressed FP system ownership')
    test=(common.ROOT/expected[1]).read_text().replace(
        '        intercept[IllegalArgumentException] { p.copy(shareProtectedHeadPayload = true, fastHeadSystemRecovery = false) }\n','')
    for name,text in zip(expected,(params,test)):
        if hashlib.sha256(text.encode()).hexdigest()!=qualified['inputs'][name]:raise RuntimeError('delta exceeds intended guard/test: '+name)
    state={'status':'RUNNING','inputs':sources,'qualified_receipt':str(prior/'receipt.json'),
        'qualified_receipt_sha256':sha(prior/'receipt.json'),'changed':changed,'models':{},'fpu_dependency_receipt':str(fpReceipt),'fpu_dependency_receipt_sha256':sha(fpReceipt),
        'dependency_note':'Fresh re-elaboration binds build.mill/.mill-version and18 pinned HardFloat Scala files omitted by older behavioral runner inventories',
        'qualification':'Behavior/cycles inherited only after exact regenerated FIR identity; no C++ rebuild or changed DUT behavior'}
    try:
        common.run(['mill','-i','IonSoC.test.testOnly','ooo.ProtectedHeadPayloadSpec'],log=out/'contracts.log')
        for label in ('dedicated','shared'):
            model=out/label;model.mkdir()
            common.run(['mill','-i','IonSoC.test.runMain','ooo.ProtectedHeadPayloadGsimMain',model,label],log=model/'emit.log')
            name=label+'/FloatingPointCpuGsim.fir';fresh=model/'FloatingPointCpuGsim.fir';old=prior/name
            if sha(old)!=qualified['artifacts'][name]:raise RuntimeError('qualified FIR changed')
            state['models'][label]={'qualified_sha256':sha(old),'current_sha256':sha(fresh),'byte_identical':fresh.read_bytes()==old.read_bytes()}
            if fresh.read_bytes()!=old.read_bytes():raise RuntimeError('configuration guard changed selected FIR')
        state['status']='PASS_CONTRACT_AND_IDENTICAL_FIR'
    except Exception as error:state['status']='FAIL';state['error']=str(error);raise
    finally:
        if any(sha(common.ROOT/name)!=digest for name,digest in sources.items()):state['status']='FAIL_SOURCE_CHANGED'
        state['artifacts']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='receipt.json'}
        (out/'receipt.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps({'status':state['status'],'receipt':str(out/'receipt.json')}))
if __name__=='__main__':main()
