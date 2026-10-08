#!/usr/bin/env python3
"""Build two tiny actual-ROM CRC controls for one shared BoardSoc model."""
import hashlib,json,pathlib,subprocess,sys,zlib
src=pathlib.Path(__file__).resolve().parent
out=pathlib.Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=True)
manifest={'scope':'ROM CRC target-cycle controls; not a host-speed benchmark','mailbox':0x80600000,'source':0x80400000,'destination':0x80420000,'rows':16,'row_u64':['mode','alignment','warm','stream_ticks','ram_ticks','stream_crc','ram_crc','length'],'cold_policy':'64KiB read sweep, one 8-byte word per 64-byte line; 32KiB-cache eviction pressure, no hardware cache-miss claim','length':1024,'expected_crc':[zlib.crc32(bytes((i*73+(i>>3)+19)&255 for i in range(a,a+1024))) for a in range(8)],'artifacts':{}}
flags=['-march=rv64im_zicsr_zifencei','-mabi=lp64','-mcmodel=medany','-mno-relax','-msmall-data-limit=0','-Os','-ffreestanding','-fno-builtin','-fno-stack-protector','-nostdlib','-nostartfiles','-ffunction-sections','-fdata-sections','-Wl,--gc-sections','-Wl,--defsym=BOARD_RAM_BYTES=2147483648','-Wl,--defsym=BOARD_MONITOR_BASE=4294934528',f'-T{src / "bootrom.ld"}']
for mode in (0,1):
 stem=out/f'crc-mode{mode}';elf=stem.with_suffix('.elf');binary=stem.with_suffix('.bin')
 cmd=['riscv64-unknown-elf-gcc',*flags,f'-DFIRMWARE_CRC_MODE={mode}',*(str(src/p) for p in ('start.S','crc_bench.c','crc32.c')),'-o',str(elf)]
 subprocess.run(cmd,check=True);subprocess.run(['riscv64-unknown-elf-objcopy','-O','binary',str(elf),str(binary)],check=True)
 nm=subprocess.check_output(['riscv64-unknown-elf-nm','-n',str(elf)],text=True);stem.with_suffix('.nm').write_text(nm)
 dis=subprocess.check_output(['riscv64-unknown-elf-objdump','-d',str(elf)],text=True);stem.with_suffix('.dis').write_text(dis)
 symbols={l.split()[2]:int(l.split()[0],16) for l in nm.splitlines() if len(l.split())==3}
 manifest['artifacts'][str(mode)]={'command':cmd,'elf_sha256':hashlib.sha256(elf.read_bytes()).hexdigest(),'bin_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'bin_bytes':binary.stat().st_size,'symbols':{k:v for k,v in symbols.items() if k.startswith('crc_') or k.startswith('__crc') or k in ('__bss_end','__boot_stack_top','__app_stack_top')}}
manifest['sources']={p:hashlib.sha256((src/p).read_bytes()).hexdigest() for p in ('start.S','crc_bench.c','crc32.c','crc32.h','bootrom.ld')}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
