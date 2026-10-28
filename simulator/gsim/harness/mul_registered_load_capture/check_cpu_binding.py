#!/usr/bin/env python3
"""Read-only exact model pin check. No compilation, generation, or execution."""
import argparse,hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--model-dir',required=True,type=Path);ap.add_argument('--report',required=True,type=Path);a=ap.parse_args()
    pin=json.loads((ROOT/'cpu_model_binding.json').read_text())
    if pin['capture_members_count']!=137 or len(set(pin['capture_members']))!=137:raise RuntimeError('unexpected observer scope')
    for rel,want in pin['portable_observer_files'].items():
        if digest(ROOT/rel)!=want:raise RuntimeError('observer source changed; independent requalification required: '+rel)
    files={}
    for kind in ['cpp','header']:
        p=a.model_dir/pin[kind]['name'];actual=digest(p)
        if actual!=pin[kind]['sha256']:raise RuntimeError('not the reviewed '+kind+' model; do not bypass with name/width-only matching')
        files[str(p)]=actual
    text=(a.model_dir/pin['header']['name']).read_text()
    missing=[n for n in pin['capture_members'] if not re.search(r'\b'+re.escape(n)+r'(?:\[[^;]*\])?;',text)]
    if missing:raise RuntimeError('missing actual members: '+','.join(missing))
    report={'status':'PASS_PINNED_MODEL_IDENTITY_NOT_NEW_ABI_QUALIFICATION','files':files,'capture_members':137,'model_execution':False,'limits':'CURRENT phase/authority qualification belongs to the reviewed exact model. A different generator or source requires independent semantic review.'}
    with a.report.open('x') as f:json.dump(report,f,indent=2);f.write('\n')
    print(report['status'])
if __name__=='__main__':main()
