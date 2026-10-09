"""Compile pinned, unmodified CoreMark kernels and diagnostics separately at -O3."""
from pathlib import Path
import hashlib,json,subprocess
REV='1f483d5b8316753a742cbf5590caf5bd0a4e4777'
# Pinned official algorithm inventory; upstream coremark.md5 has a stale header
# entry. Header below matches both pinned codeload archive and raw official URL.
MD5={'core_list_join.c':'9007fe7861b60ee6f210d156b62974c8','core_main.c':'4a9e6dadce1ac3866381021fbe843fc9','core_matrix.c':'5fa21a0f7c3964167c9691db531ca652','core_state.c':'fb49e7605c125306575a83f14f5798ac','core_util.c':'45540ba2145adea1ec7ea2c72a1fbbcb','coremark.h':'b0ec69b6c8e75853d06accb3b1bcf534'}
def build(source,out,prefix,clock,ram_bytes,monitor):
 core=source.parents[1]/'simulator/build/coremark-src'
 for name,expected in MD5.items():
  if not (core/name).exists() or hashlib.md5((core/name).read_bytes()).hexdigest()!=expected:raise RuntimeError('missing/modified pinned official CoreMark: '+str(core/name))
 gcc=prefix+'gcc';version=subprocess.check_output([gcc,'-dumpfullversion'],text=True).strip()
 flags=['-fstack-usage','-O3','-march=rv64im_zicsr_zifencei','-mabi=lp64','-mcmodel=medany','-mno-relax','-msmall-data-limit=0','-ffreestanding','-fno-builtin','-fno-stack-protector','-ffunction-sections','-fdata-sections','-nostdlib','-nostartfiles',f'-DCPU_HZ={clock}ULL',f'-DBOARD_RAM_BYTES={ram_bytes}UL',f'-DBOARD_MONITOR_BASE={monitor}UL','-DBOOT_MENU=1','-DMONITOR_DIAGNOSTIC=1','-DTOTAL_DATA_SIZE=2000',f'-DCOREMARK_COMPILER_VERSION="riscv64-unknown-elf-gcc {version}"','-DCOREMARK_COMPILER_FLAGS="-O3 -march=rv64im_zicsr_zifencei -mabi=lp64"','-DMEM_LOCATION="ROM-loaded independent RAM diagnostic region; standard2000bytes"','-I'+str(source/'coremark_port'),'-I'+str(source),'-I'+str(core)]
 inputs=[source/'sample_start.S',source/'monitor_diagnostics.c',source/'coremark_port/core_portme.c',*(core/n for n in MD5 if n.endswith('.c'))];objects=[]
 for i,p in enumerate(inputs):
  o=out/f'diag-{i}.o';subprocess.run([gcc,*flags,*(['-Dmain=coremark_main'] if p.name=='core_main.c' else []),'-c',str(p),'-o',str(o)],check=True);objects.append(o)
 elf=out/'monitor-diagnostic.elf';binary=out/'monitor-diagnostic.bin'
 subprocess.run([gcc,*flags,*map(str,objects),'-Wl,--gc-sections','-Wl,--no-relax',f'-Wl,--defsym=DIAGNOSTIC_BASE={monitor-0x80000}',f'-T{source / "monitor_diag.ld"}','-lgcc','-o',str(elf)],check=True)
 subprocess.run([prefix+'objcopy','-O','binary',str(elf),str(binary)],check=True)
 if binary.stat().st_size>0x1c000:raise RuntimeError('diagnostic code/data image exceeds112KiB')
 asm=out/'monitor-diagnostic-blob.S';asm.write_text('.section .rodata.monitor_diagnostic,"a"\n.balign 8\n.global monitor_diag_blob_start,monitor_diag_blob_end\nmonitor_diag_blob_start:\n.incbin "'+str(binary)+'"\nmonitor_diag_blob_end:\n')
 (out/'diagnostic-contract.json').write_text(json.dumps({'coremark_revision':REV,'official_source_sha256':{n:hashlib.sha256((core/n).read_bytes()).hexdigest() for n in MD5},'compiler':version,'flags':flags,'total_data_size':2000,'short_coremark_menu':False,'formal_mode':'official auto calibration; measured duration strictly greater than10seconds and all CRCs required; provisional rate suppressed','rom_blob_bytes':binary.stat().st_size,'rom_blob_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'reserve_start':monitor-0x80000,'reserve_end':monitor,'payload_stack_bytes':16384,'monitor_stack_bytes':8192,'boot_scratch_reclaimable_by_payload':True},indent=2)+'\n')
 return asm
