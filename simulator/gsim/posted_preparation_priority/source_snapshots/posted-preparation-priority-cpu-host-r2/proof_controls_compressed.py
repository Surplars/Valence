"""Seven exact actual-trace mutations, full bytes retained in verified gzip members."""
import argparse,gzip,hashlib,json,resource,shutil,time
from pathlib import Path
from contract import require,sha,save
import proof_trace
CHANGES=(('same_index_new_tag','tag'),('wrong_index','index'),('wrong_epoch','epoch'),('wrong_pa_line','pa'),('permission_not_allowed','allowed'),('not_inserted_owner','ownermatches'),('acceptance_not_next_edge','accepted_cycle'))
def mutation(x,name):
 y=x.copy()
 if name=='same_index_new_tag':y['tag']=(x['tag']+1)%2**64
 elif name=='wrong_index':y['index']=x['index']^1
 elif name=='wrong_epoch':y['epoch']=(x['epoch']+1)%2**32
 elif name=='wrong_pa_line':y['pa']=x['pa']^64
 elif name=='permission_not_allowed':y['allowed']=0
 elif name=='not_inserted_owner':y['ownermatches']=0
 elif name=='acceptance_not_next_edge':y['accepted_cycle']=x['cycle']
 else:raise RuntimeError('unknown exact mutation')
 return y
def reason(name):return 'inserted proof missing earlier same-owner query'if name in('same_index_new_tag','wrong_index','wrong_epoch')else 'acceptance must be confirmed following edge'if name=='acceptance_not_next_edge'else 'inserted proof not actual positive permission'
def decoded_identity(gz):
 h=hashlib.sha256();size=0
 with gzip.open(gz,'rb')as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b);size+=len(b)
 return h.hexdigest(),size

def run(folder,out):
 folder=Path(folder).resolve();out=Path(out).resolve();require(not out.exists(),'fresh compressed control namespace');r=json.loads((folder/'receipt.json').read_text())
 require(r['schema']=='posted-preparation-priority-cpu-case-v1'and r['status']=='SCOPED_PASS_WITH_BOUNDARY_JOIN_UNKNOWN'and r['case']==21,'complete fresh actual case21 required')
 raw=folder/'positive.proof.jsonl';require(sha(raw)==r['artifacts'][raw.name],'actual proof raw drift');out.mkdir();report=[];started=time.monotonic()
 for name,field in CHANGES:
  require(shutil.disk_usage(out).free>raw.stat().st_size+740*1024**2,'control plaintext plus disk floor unavailable')
  p=out/(name+'.jsonl');n=0;h=hashlib.sha256();size=0
  with raw.open('rb')as f,p.open('xb')as w:
   for line in f:
    x=proof_trace.decode(line)
    if x['event']=='result'and x['inserted']:
     y=mutation(x,name);require({k for k in x if x[k]!=y[k]}=={field},'mutation changed unexpected fields');line=(json.dumps(y,sort_keys=True)+'\n').encode();n+=1
    w.write(line);h.update(line);size+=len(line)
  require(n>0,'no actual inserted proofs; no zero-mutation control');t=time.monotonic()
  try:proof_trace.validate(p,folder/'positive.canonical.jsonl',(folder/'positive.log').read_text(),r['result'],r['window_trace'])
  except RuntimeError as e:require(str(e)==reason(name),'control rejected for unrelated reason '+name+': '+str(e));diagnostic=str(e)
  else:raise RuntimeError('control escaped '+name)
  original_digest=h.hexdigest();require(sha(p)==original_digest and p.stat().st_size==size,'mutant changed during validator')
  gz=p.with_suffix(p.suffix+'.gz')
  with p.open('rb')as f,gz.open('xb')as target,gzip.GzipFile(filename='',mode='wb',fileobj=target,mtime=0,compresslevel=1)as z:shutil.copyfileobj(f,z,1<<20)
  require(decoded_identity(gz)==(original_digest,size),'gzip exact decompression verification failed')
  entry=dict(name=name,mutation_count=n,rejected=True,reason=diagnostic,expected_reason=reason(name),sha256=original_digest,uncompressed_size=size,gzip_path=str(gz),gzip_sha256=sha(gz),gzip_size=gz.stat().st_size,decoded_bytes_verified=True,validation_seconds=time.monotonic()-t,process_maxrss_KiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
  # This is a newly created, unbound temporary member. Only remove after a full
  # lossless gzip decode has proven every byte and receipt carries restoration.
  p.unlink();entry['temporary_plaintext_removed_after_verification']=True;report.append(entry)
  save(out/'progress.json',dict(status='RUNNING',controls=report))
 require(sha(raw)==r['artifacts'][raw.name],'actual source raw changed')
 result=dict(status='PASS_ACTUAL_TRACE_IDENTITY_PERMISSION_EDGE_NEGATIVES',schema='lossless-compressed-actual-proof-controls-v1',side=r['side'],source_trace_sha256=sha(raw),candidate_receipt_sha256=sha(folder/'receipt.json'),DUT_reexecuted=False,controls=report,streaming_host_only=True,original_control_spec_sha256=sha(folder.parent/'test_proof_trace.py'),runner_sha256=sha(__file__),validator_path=str(folder.parent/'proof_trace.py'),validator_sha256=sha(folder.parent/'proof_trace.py'),all_rejections_exact_expected_reason=True,elapsed_seconds=time.monotonic()-started,process_maxrss_KiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,restore_contract='gzip -dc each pinned gzip_path into a fresh name.jsonl; verify uncompressed size and sha256 before passing that path to the unchanged strict validator; never overwrite an unequal existing path.')
 save(out/'receipt.json',result,True);print(json.dumps(dict(status=result['status'],side=r['side'],controls=len(report),receipt=str(out/'receipt.json'),sha256=sha(out/'receipt.json'))))

def verify(path,candidate_receipt):
 p=Path(path);r=json.loads(p.read_text());require(r['status']=='PASS_ACTUAL_TRACE_IDENTITY_PERMISSION_EDGE_NEGATIVES'and r['schema']=='lossless-compressed-actual-proof-controls-v1','compressed control gate not terminal')
 require(r['candidate_receipt_sha256']==sha(candidate_receipt),'controls bind another CPU run')
 candidate=json.loads(Path(candidate_receipt).read_text());require(r['side']==candidate['side']and r['source_trace_sha256']==candidate['artifacts']['positive.proof.jsonl'],'controls raw/side mismatch')
 require(r['validator_sha256']==sha(Path(__file__).with_name('proof_trace.py'))and r['runner_sha256']==sha(__file__)and r['original_control_spec_sha256']==sha(Path(__file__).with_name('test_proof_trace.py')),'control source identity changed')
 require([x['name']for x in r['controls']]==[x[0]for x in CHANGES],'seven exact controls missing/reordered')
 for x in r['controls']:
  require(x['rejected']and x['mutation_count']>0 and x['reason']==x['expected_reason']==reason(x['name']),'control rejection reason differs')
  gz=Path(x['gzip_path']);require(gz.parent==p.resolve().parent and sha(gz)==x['gzip_sha256']and gz.stat().st_size==x['gzip_size'],'compressed control member drift')
  require(decoded_identity(gz)==(x['sha256'],x['uncompressed_size']),'compressed member full bytes no longer restore')
 return r
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--case',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.case,a.out)
