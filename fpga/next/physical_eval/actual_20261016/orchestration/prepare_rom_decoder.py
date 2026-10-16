from pathlib import Path
import hashlib,json,os,sys
root=Path(sys.argv[1]);stage=sys.argv[2];checkpoint=Path(sys.argv[3])
work=checkpoint.parent/('rom-decoder-'+stage)
work.mkdir()
(work/'firmware').mkdir();(work/'synthesis').mkdir()
raw=(root/'dependencies/firmware/bootrom.bin').read_bytes()
assert hashlib.sha256(raw).hexdigest()=='ee7c2e5fb86d50dad55df532aeb7ccb1d0b91cb37b0b7042d03b446eee362d79'
(work/'firmware/bootrom.bin').write_bytes(raw)
os.link(checkpoint,work/'synthesis/post_synth_unconstrained.dcp')
print(str(work).replace('\\','/'))
