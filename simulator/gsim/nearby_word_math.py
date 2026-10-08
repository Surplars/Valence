#!/usr/bin/env python3
"""Exhaustive reduced-width formula check against independent modulo integer order.

This validates the arithmetic identity only. Actual RTL is checked separately by
nearby_word_relations.cpp and the byte-range PMP policy oracle.
"""
import random,json

def shared(base,bound,width,maxoff):
 k=max(1,maxoff.bit_length());mask=(1<<k)-1;high=base>>k;bh=bound>>k;bl=bound&mask
 hn=(high+1)&((1<<(width-k))-1);wrap=high==((1<<(width-k))-1)
 eq=bh==high;eqn=bh==hn;le=bh<=high;lt=le and not eq;rev=not le;zero=bh==0
 out=[]
 for n in range(maxoff+1):
  s=(base&mask)+n;lo=s&mask;carry=s>>k;ble=bl<=lo;lbe=lo<=bl
  pair=(lt or (eq and ble),rev or (eq and lbe))
  if carry:pair=(zero and ble,not zero or lbe) if wrap else (le or (eqn and ble),rev and (not eqn or lbe))
  out.append(pair)
 return out
count=0
for w in range(3,9):
 for n in range(1,min(8,(1<<(w-1))-1)+1):
  for base in range(1<<w):
   for bound in range(1<<w):
    got=shared(base,bound,w,n)
    want=[(bound<=((base+i)&((1<<w)-1)),((base+i)&((1<<w)-1))<=bound) for i in range(n+1)]
    assert got==want,(w,n,base,bound,got,want)
    count+=len(want)
rng=random.Random(0x504d505348415245)
for n in (1,2,4,8,16,128,255):
 for _ in range(30000):
  base=rng.getrandbits(62);bound=rng.getrandbits(62)
  if _%2==0:bound=(base+rng.randrange(-256,256))&((1<<62)-1)
  if _%16==0:base=((1<<62)-rng.randrange(1,256))&((1<<62)-1)
  want=[(bound<=((base+i)&((1<<62)-1)),((base+i)&((1<<62)-1))<=bound) for i in range(n+1)]
  assert shared(base,bound,62,n)==want,(n,base,bound)
  count+=len(want)
print(json.dumps({'status':'PASS_MATHEMATICAL_MODEL_ONLY','comparisons':count,'small_widths':[3,4,5,6,7,8],'random_seed':hex(0x504d505348415245),'rtl_verified':False}))
