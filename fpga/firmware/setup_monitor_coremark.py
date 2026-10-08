#!/usr/bin/env python3
"""Restore only the small pinned official CoreMark dependency, with archive SHA256."""
import argparse,hashlib,io,pathlib,tarfile,urllib.request
from build_monitor_diag import MD5,REV
SHA='4067e7f260218df13f2875d8f821a8ff32a84153c6e0759d7c89f96c0a8bf987'
URL='https://codeload.github.com/eembc/coremark/tar.gz/'+REV
root=pathlib.Path(__file__).resolve().parents[2]
def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--fetch',action='store_true');args=ap.parse_args()
 dest=root/'simulator/build/coremark-src'
 if args.fetch:
  data=urllib.request.urlopen(URL,timeout=60).read()
  if hashlib.sha256(data).hexdigest()!=SHA:raise RuntimeError('official archive SHA256 mismatch')
  dest.mkdir(parents=True,exist_ok=True)
  with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
   for name in (*MD5,'LICENSE.md'):
    member=archive.getmember('coremark-'+REV+'/'+name)
    if not member.isfile():raise RuntimeError('unexpected dependency member type')
    (dest/name).write_bytes(archive.extractfile(member).read())
 for name,expected in MD5.items():
  if not (dest/name).is_file() or hashlib.md5((dest/name).read_bytes()).hexdigest()!=expected:raise RuntimeError('missing/modified dependency; run setup_monitor_coremark.py --fetch')
 print('COREMARK_PIN_PASS revision='+REV+' archive_sha256='+SHA+' algorithms_unmodified=1')
if __name__=='__main__':main()
