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
    def smallcsr(c,value): emit(c<<20 | value<<15 | 5<<12 | 0x73)
    def fused(width,opcode=0x43,rm=0,rd=3,a=1,b=2,c=7):
        emit(c<<27 | (width==64)<<25 | b<<20 | a<<15 | rm<<12 | rd<<7 | opcode)
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
    fused(64,0x43,0,9,8,8,8) # real host FMA before guest entry
    csr(0x100,(2<<13)|0x100); csr(0x600,0x180); csr(0x141,0x40000000); emit(0x10200073)
    at(0x40000000); li(10,0x40010000)
    operands = {}
    loaded = {}
    def operand(reg,value):
        if loaded.get(reg) == value: return
        if value not in operands:
            off=len(operands)*8; operands[value]=off
            for j in range(8): data[0x80210000+off+j]=(value>>(8*j))&255
        ld(reg,operands[value],fp=True);loaded[reg]=value
    def case(name,width,a,b,c,rm=0,frm=0,opcode=0x43,clear=True,store=False,rd=3):
        if clear: smallcsr(1,0)
        smallcsr(2,frm)
        operand(1,a);operand(2,b);operand(7,c)
        casepc=pc;fused(width,opcode,rm,rd=rd)
        loaded.pop(rd,None)
        if store: sd(rd,1024+len(cases)*8);ld(6,1024+len(cases)*8)
        read(1)
        cases.append(dict(name=name,pc=casepc,width=width,opcode=opcode,rm=rm,frm=frm))
    for width in (32,64):
        f,e=(23,8) if width==32 else (52,11);bias=(1<<(e-1))-1
        one=bias<<f;half=(bias-1)<<f;inf=((1<<e)-1)<<f;sign=1<<(width-1)
        box=lambda n:n | (0xffffffff00000000 if width==32 else 0)
        # Every exposed R4 sign variant uses distinct third-source values.
        for opcode in (0x43,0x47,0x4b,0x4f):
            case(f'{width}-variant-{opcode:x}',width,box(one),box(one+(1<<f)),box(half),opcode=opcode)
        for rm in range(5):
            case(f'{width}-half-{rm}',width,box((one+1)|(sign if rm in (1,2) else 0)),box(one+(1<<(f-1))),box(0),7 if rm%2 else rm,rm)
        case(f'{width}-fused-residual',width,box(one+1),box(one-2),box(one|sign),store=True)
        specials=[('qnan-third',one,one,inf|(1<<(f-1)),0),
            ('snan-third',one,one,inf|1,0),('zero-inf-qnan',0,inf,inf|(1<<(f-1)),0),
            ('negative-zero',sign,one,sign,0),('cancellation-down',one,one,one|sign,2),
            ('exact-subnormal',1<<f,half,0,0),('tiny-down',1,half,0,0),('tiny-up',1,half,0,4),
            ('boundary-up',1<<f,one-1,0,0),('boundary-rounded-normal',(1<<f)-1,one+1,0,0),
            ('overflow',inf-1,one+(1<<f),0,0),('static-override',one+1,one+(1<<(f-1)),0,3)]
        for name,a,b,c,rm in specials:
            case(f'{width}-{name}',width,box(a),box(b),box(c),rm,7 if name=='static-override' else 0,
                 clear=name!='static-override',store=name=='boundary-rounded-normal')
    case('single-double-round-discriminator',32,0xffffffff3f800001,0xffffffff3fc00000,0xffffffff97800000,store=True)
    case('malformed-single-third-box',32,0xffffffff3f800000,0xffffffff40000000,0x3f000000)
    smallcsr(1,0);smallcsr(2,0)
    operand(1,0xffffffff3f800001);operand(2,0xffffffff3f7ffffe);operand(7,0xffffffffbf800000)
    ar(32,False,0,4,1,2)      # rounded shared-product S multiplication is exactly one, with NX
    fused(32,0x43,0,4,1,2,7) # exact fused residual, retains old-only NX
    ar(32,False,0,5,4,1)     # S FMA -> FMUL dependency
    read(1)
    # Explicit mixed shared-product dependency slice, with no operand reload across it.
    smallcsr(1,0);smallcsr(2,0)
    operand(1,0x3ff0000000000000);operand(2,0x4000000000000000);operand(7,0x3fe0000000000000)
    ar(64,False,0,4,1,2)      # f4=2 exact shared FMUL
    fused(64,0x43,0,4,1,2,4) # rs3-only dependency, rd aliases rs3: f4=4
    ar(64,False,0,5,4,2)     # FMA -> FMUL dependency: f5=8
    fused(64,0x47,0,6,1,2,5) # third-only dependency: f6=-6
    sd(6,1800);ld(6,1800);read(1)
    # Use FMA instructions for all permission and rounding faults.
    # Reserved static and dynamic rounding encodings must fault, never accrue flags.
    for rm in (5,6): fault(f'reserved-static-{rm}',(7<<27)|(1<<25)|(2<<20)|(1<<15)|(rm<<12)|(3<<7)|0x43)
    for frm in (5,6,7):
        csr(2,frm); fault(f'reserved-dynamic-{frm}',(7<<27)|(1<<25)|(2<<20)|(1<<15)|(7<<12)|(3<<7)|0x43)
    csr(2,0)
    fault('disable-host',0x73)
    fault('host-off-arithmetic',(7<<27)|(1<<25)|(2<<20)|(1<<15)|(3<<7)|0x43)
    csr(0x100,0)
    fault('vs-off-arithmetic',(7<<27)|(1<<25)|(2<<20)|(1<<15)|(3<<7)|0x43)
    fused(64); read(3); fault('return-host',0x73)
    # Straight-line HS handlers read actual trap CSRs, advance SEPC, and SRET.
    for n,site in enumerate(sites):
        at(site['handler'])
        for c in (0x142,0x141,0x143,0x600,0x643,0x64a): read(c)
        if site['name']=='return-host':
            csr(0x100,(2<<13)|0x100); fused(64,0x4f,0,9,8,8,8); read(3)
            terminal=pc; emit(0x6f); continue
        csr(0x105,sites[n+1]['handler'])
        csr(0x100,(0 if site['name']=='disable-host' else 2<<13)|0x100)
        csr(0x200,2<<13)
        read(0x141,1); add(1,1,4); emit(0x141<<20|1<<15|1<<12|0x73); emit(0x10200073)
        assert pc<=site['handler']+0x100
    j=dict(schema=1,profile='guarded-guest-fp-fma-v1',reset_pc=0x80000000,terminal_pc=terminal,
        zero_pages=old['zero_pages'],program=program,code=code,ptes=old['ptes'],bytes=sorted([a,b] for a,b in data.items()),
        fault_sites=sites,phase_markers=[],arithmetic_cases=cases,schedules=old['schedules'],cycle_limit=180000,
        trace_bytes_limit=22*1024*1024,native_timeout_seconds=120,
        scope=dict(cold_reset=True,clocks=1,irq_msi=False,numerical_fd=True,inflight_younger_load_cancel=False,all32_eager_contexts=[],exercised_fp_subset=['FMADD.S/D','FMSUB.S/D','FNMSUB.S/D','FNMADD.S/D','FMUL.S/D','FLD','FSD','FMV.D.X','fcsr/frm/fflags']),
        bounds_justification=dict(encoded_words=len(program),interpreted_instruction_events=600,first_terminal_instruction_events=599,retired_instructions=591,trap_events=9,physical_data_accesses=92,nested_data_pte_reads=1380,explanation='599 words and 600 interpreted events versus prior FMUL 683/684; 92 data accesses versus148, and1380 data PTE reads versus2220. Same external service laws; prior staggered146238cycles leaves33762 below unchanged180000cap, while lower software and memory traffic offset52 fused producer operations.22MiB trace and120s native bounds unchanged. These are abort caps, not hardware performance or guaranteed fit.'))
    assert len({a for a,b in program})==len(program)
    return j
if __name__=='__main__':
    path=BASE/'config/guarded_guest_fp_fma.json'
    j=generate(); path.write_text(json.dumps(j,indent=2)+'\n'); print(len(j['program']),len(j['arithmetic_cases']))
