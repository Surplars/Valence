#!/usr/bin/env python3
"""Check fixed selected-profile native RAM ports; this is not FPGA mapping."""
import argparse,hashlib,json,re
from pathlib import Path
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--rtl',required=True,type=Path)
parser.add_argument('--export-receipt',type=Path)
parser.add_argument('--output',required=True,type=Path)
args=parser.parse_args()
root=args.rtl.resolve()
receipt_path=args.export_receipt or root.parent/'receipt.json'
receipt=json.loads(receipt_path.read_text())
if receipt.get('status')!='PASS_RTL_EXPORT_ONLY':raise RuntimeError('passed native export required')
source_commit=receipt['git_head']
if not re.fullmatch(r'[0-9a-f]{40}',source_commit):raise RuntimeError('invalid export revision')
for relative,digest in receipt['rtl_sha256'].items():
 path=Path(relative)
 if path.parts[0]!='rtl' or '..' in path.parts:raise RuntimeError('unsafe exported artifact path')
 actual=root/Path(*path.parts[1:])
 if hashlib.sha256(actual.read_bytes()).hexdigest()!=digest:raise RuntimeError('export artifact drift: '+relative)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
# This profile adapter derives issue-bank depth from the bound, actual native construction.
full = receipt['full_profile']
actual_path = root.parent / 'actual-parameters.json'
if sha(actual_path) != receipt['actual_parameters_sha256']: raise RuntimeError('actual constructor artifact drift')
actual = json.loads(actual_path.read_text())
core = actual['expectedCore']
if len(core) != 140 or core != full['core'] or actual['entryProfile'] != full['profile']: raise RuntimeError('full actual profile mismatch')
if len(actual['coreParameters']) != 6 or not all(x['values'] == core for x in actual['coreParameters']): raise RuntimeError('actual core values incomplete')
if core['robEntries'] != 64 or core['renameWidth'] != 2 or not core['bankedIssuePayload']: raise RuntimeError('unsupported issue owner bank profile')
if core['robEntries'] % 2: raise RuntimeError('uneven issue owner bank geometry')
issue_bank_depth = core['robEntries'] // 2
def banks(parent,prefix):
 p=root/(parent+'.sv');s=p.read_text();out=[]
 for child,instance in re.findall(r'^  (\w+) (\w+) \(',s,re.M):
  if not re.fullmatch(prefix,instance):continue
  path=root/(child+'.sv');v=path.read_text()
  m=re.search(r'reg\s+\[(\d+):0\]\s+Memory\[0:(\d+)\]',v)
  assert m,(child,'unsupported geometry')
  reads=set(re.findall(r'\bR(\d+)_addr\b',v));writes=set(re.findall(r'\bW(\d+)_addr\b',v))
  latency=int(bool(re.search(r'reg\s+(?:\[[^\]]+\]\s+)?_R0_addr_d0;',v)))
  out.append({'instance':instance,'module':child,'width':int(m[1])+1,'depth':int(m[2])+1,'reads':len(reads),'writes':len(writes),'read_latency':latency,'helper_sha256':sha(path)})
 assert out,(parent,prefix)
 return {'parent':parent,'parent_sha256':sha(p),'banks':out}
result={'status':'PASS_SELECTED_NATIVE_STORAGE_CENSUS','source_commit':source_commit,'export_receipt_sha256':hashlib.sha256(receipt_path.read_bytes()).hexdigest(),'groups':{},'actual_profile_binding':{'actual_parameters_sha256':sha(actual_path),'robEntries':core['robEntries'],'issue_owner_banks':2,'issue_bank_depth':issue_bank_depth},'limits':['Normalized reachable production RTL geometry, not FPGA mapping/resource/frequency','Async multiport memory may require physical replication','I-data bank-way selection retains a tag-to-address path; address qualification is checked separately']}
contracts=[('issue_pc','BankedIssuePayload',r'pcBank[01]_ext',2,64,issue_bank_depth,7,0),('issue_instruction','BankedIssuePayload',r'instructionBank[01]_ext',2,32,issue_bank_depth,3,0),('issue_expanded','BankedIssuePayload',r'expandedInstructionBank[01]_ext',2,32,issue_bank_depth,1,0),('issue_next_pc','BankedIssuePayload',r'predictedNextPcBank[01]_ext',2,64,issue_bank_depth,2,0),('issue_immediate','BankedIssuePayload',r'immediateBank[01]_ext',2,64,issue_bank_depth,4,0),('issue_tval','BankedIssuePayload',r'fetchTvalBank[01]_ext',2,64,issue_bank_depth,2,0),('instruction_data','InstructionLineCache',r'dataBanks_[0-7]_ext',8,64,512,1,1),('instruction_tags','InstructionLineCache',r'tagBanks_[01]_ext',2,19,256,1,0),('data_tags','NonBlockingCoherentLineCache',r'tagBanks_[01]_ext',2,19,256,2,0),('fetch_hints','OwnerBankedFetchHints',r'writerBank[01]_ext',2,162,32,2,0)]
for label,parent,pattern,count,width,depth,reads,latency in contracts:
 row=banks(parent,pattern);assert len(row['banks'])==count,(label,row)
 for b in row['banks']:assert (b['width'],b['depth'],b['reads'],b['writes'],b['read_latency'])==(width,depth,reads,1,latency),(label,b)
 row['logical_payload_bits']=count*width*depth;result['groups'][label]=row
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(result,indent=2)+'\n')
print(result['status'])
