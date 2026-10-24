#!/usr/bin/env python3
"""Build a RAM-only relocated netboot candidate; never flashes or starts servers."""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import subprocess
import netboot_host

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--prefix',default='riscv64-unknown-elf-')
    p.add_argument('--board-ip',required=True)
    p.add_argument('--server-ip',required=True)
    a=p.parse_args()
    board=int(ipaddress.IPv4Address(a.board_ip));server=int(ipaddress.IPv4Address(a.server_ip))
    a.out.mkdir(parents=True,exist_ok=False)
    here=Path(__file__).resolve().parent
    sources=['netboot_stager_start.S','netboot_stager.c','netboot_board.c','netboot.c','crc32.c']
    flags=['-march=rv64im_zicsr_zifencei','-mabi=lp64','-mcmodel=medany','-mno-relax',
           '-msmall-data-limit=0','-Os','-ffreestanding','-fno-builtin','-fno-stack-protector',
           '-ffunction-sections','-fdata-sections','-nostdlib','-nostartfiles',
           '-Wall','-Wextra','-Werror','-Wl,--gc-sections','-Wl,--no-relax',
           '-DBOARD_RAM_BYTES=0x80000000UL','-DBOARD_MONITOR_BASE=0xffe00000UL',
           '-DTIMEBASE_HZ=250000000ULL','-DCPU_HZ=50000000ULL',
           '-DFIRMWARE_CRC_MODE=3','-DNETBOOT_POSTED_RX=1','-DNETBOOT_BLOCK_BYTES=1024',
           '-DNETBOOT_WINDOW=4','-DNETBOOT_RX_SLOTS=4',f'-DNETBOOT_IP={board}U',
           f'-DNETBOOT_SERVER={server}U','-DNETBOOT_FILE="linux.vld"',
           '-T'+str(here/'netboot_stager.ld'),'-Wl,-Map,'+str(a.out/'stager.map')]
    elf=a.out/'stager.elf';binary=a.out/'stager.bin'
    command=[a.prefix+'gcc',*flags,*[str(here/s) for s in sources],'-lgcc','-o',str(elf)]
    subprocess.run(command,check=True)
    subprocess.run([a.prefix+'objcopy','-O','binary',str(elf),str(binary)],check=True)
    symbols=subprocess.check_output([a.prefix+'nm','-n',str(elf)],text=True)
    (a.out/'symbols.txt').write_text(symbols)
    sections=subprocess.check_output([a.prefix+'readelf','-lW',str(elf)],text=True)
    (a.out/'segments.txt').write_text(sections)
    disasm=subprocess.check_output([a.prefix+'objdump','-d',str(elf)],text=True)
    (a.out/'disassembly.txt').write_text(disasm)
    netboot_host.pack(binary,a.out/'valence.vld',limit=netboot_host.LIMITS['ddr2g-menu'])
    names=sources+['netboot_stager.ld','netboot.h','netboot_copy.h','crc32.h','ram_verify.h',
                   'board_memory.h','board_clocks.h','ethernet_dma.h','valence_gmac.h',
                   'build_netboot_stager.py','netboot_host.py']
    digest=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
    manifest={'status':'BUILT_CANDIDATE_NOT_BOARD_VALIDATED','board_tested':False,
              'new_bit_required':False,'clocks_changed':False,'entry':0x80200000,
              'runtime_region':[0xffe00000,0xffe20000],
              'payload_region':[0x80200000,0xffe00000],
              'second_filename':'linux.vld','board_ip':a.board_ip,'server_ip':a.server_ip,
              'command':command,'sources':{n:digest(here/n) for n in names},
              'artifacts':{n:{'bytes':(a.out/n).stat().st_size,'sha256':digest(a.out/n)}
                           for n in ['stager.elf','stager.bin','valence.vld']}}
    (a.out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('NETBOOT_STAGER_BUILT_NOT_BOARD_VALIDATED',a.out)
if __name__=='__main__':main()
