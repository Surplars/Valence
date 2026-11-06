#!/usr/bin/env python3
"""Build the real RV64 cold-boot DDR selftest and its RPU embedded-image header."""
import argparse,hashlib,json,subprocess,zlib
from pathlib import Path
R=Path(__file__).resolve().parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True);o=ap.parse_args().output.resolve()
 if o.exists() or not o.is_relative_to(R/'build'):ap.error('fresh output inside clone build/ required')
 o.mkdir(parents=True);sources=[R/'software/rv-bringup'/n for n in ['start.S','bringup.c','link.ld','build.py']]+[R/'software/ps-rpu/i1_boot_protocol.h']
 rec={'status':'BUILDING','source_sha256':{str(p.relative_to(R)):sha(p) for p in sources},'commands':[]}
 def run(argv,log):
  argv=list(map(str,argv));rec['commands'].append({'argv':argv,'log':log})
  with (o/log).open('w') as f:subprocess.run(argv,cwd=R,stdout=f,stderr=subprocess.STDOUT,check=True)
 try:
  run(['riscv64-unknown-elf-gcc','-march=rv64im_zicsr_zifencei','-mabi=lp64','-mcmodel=medany','-mno-relax','-msmall-data-limit=0','-O2','-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-asynchronous-unwind-tables','-nostdlib','-nostartfiles','-Wall','-Wextra','-Werror','-I'+str(R/'software/ps-rpu'),'-T',R/'software/rv-bringup/link.ld','-Wl,--no-relax,-Map='+str(o/'rv-selftest.map'),R/'software/rv-bringup/start.S',R/'software/rv-bringup/bringup.c','-o',o/'rv-selftest.elf'],'compile.log')
  run(['riscv64-unknown-elf-objcopy','-O','binary',o/'rv-selftest.elf',o/'rv-selftest.bin'],'objcopy.log')
  data=(o/'rv-selftest.bin').read_bytes();assert 0<len(data)<0x0fff0000
  symbols={}
  for line in subprocess.check_output(['riscv64-unknown-elf-nm','-n',o/'rv-selftest.elf'],text=True).splitlines():
   cells=line.split()
   if len(cells)==3:symbols[cells[2]]=int(cells[0],16)
  assert symbols['_start']==0x80000000 and symbols['i1_trap']%4==0
  run(['riscv64-unknown-elf-objdump','-d',o/'rv-selftest.elf'],'disassembly.log')
  lines=['/* Generated from the qualified RV flat image; link this header into RPU firmware. */','#ifndef I1_EMBEDDED_RV_IMAGE_H','#define I1_EMBEDDED_RV_IMAGE_H','static const unsigned char i1_rv_image[] __attribute__((aligned(8))) = {']
  lines+=['    '+','.join('0x%02x'%v for v in data[i:i+16])+',' for i in range(0,len(data),16)]
  lines+=['};','#define I1_RV_IMAGE_BYTES %du'%len(data),'#define I1_RV_IMAGE_CRC32 0x%08xu'%(zlib.crc32(data)&0xffffffff),'#endif','']
  (o/'i1_embedded_rv_image.h').write_text('\n'.join(lines))
  rec.update(status='PASS_RV64_REAL_DDR_SELFTEST_IMAGE_BUILT',image_bytes=len(data),image_crc32=zlib.crc32(data)&0xffffffff,symbols={k:symbols[k] for k in ['_start','i1_trap','__i1_breakpoint_probe','__bss_start','__bss_end','__stack_top']},PS_load_address='0x40000000',RV_entry='0x80000000',PS_mailbox='0x4fff0000',RV_mailbox='0x8fff0000')
 except BaseException as e:rec.update(status='FAIL',error=repr(e));raise
 finally:
  rec['artifact_sha256']={p.name:sha(p) for p in o.iterdir() if p.is_file() and p.name!='receipt.json'}
  (o/'receipt.json').write_text(json.dumps(rec,indent=2)+'\n')
 print(rec['status'],'bytes',rec['image_bytes'],'CRC32',hex(rec['image_crc32']),flush=True)
if __name__=='__main__':main()
