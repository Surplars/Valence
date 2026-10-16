"""Bound structural equality proof for this diagnostic export; no netlist waiver."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
EXPORT=Path('/workspace/scratch/41e4a649bb60/combined-timing-repair-transfer-r1/network/export')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def proof(encoder,parent):
 m=encoder['modules']['TriSpeedRgmiiTx']; roles=[]
 for port in ('io_rise','io_fall'):
  bit=m['ports'][port]['bits'][4]
  drivers=[(n,c,c['connections']['Q'].index(bit)) for n,c in m['cells'].items() if c['type']=='$adff' and bit in c['connections'].get('Q',[])]
  if len(drivers)!=1:raise ValueError('Control must have one complete async FF driver')
  n,c,i=drivers[0];q=c['connections'];p=c['parameters']
  if p['CLK_POLARITY']!='1' or p['ARST_POLARITY']!='1' or q['CLK']!=m['ports']['clock']['bits'] or q['ARST']!=m['ports']['reset']['bits'] or p['ARST_VALUE'][-1-i]!='0':raise ValueError('Clock/reset/value mismatch')
  roles.append(dict(cell=n,D=q['D'][i],CLK=q['CLK'],ARST=q['ARST'],resetValue=0))
 if {k:v for k,v in roles[0].items() if k!='cell'}!={k:v for k,v in roles[1].items() if k!='cell'}:raise ValueError('Different control D/clock/reset')
 p=parent['modules']['TriSpeedManagedGmac']; c=p['cells']['encode'];q=c['connections']
 if c['type']!='TriSpeedRgmiiTx':raise ValueError('Wrong complete encoder')
 for a,b in [('clock','rawTxClock'),('io_rise','rgmiiTxRise'),('io_fall','rgmiiTxFall')]:
  if q[a]!=p['ports'][b]['bits']:raise ValueError('Parent forwarding mismatch')
 if q['reset']!=p['cells']['rawTxRelease']['connections']['resetOut']:raise ValueError('Wrong encoder release epoch')
 return roles

def verify(export):
 r=json.loads((HERE/'proof.json').read_text())
 for n,d in r['artifacts'].items():
  if sha(HERE/n)!=d:raise ValueError('Changed proof artifact '+n)
 for n,d in r['sources'].items():
  if sha(export/n)!=d:raise ValueError('Changed complete source '+n)
 if proof(json.loads((HERE/'encoder.json').read_text()),json.loads((HERE/'parent.json').read_text()))!=r['roles']:raise ValueError('Proof facts changed')
 if sha(export/'board/native-mac-mode.json')!=r['diagnosticIdentity']:raise ValueError('Wrong complete diagnostic identity')
 return r['diagnosticIdentity']

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('export',type=Path);a=p.parse_args();print(verify(a.export))
