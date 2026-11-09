from pathlib import Path
import json,re,hashlib
import sys
assert len(sys.argv) == 2, "work directory required"
D=Path(sys.argv[1]).resolve();wave=json.loads((D/'negative.wave.json').read_text());values={}
for s in wave['signal']:
 raw=s.get('data',[''])[0] if s['wave'].startswith('=') else s['wave'][0]
 assert raw and set(raw)<=set('01'),s
 values[s['name']]=int(raw,2)
fixed=json.loads((D/'NEGATIVE_ASSIGNMENT.json').read_text())['assignment']
for n,v in fixed.items():assert values[n]==v,(n,values.get(n),v)
assert {n:values[n] for n in ['old_valid','new_valid','mutated_valid','mutant_ok']}=={'old_valid':0,'new_valid':0,'mutated_valid':1,'mutant_ok':0}
B=json.loads((D/'ACTUAL_CUT_BINDING.json').read_text());actual={}
for r in ['off','on']:
 m=json.loads((D/(r+'-netlist.json')).read_text())['modules']['DataTranslationAdapter'];known={};drivers={};visited=set()
 for p,v in m['ports'].items():
  if v['direction']=='input':
   for i,b in enumerate(v['bits']):
    if isinstance(b,int):known[b]=(values[p]>>i)&1
 for i,s in enumerate(B[r]['states']):
  for j,b in enumerate(s['connections']['Q']):known[b]=(values['q'+str(i)]>>j)&1
 for cn,c in m['cells'].items():
  if c['type'] not in ['$dff','$scopeinfo']:
   for p,bs in c['connections'].items():
    if c['port_directions'][p]=='output':
     for i,b in enumerate(bs):
      if isinstance(b,int):drivers[b]=(cn,p,i)
 def vector(bs):return sum(bit(b)<<i for i,b in enumerate(bs))
 def bit(b):
  if isinstance(b,str):assert b in ['0','1'];return int(b)
  if b in known:return known[b]
  cn,p,i=drivers[b];visited.add(cn);c=m['cells'][cn];t=c['type'];con=c['connections']
  if t=='$mux':v=vector(con['B'] if vector(con['S']) else con['A'])
  else:
   a=vector(con['A']);bv=vector(con['B']) if 'B' in con else 0
   if t=='$and':v=a&bv
   elif t=='$or':v=a|bv
   elif t=='$not':v=~a
   elif t=='$logic_not':v=int(not a)
   elif t=='$reduce_or':v=int(bool(a))
   elif t=='$reduce_and':v=int(a==(1<<len(con['A']))-1)
   elif t=='$eq':v=int(a==bv)
   elif t=='$ne':v=int(a!=bv)
   else:raise AssertionError(('unexpected actual physical-valid cone primitive',t,cn))
  known[b]=(v>>i)&1;return known[b]
 result=vector(m['ports']['io_physical_request_valid']['bits']);assert result==0
 assert not any('nextAllowed_' in n for n in visited),'negative valid claim must not depend on symbolic helper result'
 actual[r]={'actual_physical_valid':result,'cells_evaluated':sorted(visited),'helper_output_not_used':True}
(D/'NEGATIVE_DECODE.json').write_text(json.dumps({'status':'PASS_EXACT_OBSERVATION_COUNTEREXAMPLE','all_fixed_input_buses_checked':len(fixed),'values':{n:values[n] for n in ['old_valid','new_valid','mutated_valid','mutant_ok']},'actual_original_graph_evaluation':actual,'scope':'Only candidate physical-valid observation flipped; no RTL/helper mutation. Real original physical-valid cone independently evaluated at complete zero Q/input valuation; does not use abstract helper results.','wave_sha256':hashlib.sha256((D/'negative.wave.json').read_bytes()).hexdigest()},indent=2)+'\n')
print('PASS',len(fixed),actual)
