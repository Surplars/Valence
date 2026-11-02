#!/usr/bin/env python3
"""Extract every actual engine D/Q vector; prove delta and inductive refinement.
PMP invocations are structurally certified before separate arbitrary denied cuts.
"""
from pathlib import Path
import copy,json,sys
from helper_certificate import certify,remove_helpers
D=Path(sys.argv[1]);P=D/'proof';P.mkdir()
regs=['activeToken','state','issued','virtualPc','secondVirtualPc','requested','satp','sum','mxr','privilege','firstPhysical','secondPhysical','secondPageFault','secondAccessFault','permissionCaptured','allowed','errors','pageFaults','data']
(P/'HELPER_CERTIFICATE.json').write_text(json.dumps(certify(D,regs),indent=2)+'\n')
modules={};metadata={}
for role,typ in [('off','Off'),('reference','Ref'),('on','New')]:
 m=json.loads((D/'lowered'/(role+'-netlist.json')).read_text())['modules']['RegisteredInstructionTranslationEngine'];c=copy.deepcopy(m);ff={}
 for name,cell in list(c['cells'].items()):
  if cell['type']=='$dff':
   matches=[r for r in regs if m['netnames'][r]['bits']==cell['connections']['Q']];assert len(matches)==1
   r=matches[0];assert r not in ff
   assert cell['connections']['CLK']==m['ports']['clock']['bits']
   assert int(cell['parameters']['CLK_POLARITY'],2)==1 and int(cell['parameters']['WIDTH'],2)==len(cell['connections']['Q'])
   ff[r]=cell['connections'];del c['cells'][name]
  elif cell['type']=='$scopeinfo':del c['cells'][name]
 assert set(ff)==set(regs) and sum(len(v['Q'])for v in ff.values())==467
 for r in regs:
  for pref,direction in [('Q','input'),('D','output')]:
   n=pref+'_'+r;bits=ff[r][pref];c['ports'][n]={'direction':direction,'bits':bits};c['netnames'][n]={'hide_name':0,'bits':bits,'attributes':{}}
 remove_helpers(c,m);c['attributes']={};modules[typ]=c;metadata[role]=ff
ports=modules['Off']['ports'];assert all({n:(v['direction'],len(v['bits']))for n,v in m['ports'].items()}=={n:(v['direction'],len(v['bits']))for n,v in ports.items()}for m in modules.values())
# Reject hidden initialization constraints on any alias of actual state bits.
for m in modules.values():
 qbits={b for r in regs for b in m['ports']['Q_'+r]['bits']}
 for n,v in m['netnames'].items():
  if qbits.intersection(v['bits']):assert 'init' not in v.get('attributes',{}),n
# Add observations from existing actual logic, not hand-coded replacements.
for typ in ['Ref','New']:
 m=modules[typ]
 for name,net in [('observedEarly','earlyFinalOffer'),('observedFirstMask','firstMask'),('observedCrosses','crosses')]:m['ports'][name]={'direction':'output','bits':m['netnames'][net]['bits']}
(P/'cuts.json').write_text(json.dumps({'modules':modules},indent=2)+'\n');(P/'CUT_BINDING.json').write_text(json.dumps(metadata,indent=2)+'\n')
ins={n:len(v['bits'])for n,v in ports.items()if v['direction']=='input'};outs={n:len(v['bits'])for n,v in ports.items()if v['direction']=='output'}
allD=['D_'+r for r in regs];faults=['io_result_bits_accessFaults','io_result_bits_pageFaults']
properties=['nonEarly','blocked','earlyPayload','consumed','turnover','otherOutputs','base','step','mask','allD','nonFault','faultsUnderI','capturedBlocked','withoutI','wrongObservation']
lines=['module Contract(', ',\n'.join(f'input [{w-1}:0] {n}'for n,w in ins.items())+',', ',\n'.join('output '+n for n in properties+['currentI','observedEarly'])+');']
for inst,typ in [('a','Off'),('b','Ref'),('init','Off'),('c','New')]:
 ps=modules[typ]['ports']
 for n,p in ps.items():
  if p['direction']=='output':lines.append(f"wire [{len(p['bits'])-1}:0] {inst}_{n};")
 conn=[]
 for n,p in ps.items():
  v=inst+'_'+n if p['direction']=='output' else ("3'd0"if inst=='init'and n=='Q_state'else n)
  conn.append('.'+n+'('+v+')')
 lines.append(typ+' '+inst+'('+','.join(conn)+');')
def eq(ns,x='a',y='b'):return ' && '.join(f'({x}_{n} == {y}_{n})'for n in ns)
lines += ["wire early = !reset && Q_state == 3'd4 && !(Q_virtualPc[11:0] == 12'd4092 && Q_requested[1]) && io_physical_response_valid;",'wire take = early && io_result_ready;','wire allocate = b_io_command_ready && io_command_valid;',
'assign nonEarly = early || ('+eq(outs)+');',
'assign blocked = !(early && !io_result_ready) || ('+eq(allD)+' && b_io_result_valid && !b_io_command_ready);',
'assign earlyPayload = !early || (b_io_result_valid && b_io_result_bits_token == Q_activeToken && b_io_result_bits_data == a_D_data && b_io_result_bits_accessFaults == a_D_errors && b_io_result_bits_pageFaults == a_D_pageFaults);',
'assign consumed = !(take && !allocate) || (b_D_state == 0 && '+eq([n for n in allD if n!='D_state'])+');',
'assign turnover = !(take && allocate) || ('+eq(allD,'init','b')+');',
'assign otherOutputs = '+eq([n for n in outs if n not in allD+['io_command_ready','io_result_valid','io_result_bits_data',*faults]])+';',
"assign currentI = Q_state != 3'd4 || Q_permissionCaptured;",
"wire nextI = b_D_state != 3'd4 || b_D_permissionCaptured;",
'assign base = !reset || nextI;', 'assign step = reset || !currentI || nextI;',
"assign mask = !(currentI && Q_state == 3'd4 && !b_observedCrosses) || b_observedFirstMask == Q_allowed;",
'assign allD = '+eq(allD,'b','c')+';',
'assign nonFault = '+eq([n for n in outs if n not in allD+faults],'b','c')+';',
'assign faultsUnderI = !currentI || ('+eq(faults,'b','c')+');',
"assign capturedBlocked = !(currentI && c_observedEarly && !io_result_ready) || (c_io_result_bits_accessFaults == b_D_errors && c_io_result_bits_pageFaults == b_D_pageFaults && allD && c_D_state == 3'd7);",
'assign withoutI = '+eq(faults,'b','c')+';',
'assign observedEarly = b_observedEarly;',
'assign wrongObservation = !early || Q_errors == a_D_errors;', 'endmodule']
(P/'contract.sv').write_text('\n'.join(lines)+'\n')
jobs=[]
for prop in properties:
 negative=prop in ['withoutI','wrongObservation'];p=P/(prop+'.ys')
 p.write_text(f'read_json {P/"cuts.json"}\nread_verilog -sv {P/"contract.sv"}\nhierarchy -check -top Contract\nproc\nflatten\nopt_clean\ncheck -assert\nsat -verify -prove {prop} 1 -show-inputs -show-outputs -dump_json {P/(prop+"-cex.json")} -timeout 60\n')
 jobs.append({'name':prop,'expected_exit':1 if negative else 0})
(P/'JOBS.json').write_text(json.dumps(jobs,indent=2)+'\n')
