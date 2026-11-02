import json,hashlib
from pathlib import Path

def certify(Q,regs):
 raw=Q/'lowered';sv=Q/'rtl';assert (sv/'off/PmpChecker.sv').read_bytes()==(sv/'reference/PmpChecker.sv').read_bytes()==(sv/'on/PmpChecker.sv').read_bytes()
 result={'helper_sha256':hashlib.sha256((sv/'off/PmpChecker.sv').read_bytes()).hexdigest(),'instances':{}}
 signatures={}
 for side in ['off','reference','on']:
  m=json.loads((raw/(side+'-netlist.json')).read_text())['modules']['RegisteredInstructionTranslationEngine'];roots={};drivers={}
  for n,p in m['ports'].items():
   if p['direction']=='input':
    for i,b in enumerate(p['bits']):roots[b]=('input',n,i)
  for r in regs:
   for i,b in enumerate(m['netnames'][r]['bits']):roots[b]=('Q',r,i)
  for n,c in m['cells'].items():
   if c['type'] in ['$dff','$scopeinfo']:continue
   for p,bs in c['connections'].items():
    if c['port_directions'][p]=='output':
     for i,b in enumerate(bs):
      if isinstance(b,int):assert b not in drivers;drivers[b]=(n,p,i)
  memo={}
  def sig(b):
   if isinstance(b,str):assert b in ['0','1'];return ('constant',b)
   if b in roots:return roots[b]
   if b in memo:return memo[b]
   n,p,i=drivers[b];assert not n.startswith('$flatten\\checker_')
   c=m['cells'][n];v=(c['type'],tuple(sorted(c['parameters'].items())),p,i,tuple((k,tuple(sig(x) for x in bs)) for k,bs in sorted(c['connections'].items()) if c['port_directions'][k]=='input'))
   memo[b]=v;return v
  for idx in range(2):
   pref=f'checker_{idx}.';ports={n[len(pref):]:v['bits'] for n,v in m['netnames'].items() if n.startswith(pref+'io_') and n!=pref+'io_denied'}
   assert len(ports)==66,len(ports)
   terms={n:[sig(b) for b in bs] for n,bs in ports.items()}
   # No helper input depends on engine state; original idle-init instance uses
   # identical function invocation even though its state Q is deliberately idle.
   assert '"state"' not in json.dumps(terms)
   signatures[side,idx]=terms
   result['instances'][side+str(idx)]={'inputs':terms,'actual_bits':ports,'denied':m['netnames'][pref+'io_denied']['bits']}
 for idx in range(2):assert signatures['off',idx]==signatures['reference',idx]==signatures['on',idx]
 return result

def remove_helpers(c,m):
 removed={n for n in c['cells'] if n.startswith('$flatten\\checker_0.') or n.startswith('$flatten\\checker_1.')}
 produced=set()
 for n in removed:
  cell=c['cells'][n]
  for p,bs in cell['connections'].items():
   if cell['port_directions'][p]=='output':produced.update(b for b in bs if isinstance(b,int))
 denied=set()
 for idx in range(2):
  bits=m['netnames'][f'checker_{idx}.io_denied']['bits'];assert len(bits)==1;denied.update(bits)
  name=f'helperDenied{idx}';c['ports'][name]={'direction':'input','bits':bits};c['netnames'][name]={'hide_name':0,'bits':bits,'attributes':{}}
 for n,cell in c['cells'].items():
  if n in removed:continue
  for p,bs in cell['connections'].items():
   if cell['port_directions'][p]=='input':assert not((set(bs)&produced)-denied),(n,p)
 for p in c['ports'].values():
  if p['direction']=='output':assert not((set(p['bits'])&produced)-denied)
 for n in removed:del c['cells'][n]
 # Drop only helper private aliases after actual structural certificate is saved.
 for n in list(c['netnames']):
  if n.startswith('checker_0.') or n.startswith('checker_1.'):del c['netnames'][n]
 return len(removed)
