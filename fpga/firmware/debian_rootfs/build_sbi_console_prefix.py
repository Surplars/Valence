#!/usr/bin/env python3
"""Rebuild only pinned OpenSBI/DT for an exact sealed I1 VLD; kernel stays byte-identical."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile
import zlib
import sbi_console_handoff
from apply_sbi_console_prefix import validate_vld

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ORIGINAL = 'd46762eb312579cd305909690dcb95a5f6c0de6e6fd66eb232ad1dff86a2d0b9'
SPLIT = 36 + 0x200000

def sha(data): return hashlib.sha256(data).hexdigest()
def run(cmd, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str,cmd)), stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=600)


def build(args):
    out=args.out.resolve(); out.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(args.baseline) as z:
        manifest=json.loads(z.read('i1/manifest.json'))
        old=z.read('i1.prefix')+z.read('common-body.bin')
        dts=z.read('i1/valence-vl100.dts').decode()
        olddt=z.read('i1/valence-vl100.dtb')
    validate_vld(old)
    if sha(old)!=ORIGINAL or len(old)!=142386892:
        raise RuntimeError('Wrong baseline firmware, no patch constructed')
    raw=old[SPLIT:]; image_bytes=manifest['files']['Image']['bytes']; image=raw[:image_bytes]
    if sha(image)!=manifest['files']['Image']['sha256']:
        raise RuntimeError('Original kernel Image identity mismatch')
    marker='            reg-io-width = <1>;'
    if dts.count(marker)!=1 or 'openion,sbi-console-exclusive' in dts:
        raise RuntimeError('Unexpected initial UART DT')
    dts=dts.replace(marker,marker+'\n            openion,sbi-console-exclusive;')
    (out/'initial.dts').write_text(dts);(out/'original.dtb').write_bytes(olddt)
    (out/'Image').write_bytes(image)
    run(['dtc','-q','-I','dts','-O','dtb','-o',out/'initial.dtb',out/'initial.dts'],out/'dtc.log')
    source=out/'opensbi-patched'; patch=sbi_console_handoff.prepare(args.opensbi,source)
    command=['make','-C',source,'-j8','PLATFORM=generic','CROSS_COMPILE='+args.cross_compile,
             'PLATFORM_RISCV_ISA=rv64imac_zicsr_zifencei','PLATFORM_RISCV_ABI=lp64',
             'FW_TEXT_START=0x80200000','FW_DYNAMIC=n','FW_JUMP=n','FW_PAYLOAD=y',
             'FW_PAYLOAD_OFFSET=0x200000','FW_PAYLOAD_FDT_ADDR=0x80300000','FW_FDT_PADDING=8192',
             'FW_FDT_PATH='+str(out/'initial.dtb'),'FW_PAYLOAD_PATH='+str(out/'Image'),'O='+str(out/'opensbi-build')]
    run(command,out/'opensbi-build.log')
    binary=out/'opensbi-build/platform/generic/firmware/fw_payload.bin'
    content=binary.read_bytes()
    if content[0x200000:]!=raw:
        raise RuntimeError('Kernel/rootfs body changed or payload layout drifted')
    if content.count((out/'initial.dtb').read_bytes())!=1:
        raise RuntimeError('Initial firmware DT not embedded exactly once')
    # Reuse the frozen payload/ELF memory-layout validator; no kernel rebuild.
    sys.path.insert(0,str(HERE))
    import build_image
    padding=build_image.validate_payload(content,image,0xfff78000)
    elf=binary.with_suffix('.elf')
    binding=build_image.validate_payload_elf(elf.read_bytes(),content,image,0xfff78000)
    symbols={line.split()[2]:int(line.split()[0],16) for line in
             subprocess.check_output([args.cross_compile+'nm',str(elf)],text=True).splitlines()
             if len(line.split())==3}
    if symbols.get('_fw_start')!=0x80200000 or symbols.get('payload_bin')!=0x80400000 or not 0x80200000<symbols.get('_fw_end',0xffffffff)<=0x80300000:
        raise RuntimeError('OpenSBI firmware overlaps the reserved DT/kernel region')
    config=(out/'opensbi-build/platform/generic/kconfig/.config').read_text()
    if 'CONFIG_PLATFORM_GENERIC_FDT_EMPTY_SPACE=4' not in config.splitlines() or (out/'initial.dtb').stat().st_size+8192>0x10000:
        raise RuntimeError('Reserved firmware DT expansion contract mismatch')
    fields=list(struct.unpack('<9I',old[:36]));fields[5]=zlib.crc32(content);fields[8]=zlib.crc32(struct.pack('<8I',*fields[:8]))
    new=struct.pack('<9I',*fields)+content;validate_vld(new)
    delivery=out/'delivery';delivery.mkdir();prefix=new[:SPLIT]
    (delivery/'i1-sbi-console-fixed.prefix').write_bytes(prefix)
    (out/'verified-new-i1.vld').write_bytes(new)
    result=dict(schema=1,original_vld_sha256=sha(old),original_vld_bytes=len(old),
                prefix_bytes=SPLIT,new_prefix_sha256=sha(prefix),unchanged_body_sha256=sha(raw),
                new_vld_sha256=sha(new),new_vld_bytes=len(new),kernel_image_sha256=sha(image),
                original_dtb_sha256=sha(olddt),initial_dtb_sha256=sha((out/'initial.dtb').read_bytes()),
                opensbi_patch=patch,firmware_end=symbols['_fw_end'],dt_reserved_bytes=0x10000,final_dt_expansion_bytes=4096,cross_compile=args.cross_compile,compiler_version=subprocess.check_output([args.cross_compile+'gcc','--version'],text=True).splitlines()[0],payload_elf_binding=binding,padding_bytes=len(padding) if isinstance(padding,bytes) else padding,
                no_kernel_or_rootfs_rebuild=True,board_verified=False)
    (delivery/'prefix-patch.json').write_text(json.dumps(result,indent=2)+'\n')
    shutil.copy2(HERE/'apply_sbi_console_prefix.py',delivery)
    shutil.copy2(out/'initial.dtb',delivery)
    shutil.copy2(out/'initial.dts',delivery)
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--opensbi',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--cross-compile',default='riscv64-linux-gnu-')
    build(p.parse_args())
