import gzip,tempfile,hashlib,json
from pathlib import Path
from proof_controls_compressed import CHANGES,mutation,reason,decoded_identity
from contract import require
x=dict(event='result',inserted=1,index=63,tag=2**64-1,epoch=2**32-1,va=0x80201000,size=3,pa=0x80201000,allowed=1,ownermatches=1,cycle=123,accepted_cycle=124)
expected={'same_index_new_tag':0,'wrong_index':62,'wrong_epoch':0,'wrong_pa_line':0x80201040,'permission_not_allowed':0,'not_inserted_owner':0,'acceptance_not_next_edge':123}
for name,field in CHANGES:
 y=mutation(x,name);require({k for k in x if x[k]!=y[k]}=={field}and y[field]==expected[name],'compressed mutation spec differs '+name);require(reason(name),'missing exact rejection reason')
with tempfile.TemporaryDirectory()as d:
 p=Path(d)/'bytes.gz';raw=b'\x00\xff\n\r"\\'+bytes(range(256))*13
 with gzip.open(p,'wb')as f:f.write(raw)
 require(decoded_identity(p)==(hashlib.sha256(raw).hexdigest(),len(raw)),'lossless gzip round trip')
print(json.dumps(dict(status='PASS_COMPRESSED_CONTROL_SOURCE_AND_LOSSLESS_BYTES',mutation_specifications=7,actual_trace_controls='PENDING_NEW_RUNTIME',DUT_executed=False)))
# Verify rejection through the actual compressed-control verifier, including
# gzip stream failures and candidate identity. Fixtures are synthetic tiny bytes.
from proof_controls_compressed import verify
from contract import sha
import proof_controls_compressed as pc
rejects=[]
with tempfile.TemporaryDirectory()as d:
 root=Path(d);candidate=root/'candidate.json';candidate.write_text(json.dumps(dict(side='on',artifacts={'positive.proof.jsonl':'a'*64})))
 entries=[]
 for name,field in CHANGES:
  p=root/(name+'.jsonl.gz')
  with gzip.open(p,'wb')as f:f.write(raw)
  entries.append(dict(name=name,rejected=True,mutation_count=1,reason=reason(name),expected_reason=reason(name),gzip_path=str(p),gzip_sha256=sha(p),gzip_size=p.stat().st_size,sha256=hashlib.sha256(raw).hexdigest(),uncompressed_size=len(raw)))
 r=dict(status='PASS_ACTUAL_TRACE_IDENTITY_PERMISSION_EDGE_NEGATIVES',schema='lossless-compressed-actual-proof-controls-v1',side='on',source_trace_sha256='a'*64,candidate_receipt_sha256=sha(candidate),validator_sha256=sha(Path(pc.__file__).with_name('proof_trace.py')),runner_sha256=sha(pc.__file__),original_control_spec_sha256=sha(Path(pc.__file__).with_name('test_proof_trace.py')),controls=entries)
 receipt=root/'receipt.json'
 def put(v):receipt.write_text(json.dumps(v))
 put(r);verify(receipt,candidate)
 import copy
 for name,field,value in [('wrong_side','side','off'),('wrong_source','source_trace_sha256','b'*64)]:
  q=copy.deepcopy(r);q[field]=value;put(q)
  try:verify(receipt,candidate)
  except RuntimeError as e:require(str(e)=='controls raw/side mismatch','wrong identity rejection');rejects.append(name)
  else:raise AssertionError(name+' escaped')
 original=Path(entries[0]['gzip_path']).read_bytes()
 for name,bad in [('corrupt_gzip',b'NO'+original[2:]),('truncated_gzip',original[:-5])]:
  p=Path(entries[0]['gzip_path']);p.write_bytes(bad);q=copy.deepcopy(r);q['controls'][0].update(gzip_sha256=sha(p),gzip_size=len(bad));put(q)
  try:verify(receipt,candidate)
  except (OSError,EOFError):rejects.append(name)
  else:raise AssertionError(name+' escaped')
  p.write_bytes(original)
print(json.dumps(dict(status='PASS_COMPRESSED_VERIFIER_CORRUPTION_AND_IDENTITY_CONTROLS',rejections=rejects,DUT_executed=False)))
