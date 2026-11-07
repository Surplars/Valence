#!/usr/bin/env python3
"""Freeze only instruction, page-table and operand inputs; no result oracle."""
import json
from pathlib import Path
BASE = Path(__file__).parent

def generate():
    old = json.loads((BASE/'config/guarded_guest_fp_core.json').read_text())
    program, code, data, sites, cases = [], [], {}, [], []
    pc = 0
    def at(address):
        nonlocal pc
        pc = address
    def emit(i):
        nonlocal pc
        physical = pc - 0x40000000 + 0x80200000 if 0x40000000 <= pc < 0x40004000 else pc
        program.append([physical, i]); code.append([pc,physical]); pc += 4
    def add(rd, rs, imm): emit((imm&4095)<<20 | rs<<15 | rd<<7 | 0x13)
    def li(rd, value):
        chunks = list(value.to_bytes(8,'big')); chunks = chunks[next((i for i,x in enumerate(chunks) if x),7):]
        add(rd,0,chunks[0])
        for b in chunks[1:]:
            emit(8<<20 | rd<<15 | 1<<12 | rd<<7 | 0x13)
            if b: add(rd,rd,b)
    def csr(c, value): li(1,value); emit(c<<20 | 1<<15 | 1<<12 | 0x73)
    def read(c,rd=5): emit(c<<20 | 2<<12 | rd<<7 | 0x73)
    def ld(rd,offset,base=10,fp=False): emit(offset<<20 | base<<15 | 3<<12 | rd<<7 | (7 if fp else 3))
    def sd(rs,offset,base=10): emit((offset>>5)<<25 | rs<<20 | base<<15 | 3<<12 | (offset&31)<<7 | 0x27)
    def ar(width,sub,rm,rd=3,a=1,b=2): emit((8+(width==64))<<25 | b<<20 | a<<15 | rm<<12 | rd<<7 | 0x53)
    def fault(name,inst):
        sites.append(dict(pc=pc,name=name,handler=0x80004000+len(sites)*0x100,**{'class':'ecall' if inst==0x73 else 'fault'})); emit(inst)
    # Explicit M bootstrap, then HS entry before the first VS SRET.
    at(0x80000000)
    for c in (0x300,0x304,0x180,0x303,0x602,0x603,0x604): csr(c,0)
    csr(0x3b0,(1<<54)-1); csr(0x3a0,31)
    csr(0x302,1<<2 | 1<<10); csr(0x105,0x80004000)
    csr(0x280,(8<<60)|0x10000); csr(0x680,(8<<60)|0x80010)
    csr(0x200,2<<13); csr(0x300,(2<<13)|(1<<11)); csr(0x341,0x80001000); emit(0x30200073)
    at(0x80001000)
    li(1,0x3ff0000000000000); emit(0xf2000053 | 1<<15 | 8<<7)
    ar(64,False,0,9,8,8) # real host arithmetic before guest entry
    csr(0x100,(2<<13)|0x100); csr(0x600,0x180); csr(0x141,0x40000000); emit(0x10200073)
    at(0x40000000); li(10,0x40010000)
    def case(name,width,sub,a,b,rm=0,frm=0):
        n=len(cases); off=n*16
        for k,value in ((off,a),(off+8,b)):
            for j in range(8): data[0x80210000+k+j]=(value>>(8*j))&255
        csr(2,frm); ld(1,off,fp=True); ld(2,off+8,fp=True)
        casepc=pc; ar(width,sub,rm); sd(3,1024+n*8); ld(6,1024+n*8); read(1)
        cases.append(dict(name=name,pc=casepc,width=width,subtract=sub,rm=rm,frm=frm))
    for width in (32,64):
        f,e=(23,8) if width==32 else (52,11); bias=(1<<(e-1))-1
        one=bias<<f; half=(bias-1)<<f; inf=((1<<e)-1)<<f; sign=1<<(width-1)
        box=lambda n: n | (0xffffffff00000000 if width==32 else 0)
        for rm in range(5):
            csr(1,0)
            case(f'{width}-half-{rm}',width,False,box((one+1)|(sign if rm in (1,2) else 0)),box(one+(1<<(f-1))),7 if rm%2 else rm,rm)
        specials=[('qnan',inf|(1<<(f-1)),one,0),('snan',inf|1,one,0),
            ('zero-inf',0,inf,0),('infinity',inf,one|sign,0),('negative-zero',sign,one,0),
            ('exact-subnormal',1<<f,half,0),('tiny-down',1,half,0),('tiny-up',1,half,4),
            ('boundary-up',1<<f,one-1,0),('boundary-rounded-normal',(1<<f)-1,one+1,0),
            ('overflow',inf-1,one+(1<<f),0),('negative-overflow',sign|(inf-1),one+(1<<f),3),
            ('static-override',one+1,one+(1<<(f-1)),3)]
        for name,a,b,rm in specials:
            # Retain OF as an old-only sticky bit on static override, but isolate every other flag check.
            if name != 'static-override': csr(1,0)
            case(f'{width}-{name}',width,False,box(a),box(b),rm,7 if name=='static-override' else 0)
    # Consume a real finite preceding FMUL result, not a reloaded operand.
    ar(64,False,0,4,3,3); read(1)
    csr(1,0)
    case('malformed-single-box',32,False,0x3f800000,0xffffffff3f800000)
    # A true FPR numerical dependency and explicit sticky flag read/clear.
    csr(1,0); read(1)
    # Reserved static and dynamic rounding encodings must fault, never accrue flags.
    for rm in (5,6): fault(f'reserved-static-{rm}',(9<<25)|(2<<20)|(1<<15)|(rm<<12)|(3<<7)|0x53)
    for frm in (5,6,7):
        csr(2,frm); fault(f'reserved-dynamic-{frm}',(9<<25)|(2<<20)|(1<<15)|(7<<12)|(3<<7)|0x53)
    csr(2,0)
    fault('disable-host',0x73)
    fault('host-off-arithmetic',(9<<25)|(2<<20)|(1<<15)|(3<<7)|0x53)
    csr(0x100,0)
    fault('vs-off-arithmetic',(9<<25)|(2<<20)|(1<<15)|(3<<7)|0x53)
    ar(64,False,0); read(3); fault('return-host',0x73)
    # Straight-line HS handlers read actual trap CSRs, advance SEPC, and SRET.
    for n,site in enumerate(sites):
        at(site['handler'])
        for c in (0x142,0x141,0x143,0x600,0x643,0x64a): read(c)
        if site['name']=='return-host':
            csr(0x100,(2<<13)|0x100); ar(64,True,0,9,8,8); read(3)
            terminal=pc; emit(0x6f); continue
        csr(0x105,sites[n+1]['handler'])
        csr(0x100,(0 if site['name']=='disable-host' else 2<<13)|0x100)
        csr(0x200,2<<13)
        read(0x141,1); add(1,1,4); emit(0x141<<20|1<<15|1<<12|0x73); emit(0x10200073)
        assert pc<=site['handler']+0x100
    j=dict(schema=1,profile='guarded-guest-fp-multiply-v1',reset_pc=0x80000000,terminal_pc=terminal,
        zero_pages=old['zero_pages'],program=program,code=code,ptes=old['ptes'],bytes=sorted([a,b] for a,b in data.items()),
        fault_sites=sites,phase_markers=[],arithmetic_cases=cases,schedules=old['schedules'],cycle_limit=180000,
        trace_bytes_limit=22*1024*1024,native_timeout_seconds=120,
        scope=dict(cold_reset=True,clocks=1,irq_msi=False,numerical_fd=True,inflight_younger_load_cancel=False,all32_eager_contexts=[],exercised_fp_subset=['FMUL.S','FMUL.D','FLD','FSD','FMV.D.X','fcsr/frm/fflags']),
        bounds_justification=dict(encoded_words=len(program),interpreted_instruction_events=684,first_terminal_instruction_events=683,retired_instructions=675,trap_events=9,physical_data_accesses=148,nested_data_pte_reads=2220,explanation='Abort caps, not measured performance. The compact FMUL program has 684 interpreter events versus 698 prior add/sub events and 148 physical accesses versus 180. The prior staggered 151141 cycles leaves 28859 cycles under unchanged 180000, allowing producer latency and traffic variation. Prior maximum trace density projects below 22 MiB at the cap. Native timeout remains 120 seconds and aggregate batch cap 512 MiB. Scalar fetch uses lane zero; no throughput claim.'))
    assert len({a for a,b in program})==len(program)
    return j
if __name__=='__main__':
    path=BASE/'config/guarded_guest_fp_multiply.json'
    j=generate(); path.write_text(json.dumps(j,indent=2)+'\n'); print(len(j['program']),len(j['arithmetic_cases']))
