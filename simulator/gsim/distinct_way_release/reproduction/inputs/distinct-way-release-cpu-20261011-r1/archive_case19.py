#!/usr/bin/env python3
"""Bounded unique ON19 raw archive, exact streaming member verification; no deletion."""
from pathlib import Path
import gzip,hashlib,io,json,os,shutil,stat,tarfile
HERE=Path(__file__).resolve().parent;CASE=HERE/'case19';CAP=128*1024**2;FLOOR=700*1024**2
read=lambda p:json.loads(Path(p).read_text())
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb')as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def save(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
class GuardedWriter:
 def __init__(self,f):self.f=f
 def write(self,b):
  if self.f.tell()+len(b)>CAP:raise RuntimeError('128MiB_archive_cap')
  if shutil.disk_usage(HERE).free<FLOOR:raise RuntimeError('700MiB_floor')
  return self.f.write(b)
 def flush(self):return self.f.flush()
 def tell(self):return self.f.tell()
def main():
 q=read(CASE/'qualification.json');assert q['status']=='PASS_SCOPED_ORIGINAL_ORACLES'and q['full_parser_executed']
 raw=read(HERE/'pins.json')['baseline_raw'];names=sorted(raw)
 assert len(names)==18 and all((CASE/n).is_file()for n in names)
 # All other unique case receipts, logs and resource samples; derived lifetimes can be regenerated.
 names+=sorted(p.name for p in CASE.iterdir()if p.is_file()and p.name not in raw and not p.name.endswith('.lifetimes.jsonl'))
 records={}
 for n in names:
  f=CASE/n;st=f.stat();records['distinct-way-release-cpu-20261011-r1/case19/'+n]={'sha256':sha(f),'bytes':st.st_size,'mode':stat.S_IMODE(st.st_mode),'mtime_ns':st.st_mtime_ns}
 manifest={'schema':'distinct-way-release-on19-unique-archive-v1','raw_member_count':18,'baseline_members_included':False,'model_members_included':False,'caps':{'archive_bytes':CAP,'free_floor_bytes':FLOOR},'qualification_sha256':sha(CASE/'qualification.json'),'members':records}
 mp=HERE/'case19-on-archive-manifest.json';assert not mp.exists();save(mp,manifest)
 archive=HERE/'distinct-way-release-case19-on-20261011-r1.tar.gz';assert not archive.exists()
 with archive.open('xb')as disk:
  with gzip.GzipFile(fileobj=GuardedWriter(disk),mode='wb',compresslevel=1,mtime=0)as gz:
   with tarfile.open(fileobj=gz,mode='w|',format=tarfile.PAX_FORMAT)as tar:
    for name,r in records.items():
     f=CASE/Path(name).name;info=tar.gettarinfo(str(f),arcname=name);info.pax_headers['mtime']=str(r['mtime_ns']//10**9)+'.'+str(r['mtime_ns']%10**9).zfill(9)
     with f.open('rb')as source:tar.addfile(info,source)
    tar.add(mp,arcname='distinct-way-release-cpu-20261011-r1/case19-on-archive-manifest.json',recursive=False)
 verified={}
 with tarfile.open(archive,mode='r|gz')as tar:
  for member in tar:
   assert member.isfile()and member.name not in verified
   f=tar.extractfile(member);h=hashlib.sha256();size=0
   for b in iter(lambda:f.read(1<<20),b''):h.update(b);size+=len(b)
   if member.name in records:
    r=records[member.name];expected_mtime=str(r['mtime_ns']//10**9)+'.'+str(r['mtime_ns']%10**9).zfill(9)
    assert h.hexdigest()==r['sha256']and size==r['bytes']and member.mode==r['mode']and member.pax_headers['mtime']==expected_mtime,member.name
   else:assert member.name=='distinct-way-release-cpu-20261011-r1/case19-on-archive-manifest.json'and h.hexdigest()==sha(mp)
   verified[member.name]={'sha256':h.hexdigest(),'bytes':size,'mode':member.mode,'mtime':member.pax_headers.get('mtime',str(member.mtime))}
 assert set(verified)==set(records)|{'distinct-way-release-cpu-20261011-r1/case19-on-archive-manifest.json'}
 receipt={'status':'PASS_STREAM_ALL_MEMBERS_EXACT_SHA_SIZE_MODE_MTIME','archive':str(archive),'sha256':sha(archive),'bytes':archive.stat().st_size,'manifest_sha256':sha(mp),'raw_member_count':18,'verified_members':verified,'raw_deleted':False,'delete_gate':'Parent verified persistent Library ID required'}
 save(HERE/'case19-on-archive-receipt.json',receipt);print(json.dumps({k:v for k,v in receipt.items()if k!='verified_members'},indent=2))
if __name__=='__main__':main()
