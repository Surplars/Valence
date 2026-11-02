#!/usr/bin/env python3
"""Decode semantic witnesses without pinning an arbitrary solver bit assignment."""
from pathlib import Path
import json,sys
D=Path(sys.argv[1]);result={}
for name in ['withoutI','wrongObservation']:
 v={}
 for s in json.loads((D/(name+'-cex.json')).read_text())['signal']:
  b=s['data'][0] if s['wave'][0]=='=' else s['wave'][0]
  assert b and set(b)<=set('01');v[s['name']]=int(b,2)
 assert v[name]==0 and v['observedEarly']==1
 if name=='withoutI':assert v['currentI']==0 and v['Q_state']==4 and v['Q_permissionCaptured']==0 and v['allD']==v['nonFault']==1
 else:
  cross=(v['Q_virtualPc']&4095)==4092 and bool(v['Q_requested']&2)
  checked=((v['Q_requested']&1)&(1-v['helperDenied0']))|((((v['Q_requested']>>1)&1)&(not(cross and(v['Q_secondPageFault']or v['Q_secondAccessFault'])))&(1-v['helperDenied1']))<<1)
  active=v['Q_allowed']if v['Q_permissionCaptured']else checked
  mask=active&1 if cross else active
  assert v['Q_errors'] != (v['Q_errors'] | (v['io_physical_responseError']&mask))
 result[name]=v
(D/'NEGATIVE_DECODE.json').write_text(json.dumps({'status':'PASS_DECODED_COUNTEREXAMPLES','values':result},indent=2)+'\n')
