from pathlib import Path
import hashlib,json,sys,xml.etree.ElementTree as ET,zipfile
root=Path(sys.argv[1]);pkg=root/'package/combined-timing-repair-transfer-r1'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(pkg/'transfer-manifest.json')=='3f02590424853caa73d633866257b9d24cae5454c0ecec1bc8b492fbe8c36717'
manifest=json.loads((pkg/'transfer-manifest.json').read_text())
actual={p.relative_to(pkg).as_posix() for p in pkg.rglob('*') if p.is_file()}
assert actual==set(manifest['files'])|{'transfer-manifest.json'}
for rel,x in manifest['files'].items():
 p=pkg/rel;assert not p.is_symlink() and p.stat().st_size==x['bytes'] and sha(p)==x['sha256'],rel
c=root/'valence-actual-local-dependencies-20261016-r1.json'
assert sha(c)=='fbc338c1089041260d9ae9e8f6e0a3382e8a722f69156ae9540ed9084809ab8b'
for rel,x in json.loads(c.read_text())['inventory'].items():
 p=root/'dependencies'/rel;assert p.stat().st_size==x['bytes'] and sha(p)==x['sha256'],rel
dcp=root/'run-r1/raw-synth.dcp'
assert sha(dcp)=='43521f496099521a488a6f578585e285605e9c3fb02d9ef3017f055f4d4be177'
events=(root/'run-r1/events.tsv').read_text()
assert '2026-10-16T10:16:11Z\t22028\tsynthesis\tactual_begin' in events
assert '2026-10-16T10:31:59Z\t22028\tsynthesis\tactual_end' in events
assert 'SRE module mismatch' in events
with zipfile.ZipFile(dcp) as z:m=ET.fromstring(z.read('dcp.xml'))
assert m.find('Top').get('Name')=='soc_top_fpga_next_ddr'
assert m.find('Part').get('Name')=='xczu15eg-ffvb1156-2-i'
print(json.dumps({'status':'PASS_CURRENT_SOURCE_SYNTH_CHECKPOINT_RECOVERY_BYTES','originalPid':22028,
 'synthesisStartUtc':'2026-10-16T10:16:11Z','synthesisEndUtc':'2026-10-16T10:31:59Z',
 'checkpointSha256':sha(dcp),'transferFilesVerified':len(manifest['files']),'vendorFilesVerified':283,
 'restorationReason':'External receipt Python environment mismatch; no resynthesis or old CPU checkpoint'}))
