#!/usr/bin/env python3
"""Author finite raw RV64I/M guest, independently interpret its exact bytes.
No model is compiled or executed. No hardware decode helpers are imported.
"""
import hashlib,json,struct
from pathlib import Path
OUT=Path(__file__).resolve().parent
BASE=0x80200000
LINES=[0x81400000,0x81400400,0x81400800]
MASK=(1<<64)-1

def sx(v,n): return (v^(1<<(n-1)))-(1<<(n-1))
def i(rd,rs,v,f=0): return ((v&4095)<<20)|(rs<<15)|(f<<12)|(rd<<7)|0x13
def ld(rd,rs,off=0): return ((off&4095)<<20)|(rs<<15)|(3<<12)|(rd<<7)|3
def sd(rs,base,off=0): return (((off&4095)>>5)<<25)|(rs<<20)|(base<<15)|(3<<12)|((off&31)<<7)|0x23
def beq(a,b,off): return (((off>>12)&1)<<31)|(((off>>5)&63)<<25)|(b<<20)|(a<<15)|(((off>>1)&15)<<8)|(((off>>11)&1)<<7)|0x63

def authored():
 code=[];labels={}
 def emit(x,label=None):
  if label: labels[label]=BASE+len(code)*4
  code.append(x)
 def constant(rd,v):
  parts=v.to_bytes(8,'big');emit(i(rd,0,parts[0]))
  for byte in parts[1:]:emit(i(rd,rd,8,1));emit(i(rd,rd,byte))
 emit(0x01200097) # AUIPC x1,0x1200: BASE + 0x1200000 = first data line.
 constant(2,0x1122334455667788)
 constant(3,0xa1b2c3d4e5f60718)
 constant(4,0x99aabbccddeeff00)
 emit(i(6,0,1));emit(i(7,0,0))
 for case in range(2):
  if case: emit(i(1,1,0x400))
  # Keep the witness in one instruction-cache line, with the future loads
  # inside the ROB. These padding instructions execute normally.
  while len(code)%16:emit(i(7,7,1))
  p=f'case{case}_'
  if not case:
   for n in range(2):emit((1<<25)|(6<<20)|((6 if n==0 else 22)<<15)|(22<<7)|0x33)
  emit(sd(2,1),p+'S0')
  if not case:emit(i(7,7,1))
  emit(sd(3,1,8),p+'S1')
  if not case:
   for n in range(3):emit(i(7,7,1))
   emit(ld(10,1),p+'U')
  else:
   emit((1<<25)|(6<<20)|(1<<15)|(20<<7)|0x33,p+'MUL')
   emit(ld(10,20),p+'U')
   emit(ld(13,1,8),p+'Q') # independently ready younger selected candidate
  emit(sd(4,1),p+'Y');emit(ld(11,1),p+'V')
  emit(ld(12,1,8),p+'W')
  emit(0x0ff0000f,p+'FENCE')
  # Genuine allocations exercise full-tag index reuse; no token injection.
  for n in range(20):emit(i(7,7,1))
 # One bounded taken branch resolves after a real dependent MUL chain. Its
 # wrong-path LD is independently specified but must never issue or retire.
 emit(i(1,1,0x400))
 while len(code)%16:emit(i(7,7,1))
 emit(sd(2,1),'kill_S0');emit(sd(3,1,8),'kill_S1')
 for n in range(4):emit((1<<25)|(6<<20)|((6 if n==0 else 21)<<15)|(21<<7)|0x33)
 emit(beq(21,6,24),'kill_branch')
 emit(ld(14,1),'killed_load')
 for n in range(4):emit(i(7,7,1))
 emit(ld(15,1),'replacement_load')
 emit(0x0ff0000f,'kill_FENCE')
 for n in range(20):emit(i(7,7,1))
 emit(0x0000100f,'flush');emit(0x0000006f,'done')
 return code,labels

def initial():
 return {line+off:(0x80+off)&255 for line in LINES for off in range(-64,128)}

def interpret(code):
 regs=[0]*32;mem=initial();trace=[];ops=[]
 n=0;steps=0
 while n<len(code):
  x=code[n];next_n=n+1;steps+=1
  assert steps<=len(code),'guest must be finite before final spin'
  pc=BASE+4*n;op=x&127;rd=(x>>7)&31;a=(x>>15)&31;b=(x>>20)&31;f=(x>>12)&7
  e={'pc':pc,'instruction':x,'rd':0,'value':0,'memory':False,'done':False}
  if op==0x17:e.update(rd=rd,value=(pc+sx(x&0xfffff000,32))&MASK)
  elif op==0x13 and f==0:e.update(rd=rd,value=(regs[a]+sx(x>>20,12))&MASK)
  elif op==0x13 and f==1 and x>>26==0:e.update(rd=rd,value=(regs[a]<<((x>>20)&63))&MASK)
  elif op==0x33 and f==0 and x>>25==1:e.update(rd=rd,value=(regs[a]*regs[b])&MASK)
  elif op==0x63 and f==0:
   imm=((x>>31)<<12)|(((x>>7)&1)<<11)|(((x>>25)&63)<<5)|(((x>>8)&15)<<1)
   if regs[a]==regs[b]:next_n=n+sx(imm,13)//4
   assert 0<=next_n<len(code),'branch target outside raw guest'
  elif op in (3,0x23) and f==3:
   store=op==0x23;imm=(((x>>25)<<5)|((x>>7)&31)) if store else x>>20
   addr=(regs[a]+sx(imm,12))&MASK
   assert addr%8==0 and all(addr+j in mem for j in range(8)),('bad memory',pc,addr)
   value=regs[b] if store else sum(mem[addr+j]<<(8*j) for j in range(8))
   m={'pc':pc,'instruction':x,'address':addr,'data':value if store else 0,'size':3,'store':store,'expected':value}
   e['memory']=True;e['intent']=m;ops.append(m)
   if store:
    for j in range(8):mem[addr+j]=(value>>(8*j))&255
   else:e.update(rd=rd,value=value)
  elif x in (0x0ff0000f,0x0000100f):pass
  elif x==0x0000006f:e['done']=True
  else:raise AssertionError(('unsupported raw encoding',hex(pc),hex(x)))
  if e['rd']:regs[e['rd']]=e['value']
  regs[0]=0;trace.append(e)
  if e['done']:break
  n=next_n
 return trace,ops,mem

def main():
 code,labels=authored();trace,ops,final=interpret(code)
 raw=b''.join(struct.pack('<I',x) for x in code)
 # Safe speculative fall-through is encoded but never part of expected retire.
 raw+=struct.pack('<I',0x0000006f)*32
 bypc={x['pc']:x for x in ops}
 for c,line in enumerate(LINES[:2]):
  assert bypc[labels[f'case{c}_U']]['expected']==0x1122334455667788
  assert bypc[labels[f'case{c}_V']]['expected']==0x99aabbccddeeff00
  assert bypc[labels[f'case{c}_S1']]['data']==0xa1b2c3d4e5f60718
  assert all(final[line+j]==initial()[line+j] for j in range(16,64))
 killed={'pc':labels['killed_load'],'instruction':code[(labels['killed_load']-BASE)//4],'address':LINES[2],'data':0,'size':3,'store':False,'expected':0x1122334455667788}
 assert killed['pc'] not in {e['pc'] for e in trace}
 assert bypc[labels['replacement_load']]['expected']==killed['expected']
 manifest={'schema':2,'status':'PREPARED_NOT_SIMULATED','base':BASE,'lines':LINES,'labels':labels,'guest_sha256':hashlib.sha256(raw).hexdigest(),'raw_words':code,'trace':trace,'memory_operations':ops,'killed_load':killed,'initial_bytes':[[a,b] for a,b in sorted(initial().items())],'final_bytes':[[a,b] for a,b in sorted(final.items())]}
 (OUT/'guest.bin').write_bytes(raw);(OUT/'guest-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 s=['#pragma once','#include <array>','#include <cstdint>','namespace directed_guest {',f'constexpr uint64_t base={BASE}ULL;',f'constexpr uint64_t donePc={labels["done"]}ULL;',f'constexpr uint64_t killedPc={killed["pc"]}ULL;',f'constexpr uint64_t replacementPc={labels["replacement_load"]}ULL;',f'constexpr unsigned rawBytes={len(raw)};',f'constexpr std::array<uint32_t,{len(code)}> rawWords{{'+','.join(str(x)+'U' for x in code)+'};','struct Expected {uint64_t pc;uint32_t raw;bool memory,store,done;uint64_t address,data,value;unsigned size;};',f'constexpr Expected killed{{{killed["pc"]}ULL,{killed["instruction"]}U,true,false,false,{killed["address"]}ULL,0,{killed["expected"]}ULL,3}};',f'constexpr std::array<Expected,{len(trace)}> trace{{{{']
 for e in trace:
  m=e.get('intent',{});s.append('{%dULL,%dU,%s,%s,%s,%dULL,%dULL,%dULL,%d},'%(e['pc'],e['instruction'],str(e['memory']).lower(),str(m.get('store',False)).lower(),str(e['done']).lower(),m.get('address',0),m.get('data',0),m.get('expected',0),m.get('size',0)))
 s+=['}};','struct Byte {uint64_t address;unsigned value;};']
 for name,mem in [('initial',initial()),('finalBytes',final)]:
  s.append(f'constexpr std::array<Byte,{len(mem)}> {name}{{{{');s.extend('{%dULL,%d},'%(a,b) for a,b in sorted(mem.items()));s.append('}};')
 s+=['struct Case {uint64_t line,s0,s1,u,y,v,q;};','constexpr std::array<Case,2> cases{{']
 for c,line in enumerate(LINES[:2]):s.append('{'+','.join(str(x)+'ULL' for x in [line]+[labels.get(f'case{c}_{l}',0) for l in ['S0','S1','U','Y','V','Q']])+'},')
 s+=['}};','}'];(OUT/'guest_inputs.h').write_text('\n'.join(s)+'\n')
 print(json.dumps({'status':'PREPARED_NOT_SIMULATED','instructions':len(trace),'memory_operations':len(ops),'sha256':manifest['guest_sha256']}))
if __name__=='__main__':main()
