#!/usr/bin/env python3
"""Independent ELF64/LMA relocation proof. Does not execute RISC-V instructions."""
import argparse
import json
from pathlib import Path
import struct

LOW=0x80200000
HIGH=0xffe00000
END=0xffe20000
STACK=END-16384

def check(elf, binary):
    if len(elf)<64 or elf[:7]!=b'\x7fELF\x02\x01\x01':
        raise ValueError('requires little-endian ELF64')
    h=struct.unpack_from('<16sHHIQQQIHHHHHH',elf)
    _,typ,machine,version,entry,phoff,shoff,flags,ehsize,phsize,phnum,shsize,shnum,shstr=h
    if (typ,machine,version,entry,phsize)!=(2,243,1,LOW,56):
        raise ValueError('wrong executable architecture/entry/header')
    segments=[]
    for i in range(phnum):
        values=struct.unpack_from('<IIQQQQQQ',elf,phoff+i*phsize)
        kind,perm,offset,vma,lma,filesz,memsz,align=values
        if kind!=1: continue
        if filesz>memsz or offset+filesz>len(elf):
            raise ValueError('invalid segment bounds')
        segments.append(dict(perm=perm,offset=offset,vma=vma,lma=lma,filesz=filesz,memsz=memsz))
    if len(segments)!=3:
        raise ValueError('expected boot/code/data segments')
    boot,code,data=segments
    if boot['vma']!=LOW or boot['lma']!=LOW or boot['perm']!=5 or boot['filesz']!=boot['memsz']:
        raise ValueError('invalid boot stub')
    load=LOW+boot['filesz']
    if code['vma']!=HIGH or code['lma']!=load or code['perm']!=5 or code['filesz']!=code['memsz']:
        raise ValueError('invalid high code')
    if data['vma']!=HIGH+code['filesz'] or data['lma']!=load+code['filesz'] or data['perm']!=6:
        raise ValueError('relocation gap or wrong data permissions')
    if data['vma']+data['memsz']>STACK:
        raise ValueError('initialized data/BSS overlaps16KiB stack')
    if (load|code['filesz']|data['filesz'])&7:
        raise ValueError('unaligned copy range')
    used=boot['filesz']+code['filesz']+data['filesz']
    if len(binary)!=used or used>128*1024:
        raise ValueError('wrong flat binary span')
    for s in segments:
        got=binary[s['lma']-LOW:s['lma']-LOW+s['filesz']]
        want=elf[s['offset']:s['offset']+s['filesz']]
        if got!=want: raise ValueError('flat binary does not match ELF load segment')
    # Reproduce the assembly's contiguous eight-byte relocation, independently
    # compare each segment, then its BSS zeroing. No target execution claim.
    memory=bytearray(b'\xa5'*(END-HIGH))
    init=code['filesz']+data['filesz']
    for off in range(0,init,8):
        memory[off:off+8]=binary[boot['filesz']+off:boot['filesz']+off+8]
    for s in (code,data):
        off=s['vma']-HIGH
        if memory[off:off+s['filesz']]!=elf[s['offset']:s['offset']+s['filesz']]:
            raise ValueError('relocated byte mismatch')
    bss_start=data['vma']+data['filesz']
    bss_end=data['vma']+data['memsz']
    memory[bss_start-HIGH:bss_end-HIGH]=bytes(bss_end-bss_start)
    if shsize!=64: raise ValueError('unexpected section format')
    sections=[struct.unpack_from('<IIQQQQIIQQ',elf,shoff+i*shsize) for i in range(shnum)]
    launch=None
    for sec in sections:
        if sec[1]==2:
            strings=sections[sec[6]]
            names=elf[strings[4]:strings[4]+strings[5]]
            for off in range(sec[4],sec[4]+sec[5],sec[9]):
                name,info,other,index,value,size=struct.unpack_from('<IBBHQQ',elf,off)
                if names[name:].split(b'\0',1)[0]==b'stage_launch': launch=value
    if launch is None: raise ValueError('missing stage_launch symbol')
    launch_off=code['offset']+launch-HIGH
    if not HIGH<=launch< HIGH+code['filesz']-8 or struct.unpack_from('<II',elf,launch_off)!=(0x02051293,0x0202d293):
        raise ValueError('entry must zero-extend physical uint32 before launch')
    # Independent RV64 shift semantics, including ABI sign-extended arguments.
    for argument in (0x80200000,0xffffffff80200000,0xfffffffffffffffc):
        actual=((argument<<32)&((1<<64)-1))>>32
        if actual != argument & 0xffffffff: raise ValueError('launch extension mismatch')
    for i in range(shnum):
        sec=struct.unpack_from('<IIQQQQIIQQ',elf,shoff+i*shsize)
        if sec[1] in (4,9) and sec[5]: raise ValueError('unresolved relocation sections')
    return {'status':'PASS_ELF_LAYOUT_AND_HOST_COPY_NOT_TARGET_EXECUTION',
            'entry':hex(entry),'launch_zero_extension':True,'load_range':[hex(LOW),hex(LOW+used)],
            'runtime_range':[hex(HIGH),hex(END)],'bss':[hex(bss_start),hex(bss_end)],
            'stack':[hex(STACK),hex(END)],'copied_bytes':init,'segments':segments}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('build',type=Path);p.add_argument('--negative-tests',action='store_true')
    a=p.parse_args();elf=(a.build/'stager.elf').read_bytes();binary=(a.build/'stager.bin').read_bytes()
    report=check(elf,binary)
    if a.negative_tests:
        phoff=struct.unpack_from('<Q',elf,32)[0]
        mutations=[]
        bad=bytearray(elf)
        # The previously encountered hidden VMA/LMA alignment gap.
        data_lma=phoff+2*56+24
        struct.pack_into('<Q',bad,data_lma,struct.unpack_from('<Q',bad,data_lma)[0]+8)
        mutations.append((bad,binary))
        bad=bytearray(binary);bad[-1]^=1;mutations.append((elf,bad))
        bad=bytearray(elf);struct.pack_into('<Q',bad,24,HIGH);mutations.append((bad,binary))
        bad=bytearray(elf);struct.pack_into('<Q',bad,phoff+2*56+40,0x20000);mutations.append((bad,binary))
        # Recreate old mv t0,a0 bug in BOTH ELF and BIN so segment identity passes.
        code=report['segments'][1]
        bad=bytearray(elf);bad_bin=bytearray(binary)
        needle=struct.pack('<II',0x02051293,0x0202d293)
        off=elf.index(needle,code['offset'],code['offset']+code['filesz'])
        struct.pack_into('<I',bad,off,0x00050293)
        struct.pack_into('<I',bad_bin,code['lma']-LOW+off-code['offset'],0x00050293)
        mutations.append((bad,bad_bin))
        for bad_elf,bad_bin in mutations:
            try:check(bad_elf,bad_bin)
            except ValueError:pass
            else:raise AssertionError('invalid layout accepted')
        report['negative_cases_rejected']=len(mutations)
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
