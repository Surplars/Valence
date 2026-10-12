"""Exact reviewed whole-burst service verifier; no model execution."""
from collections import Counter

def verify_service(p):
 owner={};active=None;first=[];last=[];gaps=[]
 for s in p.read_text().splitlines():
  v=list(map(int,s.split('\t')[1:]));c,ch=v[:2];f=v[2:]
  if ch==0:
   assert f[1] not in owner;owner[f[1]]={'c':c,'address':f[0],'size':f[3],'len':f[2],'beat':0,'previous':None}
  if ch==2:
   i=f[0];o=owner[i]
   if active is None:active=i
   assert i==active,'R transaction interleaved before actual LAST'
   assert f[4]==o['address']+(o['beat']<<o['size']),'R beat address/order'
   assert bool(f[2])==(o['beat']==o['len']),'R LAST/count'
   assert c>=o['c']+32,'R before unchanged eligibility'
   if o['beat']==0:first.append(c-o['c'])
   else:gaps.append(c-o['previous']);assert c-o['previous']>=1
   o['previous']=c;o['beat']+=1
   if f[2]:last.append(c-o['c']);del owner[i];active=None
 assert not owner and active is None
 return {'transactions':len(first),'ar_to_first_r':dict(sorted(Counter(first).items())),'ar_to_last_r':dict(sorted(Counter(last).items())),'interbeat_gap':dict(sorted(Counter(gaps).items())),'no_interleaving':True}
