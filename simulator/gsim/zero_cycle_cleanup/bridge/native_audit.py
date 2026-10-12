#!/usr/bin/env python3
"""Exact paired native upper-bank WE delta; no timing or mapped area claim."""
import argparse,hashlib,json,re,difflib
from pathlib import Path
from native_graph_helpers import assignments,cone,ports,registers
from native_slot_audit import audit_slot

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def clean(s):return re.sub(r'//[^\n]*|/\*.*?\*/','',s,flags=re.S)
def tokens(s):return re.findall(r"[A-Za-z_]\w*|\d+'[s]?[bdhoBDHO][a-fA-F0-9_xzXZ]+|\d+|[^\s]",clean(s))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();root=a.root.resolve()
 dirs=[root/s/'rtl' for s in ('off','on')]
 files=[{p.name:sha(p) for p in sorted(d.glob('*.sv'))} for d in dirs]
 assert files[0].keys()==files[1].keys(),'native module set changed'
 changed=[n for n in files[0] if files[0][n]!=files[1][n]]
 assert changed==['TileLinkAxi4BurstBridge.sv'],('unexpected native delta',changed)
 old,new=[(d/'TileLinkAxi4BurstBridge.sv').read_text() for d in dirs]
 evidence=audit_slot(old,new,root/'unexpected-native.diff')
 banks=evidence['bank_connections']
 state={};interface={}
 for name in files[0]:
  x,y=[(d/name).read_text() for d in dirs]
  assert registers(x)==registers(y),('register inventory changed',name)
  sig=lambda t:tokens(t[t.index('module '):t.index(');')+2])
  assert sig(x)==sig(y),('native module ports changed',name)
  state[name]={'registers':len(registers(x)),'bits':sum(registers(x).values())}
  interface[name]=hashlib.sha256(' '.join(sig(x)).encode()).hexdigest()
 memory=(dirs[0]/'payloadBanks_2x72.sv').read_text()
 assert re.search(r'reg\s+\[71:0\]\s+Memory\[0:1\]',memory)
 assert len(re.findall(r'\bW0_en\b',memory))==2 and 'W1_' not in memory
 manager=(dirs[0]/'TileLinkAxi4OutstandingBridge.sv').read_text()
 assert len(re.findall(r'\bTileLinkAxi4BurstBridge\s+slots_\d+\s*\(',manager))==4
 result={'status':'PASS_NATIVE_LOCAL_PAYLOAD_ENABLE','files':dict(zip(('off','on'),files)),
  'changed_modules':changed,'native_module_count':len(files[0]),'bank_connections':banks,
  'all_other_native_tokens_identical':True,'all_state_and_interfaces_identical':True,
  'new_local_wires':evidence['new_local_wires'],'reviewed_optimizer_normalizations':evidence['reviewed_optimizer_normalizations'],
  'exact_continued_event_proof':evidence['exact_continued_event_proof'],'exact_upper_bank_decodes_proven':evidence['exact_upper_bank_decodes_proven'],'state':state,'interfaces':interface,
  'memory':{'slots':4,'banks_per_slot':8,'rows_per_bank':2,'bits_per_row':72,'payload_bits':4608,'write_ports_per_bank':1},
  'bank0_generic_control_preserved':True,'data_and_row_connections_preserved':True,
  'audit_sha256':sha(Path(__file__)),
  'limitations':['Component native RTL, not mapped LUT/cells/area or physical timing evidence.',
   'Upper-bank WE excludes direct local opcode/size/address/range; hierarchical A.valid admission remains.',
   'DATA and row-address cones are unchanged and reported separately; first-request row cone remains.']}
 (root/'audit.json').write_text(json.dumps(result,indent=2)+'\n');print(result['status'])
if __name__=='__main__':main()
