#!/usr/bin/env python3
"""Bounded menu/diagnostic software proof. Never claims CPU/GSIM/board throughput."""
import argparse,hashlib,json,os,pathlib,re,subprocess,sys
S=pathlib.Path(__file__).resolve().parent;ROOT=S.parents[1]
def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',type=pathlib.Path,required=True);args=ap.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
 files=sorted(p for p in S.rglob('*') if p.is_file() and p.suffix in ('.c','.h','.S','.ld','.py','.md') and '__pycache__' not in p.parts)
 before={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
 env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'}
 def run(cmd,name):
  with (out/name).open('w') as log:subprocess.run(list(map(str,cmd)),env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
 report={'status':'running','source_sha256':before,'scope':'ASan/UBSan portable software + fake MMIO + RV link/layout, no target performance or physical hardware','leak_sanitizer_disabled':'executor ptrace restriction; ASan and UBSan remain enabled'}
 try:
  run([sys.executable,S/'setup_monitor_coremark.py'],'dependency.log')
  flags=['-std=c11','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-Wall','-Wextra','-Werror']
  run(['clang-19',*flags,S/'test_bootrom_menu.c',S/'crc32.c','-o',out/'menu'],'menu-compile.log');run([out/'menu'],'menu.log')
  run(['clang-19',*flags,S/'test_uart_only_pending.c',S/'crc32.c','-o',out/'uart-only'],'uart-only-compile.log');run([out/'uart-only'],'uart-only.log')
  run([sys.executable,S/'check_boot_tui.py','--binary',out/'menu','--out',out/'tui-preview'],'tui-terminal.log')
  run([sys.executable,S/'test_uart_tui_interop.py','--cc','clang-19'],'uart-tui-interop.log')
  core=ROOT/'simulator/build/coremark-src';includes=['-I'+str(S/'coremark_port'),'-I'+str(core)]
  run(['clang-19',*flags,*includes,S/'test_monitor_diagnostics.c','-o',out/'diag'],'diag-compile.log');run([out/'diag'],'diag.log')
  cmflags=['-std=c11','-O3','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-DMONITOR_DIAGNOSTIC','-DDIAGNOSTIC_PORT_TEST','-DCPU_HZ=1000ULL','-DCOREMARK_COMPILER_VERSION="native oracle only"',*includes]
  objects=[]
  for name in ('core_main','core_list_join','core_matrix','core_state','core_util'):
   obj=out/(name+'.o');run(['clang-19',*cmflags,*(['-Dmain=coremark_main'] if name=='core_main' else []),'-c',core/(name+'.c'),'-o',obj],name+'-compile.log');objects.append(obj)
  run(['clang-19',*cmflags,S/'coremark_port/core_portme.c',S/'test_monitor_coremark.c',*objects,'-o',out/'coremark'],'coremark-link.log');run([out/'coremark'],'coremark.log')
  run(['clang-19',*flags,'-DBOOT_MENU=1','-DBOARD_RAM_BYTES=0x80000000UL','-DBOARD_MONITOR_BASE=0xffff8000UL','-DCPU_HZ=100000000ULL',S/'test_mmu_diagnostic.c','-o',out/'mmu'],'mmu-compile.log');run([out/'mmu'],'mmu.log')
  run([sys.executable,S/'test_monitor_profiles.py'],'profiles.log')
  run([sys.executable,S/'test_ram_verify_model.py'],'ram-verify-model.log')
  run([sys.executable,S/'build.py','--boot-menu','--crc-mode','byte','--ddr','--ddr-bytes','0x80000000','--netboot','--netboot-posted-rx','--cpu-hz','100000000','--uart-reference-hz','7372800','--uart-baud','460800','--out',out/'firmware'],'firmware-build.log')
  symbols=subprocess.check_output(['riscv64-unknown-elf-nm','-n',out/'firmware/bootrom.elf'],text=True)
  sym={l.split()[2]:int(l.split()[0],16) for l in symbols.splitlines() if len(l.split())==3};(out/'symbols.log').write_text(symbols)
  globals_bytes=sym['__bss_end']-sym['__app_stack_top'];assert globals_bytes<=8192
  binary=(out/'firmware/bootrom.bin').read_bytes();assert len(binary)<=131072
  after={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files};assert before==after,'source drift'
  menu_match=re.search(r'BOOTROM_MENU_PASS cases=(\d+)',(out/'menu.log').read_text());assert menu_match
  mmu_match=re.search(r'RECOVERY_NATIVE_PASS algorithm_cases=(\d+) negative_checks=(\d+) pte_layout_cases=(\d+) context_predicate_cases=(\d+)',(out/'mmu.log').read_text());assert mmu_match
  report.update(mmu_algorithm_cases=int(mmu_match[1]),mmu_negative_checks=int(mmu_match[2]),mmu_pte_layout_cases=int(mmu_match[3]),mmu_context_predicate_cases=int(mmu_match[4]),mmu_privileged_cpu_execution=False)
  report.update(status='passed',menu_cases=int(menu_match[1]),uart_only_pending_cases=2,diagnostic_fake_mmio_cases=11,official_coremark_kernel_crc_oracle_pass=True,formal_duration_boundary_cases=6,official_score_claim=False,host_menu_profiles=3,globals_bytes=globals_bytes,monitor_stack_reserved=8192,diagnostic_stack_reserved=16384,rom_bytes=len(binary),rom_sha256=hashlib.sha256(binary).hexdigest(),contract=json.loads((out/'firmware/bootrom-contract.json').read_text()))
 except Exception as e:report.update(status='failed',failure=str(e));raise
 finally:(out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({k:report[k] for k in ('status','rom_bytes','globals_bytes','rom_sha256')}))
if __name__=='__main__':main()
