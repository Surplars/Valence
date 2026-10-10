#!/usr/bin/env python3
"""Semantic corruptions of throwaway hardlinked exports; never modifies evidence."""
import copy,difflib,json,os,shutil,subprocess,sys,tempfile
from pathlib import Path
import run_native as b
import audit_native as audit
h=b.HERE;c=b.load('negative_native_reachable',h/'helpers/reachable_census.py');source=h/'execution/on';receipt=b.read(source/'receipt.json');before={n:b.sha(source/n)for n in receipt['rtl_sha256']};helper='rtl/pcBank_32x64.sv';raw=(source/helper).read_text();rows=[]
cases={'wrong_issue_depth':('Memory[0:31]','Memory[0:30]','fixed'),'extra_helper_port':('  input  [4:0]  R0_addr,','  input         unexpected_probe,\n  input  [4:0]  R0_addr,','reachable'),'extra_helper_array':('  reg [63:0] Memory[0:31];','  reg [63:0] Memory[0:31];\n  reg [7:0] Unexpected[0:3];','reachable'),'wrong_helper_array_width':('  reg [63:0] Memory[0:31];','  reg [64:0] Memory[0:31];','fixed')}
for label,(old,new,expected)in cases.items():
 assert raw.count(old)==1;changed=raw.replace(old,new)
 with tempfile.TemporaryDirectory(prefix='negative-',dir=h)as temp:
  d=Path(temp)/'export';d.mkdir();shutil.copytree(source/'rtl',d/'rtl',copy_function=os.link)
  for n in ['receipt.json','actual-parameters.json','profile.json']:shutil.copy2(source/n,d/n)
  (d/helper).unlink();(d/helper).write_text(changed);r=b.read(d/'receipt.json');r['rtl_sha256'][helper]=b.sha(d/helper);b.save(d/'receipt.json',r)
  fixed=subprocess.run([sys.executable,'-B',str(h/'helpers/native_storage_census_bound_rob64.py'),'--rtl',str(d/'rtl'),'--output',str(Path(temp)/'fixed.json')],capture_output=True,text=True);err=None
  try:c.extend(d)
  except Exception as e:err=str(e)
  assert fixed.returncode!=0 if expected=='fixed'else err,(label,'mutation accepted')
  rows.append(dict(case=label,status='PASS_SEMANTIC_MUTATION_REJECTED',original_sha256=b.sha(source/helper),mutated_sha256=b.sha(d/helper),receipt_rebound_to_mutated_bytes=True,fixed_exit=fixed.returncode,reachable_error=err,fixed_error=fixed.stderr[-1600:]))
with tempfile.TemporaryDirectory(prefix='cycle-negative-',dir=h)as d:
 p=Path(d)/'IntegerBackend.sv';text=(source/'rtl/IntegerBackend.sv').read_text();p.write_text(text.replace('endmodule','  wire injected_a = injected_b;\n  wire injected_b = injected_a;\nendmodule'))
 try:audit.combinational_graph(p)
 except RuntimeError as e:assert 'cycle'in str(e);rows.append(dict(case='backend_combinational_cycle',status='PASS_SEMANTIC_MUTATION_REJECTED',error=str(e)))
 else:raise AssertionError('cycle accepted')
assert before=={n:b.sha(source/n)for n in receipt['rtl_sha256']}
b.save(h/'analysis/negative-controls.json',dict(status='PASS_FIVE_SEMANTIC_MUTATIONS_REJECTED',checker_sha256=b.sha(__file__),original_exports_unchanged=True,cases=rows));print('PASS_FIVE_SEMANTIC_MUTATIONS_REJECTED')
