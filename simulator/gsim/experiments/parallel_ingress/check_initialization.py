from pathlib import Path
import json,hashlib
import sys
assert len(sys.argv) == 2, "work directory required"
D=Path(sys.argv[1]).resolve();B=json.loads((D/'ACTUAL_CUT_BINDING.json').read_text());results={}
for r in ['off','on']:
 m=json.loads((D/(r+'-netlist.json')).read_text())['modules']['DataTranslationAdapter'];q={b for s in B[r]['states'] for b in s['connections']['Q']};found={}
 for n,v in m['netnames'].items():
  if 'init' in v.get('attributes',{}):
   bits=v['bits'];value=v['attributes']['init'];assert len(bits)==len(value)
   for b,x in zip(bits,value[::-1]):
    if b in q:
     assert b not in found or found[b]==x;found[b]=x
 results[r]={'state_bits':len(q),'init_bits':found,'state_order_initializers':[[found.get(b,None) for b in s['connections']['Q']] for s in B[r]['states']]}
assert results['off']['state_order_initializers']==results['on']['state_order_initializers']
(D/'INITIALIZATION_BINDING.json').write_text(json.dumps({'status':'MATCH_ALL_ACTUAL_STATE_INITIALIZATION','sides':results,'missing_init':'No initialization constraint; arbitrary shared Q is retained.','netlist_sha256':{r:hashlib.sha256((D/(r+'-netlist.json')).read_bytes()).hexdigest() for r in results}},indent=2)+'\n')
print({r:len(v['init_bits'])for r,v in results.items()})
