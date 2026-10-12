#!/usr/bin/env python3
"""Fail-closed exact combined native delta against the qualified 611 board."""
import argparse,hashlib,json,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'components'))
from bridge_native_slot_audit import audit_slot
from registered_operand_endpoint_audit import audit_integer
from native_graph_helpers import registers,ports

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def tokens(s):return re.findall(r'''"(?:\\.|[^"\\])*"|[A-Za-z_]\w*|\d+'[s]?[bdhoBDHO][a-fA-F0-9_xzXZ]+|\d+|[^\s]''',s)
def inventory(d):return {p.name:sha(p) for p in sorted(d.glob('*.sv'))}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--off',type=Path,required=True);ap.add_argument('--on',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
 before,after=inventory(a.off),inventory(a.on)
 assert before.keys()==after.keys() and len(before)==239,'complete native module inventory changed'
 changed=sorted(n for n in before if before[n]!=after[n])
 bridges=[n for n in changed if re.fullmatch(r'TileLinkAxi4BurstBridge(?:_\d+)?\.sv',n)]
 assert bridges and set(changed)=={'IntegerBackend.sv',*bridges},('unreviewed changed modules',changed)
 # Same four-site/comparator proof, at actual inlined fullboard endpoints.
 operand=audit_integer((a.off/'IntegerBackend.sv').read_text(),(a.on/'IntegerBackend.sv').read_text())
 stage=(a.off/'IssueExecuteStage.sv').read_text()
 assert re.search(r'input\s+\[590:0\]\s+io_enq_bits',stage),'actual enqueue width changed'
 bridge_evidence={}
 for name in bridges:
  bridge_evidence[name]=audit_slot((a.off/name).read_text(),(a.on/name).read_text(),a.output.parent/(name+'.unexpected.diff'))
 state={};interfaces={}
 for name in before:
  old,new=[(d/name).read_text() for d in [a.off,a.on]]
  assert registers(old)==registers(new),('retained state differs',name)
  sig=lambda t:tokens(t[t.index('module '):t.index(');')+2])
  assert sig(old)==sig(new),('native module interface differs',name)
  state[name]={'declarations':len(registers(old)),'bits':sum(registers(old).values())}
  interfaces[name]=hashlib.sha256(' '.join(sig(old)).encode()).hexdigest()
 memory=(a.off/'payloadBanks_2x72.sv').read_text()
 assert re.search(r'reg\s+\[71:0\]\s+Memory\[0:1\]',memory) and 'W1_' not in memory
 manager=(a.off/'TileLinkAxi4OutstandingBridge.sv').read_text()
 slottypes=re.findall(r'\b(TileLinkAxi4BurstBridge(?:_\d+)?)\s+slots_(\d+)\s*\(',manager)
 assert sorted(int(i) for _,i in slottypes)==list(range(4)),'actual four-slot native manager missing'
 assert all(kind+'.sv' in bridges for kind,_ in slottypes),'an actual slot variant lacks seven-WE proof'
 assert len(re.findall(r'\bpayloadBanks_2x72\s+payloadBanks_\d+_ext\s*\(', (a.on/bridges[0]).read_text()))==8
 result={'status':'PASS_NATIVE_ZERO_CYCLE_CLEANUP','native_modules':len(before),'changed_modules':changed,
  'files':{'off':before,'on':after},'all_module_ports_identical':True,'all_declared_state_identical':True,
  'state':state,'interfaces':interfaces,'operand':operand,'bridge_variants':bridge_evidence,
  'actual_slot_types':slottypes,'memory':{'slots':4,'banks_per_slot':8,'rows_per_bank':2,'bits_per_row':72,'payload_bits':4608,'write_ports_per_bank':1},
  'audit_sha256':sha(__file__),'limitations':['Native RTL only, no mapped LUT/timing/physical claim.','Upper WE retains hierarchical A.valid admission. DATA, row and bank0 are unchanged.']}
 a.output.write_text(json.dumps(result,indent=2)+'\n');print(result['status'],changed)
if __name__=='__main__':main()
