"""Tiny real gzip/disk-restoration guards; no original raw or DUT is touched."""
import copy,gzip,hashlib,json,os,tempfile
from pathlib import Path
import raw_storage as s
controls=[]
def reject(name,fn,reason,kind=RuntimeError):
 try:fn()
 except kind as e:
  assert reason in str(e),(name,str(e));controls.append(dict(name=name,status='REJECTED',reason=str(e)))
 else:raise AssertionError('escaped '+name)
with tempfile.TemporaryDirectory()as d:
 root=Path(d);gz=root/'tiny.gz';raw=bytes(range(256))*13+b'\x00\xff\n\r"\\'
 with gzip.open(gz,'wb')as f:f.write(raw)
 e=dict(logical_path=str(root/'original'),logical_sha256=hashlib.sha256(raw).hexdigest(),logical_size=len(raw),mode=0o640,mtime_ns=1_700_000_000_000_000_000,gzip_path=str(gz),gzip_sha256=s.sha(gz),gzip_size=gz.stat().st_size,actual_fresh_restore_verified=True)
 # Regular evidence created by the runners uses only these declared modes.
 e['mode']=0o644;s.entry(e);restored=s.restore_entry(e,root/'restored');assert restored.read_bytes()==raw
 reject('existing_restore_destination',lambda:s.restore_entry(e,restored),'fresh destination')
 for name,field,value,reason in [('wrong_compressed_SHA','gzip_sha256','0'*64,'gzip identity'),('wrong_logical_SHA','logical_sha256','0'*64,'logical bytes'),('wrong_logical_size','logical_size',len(raw)+1,'logical bytes'),('missing_actual_restore','actual_fresh_restore_verified',False,'restore/mode'),('unsupported_mode','mode',0o777,'restore/mode')]:
  bad=copy.deepcopy(e);bad[field]=value;reject(name,lambda bad=bad:s.entry(bad),reason)
 st=restored.stat();identity=dict(device=st.st_dev,inode=st.st_ino,mtime_ns=st.st_mtime_ns,logical_size=st.st_size,mode=st.st_mode&0o777);s.regular(restored,identity)
 bad=copy.deepcopy(identity);bad['inode']+=1;reject('wrong_inode',lambda:s.regular(restored,bad),'inode/device')
 link=root/'symlink';link.symlink_to(restored);reject('symlink_original',lambda:s.regular(link),'regular non-symlink');link.unlink()
 link=root/'hardlink';os.link(restored,link);reject('multiple_links',lambda:s.regular(restored),'single-link');link.unlink()
 archive=root/'archive.tar';archive.write_bytes(b'tiny synthetic archive for xattr guard')
 os.setxattr(archive,'user.library-file-id',b'libfile_synthetic_control');os.setxattr(archive,'user.library-file-version',b'0')
 confirmation=dict(archive_path=str(archive),archive_sha256=s.sha(archive),library_file_id='libfile_synthetic_control',library_version=0,all_members_verified=True);s.library_archive(confirmation)
 bad=copy.deepcopy(confirmation);bad['library_file_id']='libfile_wrong';reject('wrong_Library_id',lambda:s.library_archive(bad),'Library xattrs')
 bad=copy.deepcopy(confirmation);bad['library_version']=1;reject('wrong_Library_version',lambda:s.library_archive(bad),'Library xattrs')
 original=gz.read_bytes();gz.write_bytes(original[:-4]);bad=copy.deepcopy(e);bad.update(gzip_sha256=s.sha(gz),gzip_size=gz.stat().st_size)
 reject('truncated_member',lambda:s.entry(bad),'',EOFError);gz.write_bytes(original)
 candidate=root/'candidate.json';candidate.write_text(json.dumps(dict(schema='posted-preparation-priority-cpu-case-v1',status='SCOPED_PASS_WITH_BOUNDARY_JOIN_UNKNOWN',side='on',case=21)))
 manifest=root/'manifest.json';r=dict(schema=s.SCHEMA,status=s.STATUS,runner_sha256=s.sha(s.__file__),candidate_receipt_path=str(candidate),candidate_receipt_sha256=s.sha(candidate));manifest.write_text(json.dumps(r))
 reject('cannot_archive_ON',lambda:s.verify(manifest,candidate),'only supports completed reproduced OFF')
 r['candidate_receipt_sha256']='0'*64;manifest.write_text(json.dumps(r));reject('wrong_terminal_SHA',lambda:s.verify(manifest,candidate),'binds another terminal')
print(json.dumps(dict(status='PASS_SMALL_LOSSLESS_STORAGE_AND_FRESH_DISK_RESTORE_CONTROLS',actual_roundtrip=True,rejections=controls,DUT_executed=False,original_raw_removed=False),indent=2))
