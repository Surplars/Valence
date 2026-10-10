"""Supplementary exact-byte equality of all 19 original positive/negative streams."""
from pathlib import Path
import argparse,hashlib,json,sys
H=Path(__file__).resolve().parent.parent/'posted-preparation-priority-cpu-host-r1';sys.path.insert(0,str(H))
from contract import sha,read,save,require,exact
import pair

def verify(receipt,digest,out,controls=None):
 receipt=Path(receipt).resolve();raw=read(receipt);case=raw['case'];require(case in(19,21),'only original COPY baseline');r,p,e=pair.one(receipt,digest,'off',case,controls)
 baseline=read(H/'BASELINE-REFERENCE.json')[str(case)];require(sha(baseline['source_receipt'])==baseline['source_receipt_sha256'],'baseline identity changed');old=read(baseline['source_receipt']);require(exact(r['result'],old['result']),'complete original result differs')
 required={f'{prefix}.{trace}.jsonl'for prefix in('positive','trap-negative')for trace in pair.run.TRACE_ENV.values()}|{'positive.window.jsonl.lifetimes.jsonl'}
 require(len(required)==19 and required<=set(old['artifacts']),'full original stream inventory missing')
 checks={}
 for name in sorted(required):
  actual=sha(receipt.parent/name);require(actual==r['artifacts'][name]==old['artifacts'][name],'literal original trace changed '+name);checks[name]=dict(sha256=actual,bytes=(receipt.parent/name).stat().st_size)
 j=dict(schema='posted-preparation-priority-all-original-off-reproduction-v1',status='PASS_FRESH_OFF_FULL_RESULT_AND_ALL_19_ORIGINAL_RAW_BYTES',case=case,new_execution=True,guest_changed=False,normalization_applied=False,receipt_path=str(receipt),receipt_sha256=digest,old_receipt_path=baseline['source_receipt'],old_receipt_sha256=baseline['source_receipt_sha256'],full_original_result_equal=True,raw_files=checks,pair_terminal_verification=e,verifier_sha256=sha(__file__))
 save(out,j,True);return j
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--receipt',required=True);a.add_argument('--sha256',required=True);a.add_argument('--out',required=True);a.add_argument('--controls');v=a.parse_args();j=verify(v.receipt,v.sha256,v.out,v.controls);print(json.dumps(dict(status=j['status'],case=j['case'],raw_files=len(j['raw_files']),receipt=v.out,sha256=sha(v.out)),indent=2))
