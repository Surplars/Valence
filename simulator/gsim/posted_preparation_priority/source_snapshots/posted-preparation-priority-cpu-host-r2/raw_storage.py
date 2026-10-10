"""Lossless storage of the ten reproduced new OFF streams, with explicit recovery."""
import argparse,gzip,hashlib,json,os,shutil,tempfile,tarfile,stat
from pathlib import Path
from contract import HERE,read,sha,save,require
SCHEMA='posted-preparation-priority-reproduced-off-raw-storage-v1'
STATUS='PASS_LOSSLESS_GZIP_AND_ACTUAL_FRESH_RESTORE'
def regular(path,identity=None):
 st=Path(path).lstat();require(stat.S_ISREG(st.st_mode)and st.st_nlink==1,'regular non-symlink single-link file required')
 if identity is not None:
  require((st.st_dev,st.st_ino,st.st_mtime_ns,st.st_size,st.st_mode&0o777)==(identity['device'],identity['inode'],identity['mtime_ns'],identity['logical_size'],identity['mode']),'original inode/device/mtime/size/mode differs')
 return st
def fsync_dir(path):
 fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
 try:os.fsync(fd)
 finally:os.close(fd)
def durable_json(path,value):
 path=Path(path)
 with path.open('x')as f:json.dump(value,f,indent=2,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
 fsync_dir(path.parent)
def library_archive(d):
 p=Path(d['archive_path']);regular(p)
 require(os.getxattr(p,'user.library-file-id').decode()==d['library_file_id']and os.getxattr(p,'user.library-file-version').decode()==str(d['library_version']),'actual Library xattrs differ')
 require(d['library_file_id'].startswith('libfile_')and d['archive_sha256']==sha(p)and d['all_members_verified']is True,'durable archive metadata/bytes incomplete')
 return p
def decoded(path):
 h=hashlib.sha256();size=0
 with gzip.open(path,'rb')as f:
  for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk);size+=len(chunk)
 return h.hexdigest(),size

def entry(e):
 path=Path(e['gzip_path']);regular(path);require(sha(path)==e['gzip_sha256']and path.stat().st_size==e['gzip_size'],'stored gzip identity changed')
 require(decoded(path)==(e['logical_sha256'],e['logical_size']),'stored gzip logical bytes changed')
 require(e['actual_fresh_restore_verified']is True and e['mode']in(0o644,0o664,0o600),'actual restore/mode evidence missing')
 return path

def restore_entry(e,destination):
 target=Path(destination);require(not target.exists(),'restore requires fresh destination');require(target.parent.is_dir(),'restore parent must exist');src=entry(e)
 require(shutil.disk_usage(target.parent).free>e['logical_size']+740*1024**2,'restore bytes plus disk floor unavailable')
 with gzip.open(src,'rb')as f,target.open('xb')as w:
  shutil.copyfileobj(f,w,1<<20);w.flush();os.fsync(w.fileno())
 os.chmod(target,e['mode']);os.utime(target,ns=(e['mtime_ns'],e['mtime_ns']))
 with target.open('rb')as f:os.fsync(f.fileno())
 fsync_dir(target.parent);regular(target)
 require(sha(target)==e['logical_sha256']and target.stat().st_size==e['logical_size']and target.stat().st_mode&0o777==e['mode']and target.stat().st_mtime_ns==e['mtime_ns'],'actual disk restore differs')
 return target

def verify(path,candidate_receipt):
 path=Path(path).resolve();r=read(path);c=Path(candidate_receipt).resolve();candidate=read(c)
 require(r['schema']==SCHEMA and r['status']==STATUS and r['runner_sha256']==sha(__file__),'raw storage schema/source changed')
 require(r['candidate_receipt_path']==str(c)and r['candidate_receipt_sha256']==sha(c),'raw storage binds another terminal')
 require(candidate['schema']=='posted-preparation-priority-cpu-case-v1'and candidate['status']=='SCOPED_PASS_WITH_BOUNDARY_JOIN_UNKNOWN'and candidate['side']=='off'and candidate['case'] in (19,21),'storage only supports completed reproduced OFF COPY')
 if candidate['case']==21:
  require(sha(r['proof_controls_path'])==r['proof_controls_sha256'],'stored proof-control receipt changed')
  from proof_controls_compressed import verify as verify_controls
  verify_controls(r['proof_controls_path'],c)
 else:require(r['proof_controls_path'] is None and r['proof_controls_sha256'] is None,'Bare has no inserted-proof mutation applicability')
 baseline=read(HERE/'BASELINE-REFERENCE.json')[str(candidate['case'])];require(r['baseline_reference_sha256']==sha(HERE/'BASELINE-REFERENCE.json'),'baseline reference changed')
 names=set(baseline['raw_sha256']);require(len(names)==10 and set(r['members'])==names,'exact ten reproduced streams required')
 require(candidate['original_lru_on_reproduction']==dict(ticks=baseline['result']['ticks'],flush_tail=baseline['result']['flush_tail'],complete_result_equal=True,original_raw_traces_equal=True,new_execution=True),'complete OFF reproduction missing')
 for name,e in r['members'].items():
  require(name==Path(name).name and e['logical_path']==str(c.parent/name)and e['logical_sha256']==candidate['artifacts'][name]==baseline['raw_sha256'][name],'raw storage logical identity differs '+name)
  require(Path(e['gzip_path']).parent==path.parent and Path(e['gzip_path']).name==name+'.gz','gzip path outside exact storage namespace')
  entry(e)
 return r

def prepare(case,controls,out):
 case=Path(case).resolve();out=Path(out).resolve();require(not out.exists(),'fresh raw storage namespace');receipt=case/'receipt.json';r=read(receipt)
 require(r['schema']=='posted-preparation-priority-cpu-case-v1'and r['status']=='SCOPED_PASS_WITH_BOUNDARY_JOIN_UNKNOWN'and r['side']=='off'and r['case'] in (19,21),'completed new OFF COPY required')
 import run
 from proof_controls_compressed import verify as verify_controls
 run.check(r['pins_path'],r['pins_sha256'])
 if r['case']==21:require(controls is not None,'actual Sv39 proof controls required');verify_controls(controls,receipt)
 else:require(controls is None,'Bare has no inserted-proof controls')
 baseline=read(HERE/'BASELINE-REFERENCE.json')[str(r['case'])];names=sorted(baseline['raw_sha256']);require(len(names)==10,'baseline complete ten streams')
 out.mkdir();members={}
 for name in names:
  p=case/name;st=regular(p);require(sha(p)==baseline['raw_sha256'][name]==r['artifacts'][name],'OFF raw not identical to baseline '+name)
  require(shutil.disk_usage(out).free>st.st_size+740*1024**2,'gzip actual-restore startup budget')
  gz=out/(name+'.gz')
  with p.open('rb')as f,gz.open('xb')as target:
   with gzip.GzipFile(filename='',mode='wb',fileobj=target,mtime=0,compresslevel=1)as z:shutil.copyfileobj(f,z,1<<20)
   target.flush();os.fsync(target.fileno())
  fsync_dir(out)
  e=dict(logical_path=str(p),logical_sha256=sha(p),logical_size=st.st_size,device=st.st_dev,inode=st.st_ino,mode=st.st_mode&0o777,mtime_ns=st.st_mtime_ns,gzip_path=str(gz),gzip_sha256=sha(gz),gzip_size=gz.stat().st_size,actual_fresh_restore_verified=True)
  # A fresh, real temporary file is written and checked before deleting only
  # that temporary restoration. The original stream is retained in prepare.
  tmp=out/(name+'.actual-fresh-restore');restore_entry(e,tmp);tmp.unlink();members[name]=e
  save(out/'progress.json',dict(status='RUNNING',members=members))
 result=dict(schema=SCHEMA,status=STATUS,runner_sha256=sha(__file__),candidate_receipt_path=str(receipt),candidate_receipt_sha256=sha(receipt),proof_controls_path=str(Path(controls).resolve()) if controls else None,proof_controls_sha256=sha(controls) if controls else None,baseline_reference_sha256=sha(HERE/'BASELINE-REFERENCE.json'),members=members,original_raw_removed=False,original_terminal_unchanged=True,restored_atime_policy='Not preserved; verification reads may change access time. Mode and nanosecond mtime are exact.',scope='Only ten new OFF positive streams. Prior parent streams, failures, unique ON data, model and guest are excluded.',restore_contract='Run this pinned script restore with a fresh existing directory, then hash every logical byte before a historical parser. Original-path restoration requires that every destination is absent.')
 save(out/'manifest.json',result,True);verify(out/'manifest.json',receipt);print(json.dumps(dict(status=STATUS,manifest=str(out/'manifest.json'),sha256=sha(out/'manifest.json'))))

def remove(path,confirmation,confirmation_sha):
 path=Path(path).resolve();r=read(path);verify(path,r['candidate_receipt_path']);require(sha(confirmation)==confirmation_sha,'durable confirmation hash changed');d=read(confirmation)
 require(d['status']=='CONFIRMED_DURABLE_VERIFIED_OFF_GZIP_ARCHIVE'and d['storage_manifest_sha256']==sha(path),'durable storage confirmation missing')
 library_archive(d)
 expected=sorted(e['logical_path']for e in r['members'].values());require(sorted(d['authorizes_exact_raw_paths'])==expected,'removal authorization scope differs')
 require(set(d['archive_gzip_members'])==set(r['members']),'durable archive gzip inventory differs')
 wanted={d['archive_manifest_member']:(sha(path),path.stat().st_size)}
 for n,e in r['members'].items():
  member=d['archive_gzip_members'][n];require(member not in wanted,'duplicate durable member mapping');wanted[member]=(e['gzip_sha256'],e['gzip_size'])
 seen=set()
 with tarfile.open(d['archive_path'],'r|*')as tf:
  for member in tf:
   if member.name not in wanted:continue
   require(member.name not in seen and member.isfile(),'durable mapped member must be unique regular');seen.add(member.name);h=hashlib.sha256();size=0
   with tf.extractfile(member)as stream:
    for chunk in iter(lambda:stream.read(1<<20),b''):h.update(chunk);size+=len(chunk)
   require((h.hexdigest(),size)==wanted[member.name],'durable archive gzip/manifest bytes differ')
 require(seen==set(wanted),'durable archive missing gzip/manifest member')
 out=path.parent/'removal-receipt.json';require(not out.exists(),'raw removal already recorded')
 # Verify all originals before any removal. All gzip members have just been
 # fully decoded, and the explicit durable confirmation binds their manifest.
 for e in r['members'].values():
  p=Path(e['logical_path']);regular(p,e);require(sha(p)==e['logical_sha256'],'original before removal differs')
 journal=path.parent/'removal-journal';require(not journal.exists(),'existing removal journal requires explicit recovery review');journal.mkdir();fsync_dir(path.parent);removed=[]
 for i,(name,e)in enumerate(r['members'].items()):
  p=Path(e['logical_path']);durable_json(journal/f'{i:02d}.intent.json',dict(action='unlink_exact_restorable_raw',name=name,expected=e,manifest_sha256=sha(path),confirmation_sha256=confirmation_sha))
  regular(p,e);require(sha(p)==e['logical_sha256'],'raw changed immediately before unlink');regular(p,e)
  p.unlink();fsync_dir(p.parent);removed.append(name)
  durable_json(journal/f'{i:02d}.done.json',dict(action='unlinked_exact_restorable_raw',name=name,logical_sha256=e['logical_sha256'],original_path_absent=not p.exists()))
 durable_json(out,dict(status='PASS_EXACT_TEN_REPRODUCED_RAW_REVERSIBLY_ARCHIVED',manifest_sha256=sha(path),confirmation_path=str(Path(confirmation).resolve()),confirmation_sha256=confirmation_sha,removed=removed,bytes_released=sum(e['logical_size']for e in r['members'].values()),original_receipt_unchanged=sha(r['candidate_receipt_path'])==r['candidate_receipt_sha256']))

def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='action',required=True)
 q=s.add_parser('prepare');q.add_argument('--case',required=True);q.add_argument('--controls');q.add_argument('--out',required=True)
 for action in('verify','restore','remove'):
  q=s.add_parser(action);q.add_argument('--manifest',required=True)
  if action=='restore':q.add_argument('--fresh-root',required=True)
  if action=='remove':q.add_argument('--confirmation',required=True);q.add_argument('--confirmation-sha',required=True)
 a=p.parse_args()
 if a.action=='prepare':prepare(a.case,a.controls,a.out)
 elif a.action=='remove':remove(a.manifest,a.confirmation,a.confirmation_sha)
 else:
  r=read(a.manifest);verify(a.manifest,r['candidate_receipt_path'])
  if a.action=='restore':
   root=Path(a.fresh_root);require(root.is_dir(),'fresh-root must already exist');require(not any((root/n).exists()for n in r['members']),'all restore destinations must be absent')
   for n,e in r['members'].items():restore_entry(e,root/n)
  print(STATUS)
if __name__=='__main__':main()
