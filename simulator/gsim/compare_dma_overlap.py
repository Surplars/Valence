#!/usr/bin/env python3
"""Validate exact same-source overlap comparisons and useful payload accounting."""
import argparse,csv,hashlib,json,math
from pathlib import Path
MODES={'line1':'integrated-d1-y0','line2':'integrated-d2-y0','line4':'integrated-d4-y0','line4-yield4':'integrated-d4-y4','line4-yield16':'integrated-d4-y16'}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path('build/gsim'));p.add_argument('--output',type=Path,default=Path('build/dma-overlap-comparison.json'));a=p.parse_args()
 inputs={k:a.root/('dma-overlap-'+v)/'receipt.json' for k,v in MODES.items()};r={k:json.loads(v.read_text()) for k,v in inputs.items()};base=r['line1']
 for name,x in r.items():
  assert x['status']=='PASS' and x['clock_MHz']==100 and x['source_sha256']==base['source_sha256']
  assert len(x['cases'])==42 and len(x['combined'])==12 and len(x['cpu_only'])==3
  assert x['cpu_only']==base['cpu_only']
  for row,b in zip(x['cases'],base['cases']):
   assert all(row[k]==b[k] for k in ['bytes','mode','profile','oracle_latency'])
   assert abs(row['payload_MiBps']-row['bytes']*100000000/1048576/row['cycles'])<1e-8
   assert row['axi_read_bytes']==b['axi_read_bytes'] and row['axi_write_bytes']==b['axi_write_bytes']
   if row['mode']<2:assert row['axi_read_bytes']==row['axi_write_bytes']==row['bytes']
  for row,b in zip(x['combined'],base['combined']):
   assert all(row[k]==b[k] for k in ['bytes','cpu','warm','operations','cpu_payload_bytes','full_axi_read_bytes','full_axi_write_bytes'])
   assert row['full_makespan_cycles']==row['cycles']+row['completion_control_cycles']+row['flush_tail_cycles']
   assert abs(row['full_aggregate_useful_MiBps']-(row['bytes']+row['cpu_payload_bytes'])*100000000/1048576/row['full_makespan_cycles'])<1e-5
 rows=[]
 for name,x in r.items():
  for row,b in zip(x['combined'],base['combined']):
   rows.append({'mode':name,**row,'speedup_vs_line1_full':b['full_makespan_cycles']/row['full_makespan_cycles'],'balanced':row['bytes']==row['cpu_payload_bytes']})
 report={'status':'PASS_EXACT_SOURCE_PAIRED_ACCOUNTING','clock_MHz':100,'reference':'line1','scope':'Synthetic CPU DataPort workloads and delayed host DDR; no executed CPU, physical DDR or routed timing claim.','source_sha256':base['source_sha256'],'receipts':{k:{'path':str(v),'sha256':hashlib.sha256(v.read_bytes()).hexdigest()} for k,v in inputs.items()},'isolated':{k:[c for c in x['cases'] if c['mode']==0 and c['profile'] in [0,1]] for k,x in r.items()},'combined':rows,'cpu_only_equal':True,'all_fixed_work_full_AXI_bytes_equal':True}
 a.output.write_text(json.dumps(report,indent=2)+'\n')
 with a.output.with_suffix('.csv').open('w') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 print(report['status'])
if __name__=='__main__':main()
