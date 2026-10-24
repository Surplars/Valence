#!/usr/bin/env python3
"""Bounded real-I1 relocation smoke; no networking, board, or performance claim."""
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
from cpu_boot_native import run, write_rom, sha
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('output',type=Path);p.add_argument('--rtl',type=Path,required=True)
    p.add_argument('--prefix',default='riscv64-unknown-elf-')
    a=p.parse_args();out=a.output.resolve();out.mkdir(exist_ok=False)
    rtl=a.rtl.resolve();manifest=rtl/'emission-profile.json'
    emission=json.loads(manifest.read_text())
    for k,v in {'cpu':'i1','programmableRom':True,'clockProfile':'boot50-static','romBytes':131072,'instructionCacheBytes':32768,'dataCacheBytes':32768}.items():
        if emission.get(k)!=v:raise ValueError('wrong emission '+k)
    files=sorted(rtl.glob('*.sv'))
    for f in files:
        if emission['artifacts'].get(str(f))!=sha(f):raise ValueError('RTL hash changed')
    record={'status':'RUNNING','scope':'actual I1 + cache/fabric/AXI, production relocation and launch assembly, test-only high code and DDR initialization; not full stager networking, board, or throughput',
            'emission_sha256':sha(manifest),'rtl_sha256':{str(f):sha(f) for f in files},'commands':[],'results':[]}
    def save():(out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
    def execute(cmd,name,expected=None,negative=False):
        record['commands'].append(list(map(str,cmd)));save()
        r=run(cmd,out/name,300);record['results'].append(dict(log=name,**r));save()
        log=(out/name).read_text()
        if r['timed_out'] or r['disk_floor_breached'] or (r['returncode']!=0)!=negative or (expected and expected not in log):raise RuntimeError(name+' failed')
    flags=['-march=rv64im_zicsr_zifencei','-mabi=lp64','-mcmodel=medany','-mno-relax','-msmall-data-limit=0','-Os','-ffreestanding','-fno-builtin','-nostdlib','-nostartfiles','-Wl,--no-relax','-Wall','-Wextra','-Werror']
    fw=ROOT/'fpga/firmware'
    execute([a.prefix+'gcc',*flags,'-T'+str(fw/'netboot_stager.ld'),fw/'netboot_stager_start.S',HERE/'netboot_relocation_smoke.c','-o',out/'smoke.elf'],'build-smoke.log')
    execute([a.prefix+'objcopy','-O','binary',out/'smoke.elf',out/'smoke.bin'],'objcopy-smoke.log')
    symbols={name:int(address,16) for address,_,name in re.findall(r'^([0-9a-f]+)\s+(\w)\s+(\S+)$',subprocess.check_output([a.prefix+'nm','-n',out/'smoke.elf'],text=True),re.M)}
    for name,addr in [('rom',0x80000000),('target',0x80210000)]:
        execute([a.prefix+'gcc',*flags,'-Wl,-Ttext='+hex(addr),HERE/('netboot_relocation_'+name+'.S'),'-o',out/(name+'.elf')],'build-'+name+'.log')
        execute([a.prefix+'objcopy','-O','binary',out/(name+'.elf'),out/(name+'.bin')],'objcopy-'+name+'.log')
    write_rom((out/'rom.bin').read_bytes(),out/'rom.hex')
    data=bytearray(0x40000);smoke=(out/'smoke.bin').read_bytes();data[:len(smoke)]=smoke
    target=(out/'target.bin').read_bytes();data[0x10000:0x10000+len(target)]=target
    def hexfile(data,path):path.write_text(''.join(f'{int.from_bytes(data[n:n+8],"little"):016x}\n' for n in range(0,len(data),8)))
    hexfile(data,out/'ram.hex')
    bad=bytearray(data);launch_offset=symbols['__stage_load_start']-0x80200000+symbols['stage_launch']-0xffe00000
    bad[launch_offset:launch_offset+8]=(0x00050293).to_bytes(4,'little')+(0x00000013).to_bytes(4,'little')
    hexfile(bad,out/'ram-bad.hex')
    tb=(HERE/'cpu_boot_tb.sv').read_text()
    cut=tb.index('  reg [63:0] trace_pc[0:15]');end=tb.index('\nendmodule',cut)
    monitor='''
  integer retired=0, high_retired=0, rom_retired=0, uart_count=0, guest_done=0;
  task observe(input valid,input [63:0] pc);
    if(valid) begin
      retired=retired+1;
      if(pc>=64'hffe00000 && pc<64'hffe20000) high_retired=high_retired+1;
      if(pc==64'hSTAGE_TRAP || pc==64'h80200060) $fatal(1,"RELOCATION_GUEST_FAILURE pc=%h",pc);
      if(pc==64'h80210018) begin
        if(high_retired<20 || read_count==0 || write_count==0) $fatal(1,"RELOCATION_COVERAGE");
        $display("REAL_I1_RELOCATION_PASS high_retired=%0d retired=%0d reads=%0d writes=%0d",high_retired,retired,read_count,write_count); $finish;
      end
    end
  endtask
  always @(posedge cpuClock) begin
    if(io_bootEnable) cpu_edges=cpu_edges+1;
    if(cpu_edges>maxcycles) $fatal(1,"RELOCATION_TIMEOUT");
    if(!commonColdReset) begin
      if(io_trap_valid) $fatal(1,"RELOCATION_TRAP pc=%h cause=%h",io_trap_bits_pc,io_trap_bits_cause);
      observe(io_retire_0_valid,io_retire_0_bits_pc);
      observe(io_retire_1_valid,io_retire_1_bits_pc);
    end
  end
'''.replace('STAGE_TRAP',f'{symbols["stage_trap"]:x}')
    tb=tb[:cut]+monitor+tb[end:]
    tb=tb.replace('reg [63:0] monitor_ram[0:4095];','reg [63:0] monitor_ram[0:16383]; reg [2047:0] ram_hex;')
    tb=tb.replace('for(init_i=0;init_i<4096;init_i=init_i+1) monitor_ram[init_i]=0;', '''for(init_i=0;init_i<16384;init_i=init_i+1) monitor_ram[init_i]=64'ha5a5a5a5a5a5a5a5;
    if(!$value$plusargs("ram_hex=%s",ram_hex)) $fatal(1,"RAM_IMAGE_REQUIRED");
    $readmemh(ram_hex,ram);''')
    tb=tb.replace("32'h7fdf8000","32'h7fc00000").replace("32'h7fe00000","32'h7fc20000")
    (out/'testbench.sv').write_text(tb)
    execute([os.environ.get('IVERILOG','iverilog'),'-DCOMMON_INDEPENDENT_FIXED_DOMAINS','-g2012','-DSTOP_COND=1','-DASSERT_VERBOSE_COND=1','-s','cpu_boot_tb','-o',out/'smoke.vvp',*files,out/'testbench.sv'],'compile.log')
    common=[os.environ.get('VVP','vvp'),out/'smoke.vvp','+rom_hex='+str(out/'rom.hex'),'+cpu_half=10000','+fabric_half=10000','+maxcycles=150000']
    execute([*common,'+ram_hex='+str(out/'ram.hex')],'positive.log','REAL_I1_RELOCATION_PASS')
    execute([*common,'+ram_hex='+str(out/'ram-bad.hex')],'negative.log','RELOCATION_TRAP',True)
    record['status']='PASS_REAL_I1_RELOCATION_AND_BAD_ENTRY_NEGATIVE_NOT_BOARD';record['symbols']=symbols
    record['source_sha256']={str(f):sha(f) for f in [Path(__file__),HERE/'netboot_relocation_smoke.c',HERE/'netboot_relocation_rom.S',HERE/'netboot_relocation_target.S',fw/'netboot_stager_start.S',fw/'netboot_stager.ld',HERE/'cpu_boot_tb.sv']};save()
    print(record['status'])
if __name__=='__main__':main()
