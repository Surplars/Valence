from pathlib import Path
import json,hashlib,copy
import sys
assert len(sys.argv) == 2, "work directory required"
D=Path(sys.argv[1]).resolve()
H=lambda x:hashlib.sha256(json.dumps(x,sort_keys=True).encode()).hexdigest()
put=lambda n,x:(D/n).write_text(json.dumps(x,indent=2)+'\n')
mods={r:json.loads((D/(r+'-netlist.json')).read_text())['modules']['DataTranslationAdapter'] for r in ['off','on']}
hi={r:json.loads((D/(r+'-hierarchical.json')).read_text())['modules'] for r in mods}
# Canonical helper function from actual unspecialized module ports; raw fault=0 is a parent connection, not a fake input replacing every internal zero.
cert={}
def canon(role,name):
 key=role+'/'+name
 if key in cert:return cert[key]['outputs']
 m=hi[role][name];cs=m['cells'];ins={b:['input',p,i] for p,v in m['ports'].items() if v['direction']=='input' for i,b in enumerate(v['bits'])};drivers={};memo={};used=set()
 for cn,c in cs.items():
  assert c['type'] not in ['$dff','$adff','$dlatch','$memrd','$memwr'],(key,c['type'])
  for p,bs in c['connections'].items():
   if c['port_directions'][p]=='output':
    for i,b in enumerate(bs):
     if isinstance(b,int):assert b not in drivers;drivers[b]=(cn,p,i)
 def tree(b):
  if isinstance(b,str):assert b in ['0','1'],(key,'undef',b);return ['const',b]
  if b in ins:return ins[b]
  if b in memo:return memo[b]
  cn,p,i=drivers[b];c=cs[cn];used.add(cn);typ=c['type'];args={q:[tree(x) for x in bs] for q,bs in sorted(c['connections'].items()) if c['port_directions'][q]=='input'}
  semantics=typ if typ.startswith('$') else ['module',canon(role,typ)]
  val=[semantics,c['parameters'],args,p,i];memo[b]=['node',H(val)];return memo[b]
 out={p:[tree(b) for b in v['bits']] for p,v in m['ports'].items() if v['direction']=='output'}
 def variable_bits(b):
  if isinstance(b,str):assert b in ['0','1'];return set()
  if b in ins:return {b}
  cn,p,i=drivers[b];c=cs[cn];assert c['type'] in ['$add','$mul']
  return set().union(*(variable_bits(x) for p,bs in c['connections'].items() if c['port_directions'][p]=='input' for x in bs))
 def const(b,values):
  if isinstance(b,str):assert b in ['0','1'];return int(b)
  if b in values:return values[b]
  cn,p,i=drivers[b];c=cs[cn];assert c['type'] in ['$add','$mul'];vals={}
  for port in ['A','B']:
   bs=c['connections'][port];v=sum(const(x,values)<<j for j,x in enumerate(bs))
   if int(c['parameters'].get(port+'_SIGNED','0'),2) and v&(1<<(len(bs)-1)):v-=1<<len(bs)
   vals[port]=v
  return ((vals['A']+vals['B'] if c['type']=='$add' else vals['A']*vals['B'])>>i)&1
 shifts=[]
 allowed={'$logic_not','$add','$not','$or','$ge','$gt','$reduce_or','$le','$eq','$ne','$reduce_and','$mul','$lt','$shiftx','$and','$mux'}
 for cn in used:
  c=cs[cn];assert c['type'] in allowed or c['type'] in hi[role],c['type']
  if c['type']=='$shiftx':
   aw=int(c['parameters']['A_WIDTH'],2);yw=int(c['parameters']['Y_WIDTH'],2);bs=c['connections']['B']
   vb=sorted(set().union(*(variable_bits(b) for b in bs)));assert len(vb)<=8
   shifts_actual=[]
   for assignment in range(1<<len(vb)):
    values={b:(assignment>>j)&1 for j,b in enumerate(vb)};v=sum(const(b,values)<<j for j,b in enumerate(bs))
    if int(c['parameters'].get('B_SIGNED','0'),2) and v&(1<<(len(bs)-1)):v-=1<<len(bs)
    assert 0<=v and v+yw<=aw,(key,cn,v,aw,yw);shifts_actual.append(v)
   shifts.append({'cell':cn,'variable_input_bits':vb,'all_indices':shifts_actual,'A_WIDTH':aw,'Y_WIDTH':yw})
 cert[key]={'ports':m['ports'],'outputs':out,'visited_cells':sorted(used),'bit_digests':{str(k):v for k,v in memo.items()},'defined_constant_shiftx':shifts}
 return out
assert canon('off','NextLineAuthorization')==canon('on','NextLineAuthorization')
put('HELPER_FUNCTION_CERTIFICATE.json',{'status':'IDENTICAL_ACTUAL_ORDERED_FUNCTION','modules':cert,'raw_specialization':'io_fault=0 remains explicit actual parent connection; no assumptions on other inputs'})
# Pair every actual FF by an exact whole-Q alias existing on both sides.
state={};qmeta={}
for r,m in mods.items():
 aliases={}
 for n,v in m['netnames'].items():aliases.setdefault(tuple(v['bits']),[]).append(n)
 state[r]={}
 for cn,c in m['cells'].items():
  if c['type']=='$dff':
   bs=tuple(c['connections']['Q']);names=sorted(aliases.get(bs,[]));assert names,(r,cn)
   state[r][cn]=(c,names)
shared=[];taken=set()
for cn,(c,names) in state['off'].items():
 matches=[(nn,cc,sorted(set(names)&set(ns))) for nn,(cc,ns) in state['on'].items() if set(names)&set(ns)]
 assert len(matches)==1,(cn,names,matches);nn,cc,ns=matches[0];assert nn not in taken;taken.add(nn);assert c['parameters']==cc['parameters'];shared.append((ns[0],cn,nn))
assert len(taken)==len(state['on'])
shared.sort();binding={};outmods={}
for r,m in mods.items():
 x=copy.deepcopy(m);exports={};helpers=['nextAllowed_authorize'] if r=='off' else ['nextAllowed_raw','nextAllowed_legacy'];removed=set();outputs=set()
 for pref in helpers:
  cell=hi[r]['DataTranslationAdapter']['cells'][pref];assert cell['type']=='NextLineAuthorization'
  for p,v in hi[r]['NextLineAuthorization']['ports'].items():
   assert p in cell['connections']
   bs=m['netnames'][pref+'.'+p]['bits'];assert len(bs)==len(v['bits'])
   if v['direction']=='input':
    key='h'+str(len(exports));exports[pref+'.'+p]={'port':key,'bits':bs};x['ports'][key]={'direction':'output','bits':bs}
   else:
    assert p=='io_allowed' and len(bs)==1;key='helper_'+pref;x['ports'][key]={'direction':'input','bits':bs};outputs.update(bs)
  for cn in m['cells']:
   if cn.startswith('$flatten\\'+pref+'.') or cn==pref:removed.add(cn)
 internals={b for cn in removed for p,bs in m['cells'][cn]['connections'].items() if m['cells'][cn]['port_directions'].get(p)=='output' for b in bs if isinstance(b,int)}
 for cn,c in m['cells'].items():
  if cn in removed:continue
  for p,bs in c['connections'].items():
   if c['port_directions'].get(p)=='input':assert not ((set(bs)&internals)-outputs),(r,cn,p)
 for cn in removed:del x['cells'][cn]
 states=[]
 for i,(alias,oc,nc) in enumerate(shared):
  cn=oc if r=='off' else nc;c=x['cells'].pop(cn);states.append({'alias':alias,'cell':cn,'parameters':c['parameters'],'connections':c['connections']})
  x['ports']['q'+str(i)]={'direction':'input','bits':c['connections']['Q']}
  for p in ['D','CLK']:x['ports'][p.lower()+str(i)]={'direction':'output','bits':c['connections'][p]}
 for cn in list(x['cells']):
  if x['cells'][cn]['type']=='$scopeinfo':del x['cells'][cn]
 x['ports']['offer']={'direction':'output','bits':m['netnames']['physicalIngressOffer']['bits']}
 x['attributes']={};x['netnames']={n:{'hide_name':0,'bits':v['bits'],'attributes':{}} for n,v in x['ports'].items()}
 binding[r]={'original_ports':m['ports'],'states':states,'helper_exports':exports,'helper_instances':helpers,'removed_helper_cells':sorted(removed),'remaining_cells':len(x['cells'])};outmods[r.title()]=x
assert mods['off']['ports'].keys()==mods['on']['ports'].keys()
for p,v in mods['off']['ports'].items():assert v['direction']==mods['on']['ports'][p]['direction'] and len(v['bits'])==len(mods['on']['ports'][p]['bits'])
put('ACTUAL_CUT_BINDING.json',binding);put('residual.json',{'creator':'actual full adapter except certified helper outputs and complete FF Q/D cuts','modules':outmods})
# All input buses and all 2143 state bits shared. No assume or validity guard.
inputs=[];lines=[];connections={r:[] for r in mods}
for p,v in mods['off']['ports'].items():
 w=len(v['bits'])
 if v['direction']=='input':
  inputs.append(f'input [{w-1}:0] {p}')
  for r in mods:connections[r].append(f'.{p}({p})')
for i,(alias,_,_) in enumerate(shared):
 w=len(binding['off']['states'][i]['connections']['Q']);inputs.append(f'input [{w-1}:0] q{i}')
 for r in mods:connections[r].append(f'.q{i}(q{i})')
inputs+=['input raw_allowed','input legacy_allowed']
for r in mods:
 for p,v in outmods[r.title()]['ports'].items():
  if v['direction']=='output':lines.append(f'wire [{len(v["bits"])-1}:0] {r}_{p};');connections[r].append(f'.{p}({r}_{p})')
 if r=='off':connections[r].append('.helper_nextAllowed_authorize(on_offer ? raw_allowed : legacy_allowed)')
 else:connections[r]+=['.helper_nextAllowed_raw(raw_allowed)','.helper_nextAllowed_legacy(legacy_allowed)']
 lines.append(r.title()+' actual_'+r+'('+','.join(connections[r])+');')
eq=lambda a,b:f'(({a}) == ({b}))'
ex=binding['off']['helper_exports'];on=binding['on']['helper_exports']
rels=[]
for n,v in ex.items():
 p=n.split('.',1)[1];rels.append(eq('off_'+v['port'],f'(on_offer ? on_{on["nextAllowed_raw."+p]["port"]} : on_{on["nextAllowed_legacy."+p]["port"]})'))
rels.append(eq('off_offer','on_offer'))
raw=[eq('off_'+p,'on_'+p)for p,v in mods['off']['ports'].items()if v['direction']=='output']
raw += [eq(f'off_{p}{i}',f'on_{p}{i}') for i in range(len(shared))for p in ['d','clk']]
lines+=['assign helper_inputs_ok = '+' && '.join(rels)+';','assign residual_ok = '+' && '.join(raw)+';','assign all_ok = helper_inputs_ok && residual_ok;']
(D/'Contract.v').write_text('module Contract('+','.join(inputs+['output helper_inputs_ok,residual_ok,all_ok'])+');\n'+'\n'.join(lines)+'\nendmodule\n')
print('states',len(shared),sum(len(s['connections']['Q'])for s in binding['off']['states']),'helper_input_buses',len(ex),'remainingcells',{r:b['remaining_cells']for r,b in binding.items()})
