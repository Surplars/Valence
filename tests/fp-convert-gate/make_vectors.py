"""Independent exact-integer IEEE decoder/round-to-integer oracle; no host float."""
from pathlib import Path
import random,json,sys
H=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[1];(H/"tests").mkdir(parents=True,exist_ok=True);(H/"results").mkdir(parents=True,exist_ok=True);mask64=(1<<64)-1

def oracle(bits,d,signed,rm,width):
 e,s=(11,53) if d else (8,24);bias=(1<<(e-1))-1;sign=bits>>(e+s-1);exp=(bits>>(s-1))&((1<<e)-1);frac=bits&((1<<(s-1))-1)
 nan=exp==(1<<e)-1 and frac!=0;inf=exp==(1<<e)-1 and frac==0
 low=-(1<<(width-1)) if signed else 0;high=(1<<(width-1))-1 if signed else (1<<width)-1
 if nan or inf:
  v=low if sign and not nan else high;flags=4
 else:
  sig=frac if exp==0 else (1<<(s-1))|frac
  power=(1-bias if exp==0 else exp-bias)-(s-1)
  if power>=0:q,r,den=sig<<power,0,1
  else:den=1<<-power;q,r=divmod(sig,den)
  up=(rm==0 and (2*r>den or 2*r==den and q&1)) or (rm==4 and 2*r>=den) or (rm==2 and sign and r!=0) or (rm==3 and not sign and r!=0)
  mag=q+int(up);v=-mag if sign else mag
  if not low<=v<=high:v=low if sign else high;flags=2
  else:flags=int(r!=0)
 v&=(1<<width)-1
 if width==32 and v>>31:v|=0xffffffff00000000
 return v,flags
# Known anchors are literal ISA boundary expectations, not candidate outputs.
anchors=[(0x3ff8000000000000,1,1,0,32,2,1),(0x4004000000000000,1,1,0,32,2,1),(0xbff8000000000000,1,1,2,32,0xfffffffffffffffe,1),(0x41e0000000000000,1,1,0,32,0x7fffffff,2),(0x41e0000000000000,1,0,0,32,0xffffffff80000000,0),(0x7ff0000000000001,1,1,0,32,0x7fffffff,4),(0xfff8000000000000,1,0,0,32,0xffffffffffffffff,4),(0xbfd0000000000000,1,0,1,32,0,1),(0xbfd0000000000000,1,0,2,32,0,2)]
for a in anchors:assert oracle(*a[:5])==a[5:],a
rng=random.Random(0x641632);count=0;categories={}
with (H/'tests/vectors.txt').open('w') as f:
 for d in (0,1):
  e,s=(11,53) if d else (8,24);bias=(1<<(e-1))-1;signbit=1<<(e+s-1);maxexp=(1<<e)-1
  values={0,1,(1<<(s-1))-1,1<<(s-1),maxexp<<(s-1),((maxexp-1)<<(s-1))|((1<<(s-1))-1)}
  for n in [1,2,3,1<<(s-2),(1<<(s-2))+1,(1<<(s-1))-1]:values.add((maxexp<<(s-1))|n)
  for exponent in [-2,-1,0,1,22,23,24,30,31,32,52,53,62,63,64]:
   center=(exponent+bias)<<(s-1)
   for off in range(-17,18):values.add(center+off)
  for center in [(bias<<(s-1))|(1<<(s-2)),((bias+1)<<(s-1))|(1<<(s-3))]:
   for off in range(-8,9):values.add(center+off)
  values|={x|signbit for x in list(values)}
  values|={rng.getrandbits(e+s) for _ in range(5000)}
  categories['D' if d else 'S']=len(values)
  for bits in sorted(values):
   for signed in (0,1):
    for rm in range(5):
     n,nf=oracle(bits,d,signed,rm,32);w,wf=oracle(bits,d,signed,rm,64)
     f.write(f'{d} {signed} {rm} {bits:016x} {n:016x} {nf:x} {w:016x} {wf:x}\n');count+=1
(H/'results/vector-receipt.json').write_text(json.dumps({'oracle':'exact Python arbitrary-precision IEEE decode + integer quotient/remainder rounding; no host float and no candidate formula','seed':0x641632,'formats_cases':categories,'vectors':count,'rounding_modes':[0,1,2,3,4],'literal_anchors':len(anchors),'softfloat_run':False},indent=2));print(count)
