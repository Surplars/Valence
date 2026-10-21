#!/usr/bin/env python3
import gzip, hashlib, json
from pathlib import Path
p=Path(__file__).resolve().parent
sha=lambda b:hashlib.sha256(b).hexdigest()
raw=gzip.decompress((p/'eada605-guest-receipt.json.gz').read_bytes())
base=json.loads(raw);d=json.loads((p/'eada605-banner-receipt.delta.json').read_text())
assert sha(raw)==d['base_uncompressed_sha256']
banner={k:d['values'][k] if k in d['values'] else base[k] for k in d['key_order']}
assert sha((json.dumps(banner,indent=2)+'\n').encode())==d['reconstructed_sha256']
for name in ['guest.log','uart.log','drop-b.log','drop-read.log']:
    assert sha((p/('eada605-'+name)).read_bytes())==base['artifact_sha256'][name]
assert sha((p/'eada605-firmware.log').read_bytes())==banner['artifact_sha256']['firmware.log']
history=json.loads((p/'366a643-historical-runs.json').read_text())
for run,prefix,names in [('positive-r2','366a643-initial',['guest.log']),('positive-r3','366a643',['guest.log']),('negatives-r2','366a643',['uart.log','drop-b.log','drop-read.log']),('banner-r2','366a643',['firmware.log'])]:
    for name in names:
        assert sha((p/(prefix+'-'+name)).read_bytes())==history[run]['record_without_large_maps']['artifact_sha256'][name]
assert base['status']=='PASS_COMMON_CPU_NATIVE_SHORT_BOOT'
assert banner['status']=='PASS_COMMON_CPU_NATIVE_FIRMWARE_BANNER'
assert history['banner-r2']['record_without_large_maps']['status']=='FAIL'
assert history['banner-r2']['record_without_large_maps']['results'][0]['timed_out']
print('PASS: exact current receipt reconstruction/log hashes and preserved historical failure logs; not a hardware rerun or aggregate qualification.')
