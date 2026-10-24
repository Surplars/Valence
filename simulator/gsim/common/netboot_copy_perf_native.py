#!/usr/bin/env python3
"""Matched ROM/RAM old/new copy microbenchmark on frozen full I1 RTL."""
import argparse,json,os,re,subprocess,zlib
from pathlib import Path
from cpu_boot_native import run,write_rom,sha
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('out',type=Path);p.add_argument('--rtl',type=Path,required=True);p.add_argument('--prefix',default='riscv64-unknown-elf-');a=p.parse_args()
 out=a.out.resolve();out.mkdir(exist_ok=False);rtl=a.rtl.resolve();emission=json.loads((rtl/'emission-profile.json').read_text())
 for k,v in {'cpu':'i1','clockProfile':'boot50-static','programmableRom':True,'romBytes':131072,'instructionCacheBytes':32768,'dataCacheBytes':32768,'tlbEntries':16,'cacheWays':2,'homeLines':1024,'ddrSlots':4,'ddrWriteSlots':2}.items():
  if emission.get(k)!=v:raise ValueError('geometry mismatch '+k)
 files=sorted(rtl.glob('*.sv'))
 for f in files:
  if emission['artifacts'].get(str(f))!=sha(f):raise ValueError('frozen RTL mismatch')
 sources=[Path(__file__),HERE/'netboot_copy_perf.c',HERE/'netboot_copy_perf_driver.c',HERE/'netboot_copy_perf_start.S',HERE/'netboot_copy_perf.ld',ROOT/'fpga/firmware/crc32.c',ROOT/'fpga/firmware/netboot_copy.h',HERE/'cpu_boot_tb.sv']
 frozen={str(f):sha(f) for f in sources}
 record={'status':'RUNNING','source_sha256':frozen,'emission_sha256':sha(rtl/'emission-profile.json'),'rtl_sha256':{str(f):sha(f) for f in files},'scope':'frozen boot50-static full I1, copy only ROM/RAM identical instruction bytes; one production mode3 CRC measured separately always ROM with RAM table; not board/network throughput','clocks':{'cpu_hz':50000000,'fabric_hz':50000000,'ddr_hz':250000000},'cache_state':'Each config FENCE.I, source read-prewarm and destination write-prewarm; one measured call with cold RAM instructions; ROM remains uncached. One final fixed CRC stage, separate from copy windows; table state follows all preceding configs; CRC phases not compared as placement benchmark.','bytes_per_copy':128,'alignments':[[6,4]],'commands':[],'results':[]}
 def save():(out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
 def execute(cmd,name,expected=None):
  record['commands'].append(list(map(str,cmd)));save();r=run(cmd,out/name,300);record['results'].append(dict(log=name,**r));save()
  if r['returncode'] or r['timed_out'] or r['disk_floor_breached'] or (expected and expected not in (out/name).read_text()):
   record['status']='FAIL_OR_RESOURCE_BOUND';save();raise RuntimeError(name+' failed')
 flags=['-march=rv64im_zicsr_zifencei','-mabi=lp64','-mcmodel=medany','-mno-relax','-msmall-data-limit=0','-Os','-ffreestanding','-fno-builtin','-nostdlib','-nostartfiles','-Wall','-Wextra','-Werror']
 crcs=[zlib.crc32(bytes(((i+offset)*37+11)&255 for i in range(128))) for offset in [0,2,6]]
 for name,source in [('start',HERE/'netboot_copy_perf_start.S'),('driver',HERE/'netboot_copy_perf_driver.c'),('copy',HERE/'netboot_copy_perf.c'),('crc',ROOT/'fpga/firmware/crc32.c')]:
  execute([a.prefix+'gcc',*flags,'-DFIRMWARE_CRC_MODE=3',*[f'-DCRC{o}={v}U' for o,v in zip([0,2,6],crcs)],'-c',source,'-o',out/(name+'.o')],'build-'+name+'.log')
 execute([a.prefix+'gcc',*flags,'-Wl,--no-relax','-T'+str(HERE/'netboot_copy_perf.ld'),*[out/(n+'.o') for n in ['start','driver','copy','crc']],'-lgcc','-o',out/'guest.elf'],'link.log')
 execute([a.prefix+'objcopy','-O','binary',out/'guest.elf',out/'guest.bin'],'objcopy.log')
 symbols={name:int(addr,16) for addr,_,name in re.findall(r'^([0-9a-f]+)\s+(\w)\s+(\S+)$',subprocess.check_output([a.prefix+'nm','-n',out/'guest.elf'],text=True),re.M)}
 (out/'disassembly.txt').write_text(subprocess.check_output([a.prefix+'objdump','-d',out/'guest.elf'],text=True))
 write_rom((out/'guest.bin').read_bytes(),out/'rom.hex')
 tb=(HERE/'cpu_boot_tb.sv').read_text();cut=tb.index('  reg [63:0] trace_pc[0:15]');end=tb.index('\nendmodule',cut)
 monitor='''
 integer retired=0,rom_retired=0,uart_count=0,guest_done=0;
 integer case_i,byte_i,base_i;reg [63:0] checked_word;reg [7:0] checked_byte,expected_byte;
 integer active=0,current_id=-1,completed=0,crc_completed=0;
 integer start_cycles,start_retired,start_reads,start_writes,start_b;
 time start_time;
 task observe(input valid,input [63:0] pc,input writesRd,input [4:0] rd,input [63:0] data);
 if(valid) begin
  retired=retired+1;
  if(pc==64'hFAIL) $fatal(1,"COPY_PERF_DATA_OR_CRC_ORACLE");
  if(pc==64'hBEGIN || pc==64'hCRC_BEGIN) begin
   if(active || !writesRd || rd!=31 || data>=4) $fatal(1,"COPY_PERF_BEGIN_ORACLE");
   if(pc==64'hBEGIN && (data!=completed || crc_completed!=0)) $fatal(1,"COPY_PERF_ORDER");
   if(pc==64'hCRC_BEGIN && (data!=0 || completed!=4 || crc_completed!=0)) $fatal(1,"COPY_PERF_CRC_ORDER");
   active=pc==64'hBEGIN ? 1 : 2;current_id=data;start_cycles=cpu_edges;start_retired=retired;start_time=$time;
   start_reads=read_count;start_writes=write_count;start_b=b_completed;
   $display("COPY_PERF_BEGIN kind=%0d id=%0d pc=%h",active,current_id,pc);$fflush();
  end
  if(pc==64'hEND || pc==64'hCRC_END) begin
   if(!active || data!=current_id || !writesRd || rd!=31) $fatal(1,"COPY_PERF_END_ORACLE");
   $display("COPY_PERF_WINDOW kind=%0d id=%0d cpu_cycles=%0d retired=%0d time_ps=%0t ar=%0d aw=%0d b=%0d",active,current_id,cpu_edges-start_cycles,retired-start_retired,$time-start_time,read_count-start_reads,write_count-start_writes,b_completed-start_b);$fflush();
   if(active==1)completed=completed+1;else crc_completed=crc_completed+1;active=0;
  end
  if(pc==64'hDONE) begin
   if(active || completed!=4 || crc_completed!=1 || b_completed!=write_count) $fatal(1,"COPY_PERF_FINAL_ORACLE");
   for(case_i=0;case_i<4;case_i=case_i+1)begin
    base_i=32'h10000+(2+3*case_i)*32'h1000;
    for(byte_i=0;byte_i<192;byte_i=byte_i+1)begin
     checked_word=memory_read(base_i+byte_i);checked_byte=checked_word>>(8*(byte_i%8));
     if(checked_byte!==((byte_i*37+11)&255))$fatal(1,"COPY_PERF_SOURCE_ORACLE case=%0d byte=%0d",case_i,byte_i);
     checked_word=memory_read(base_i+32'h800+byte_i);checked_byte=checked_word>>(8*(byte_i%8));
     expected_byte=(byte_i>=4 && byte_i<132)?((byte_i+2)*37+11)&255:8'ha5;
     if(checked_byte!==expected_byte)$fatal(1,"COPY_PERF_DEST_ORACLE case=%0d byte=%0d got=%h expected=%h",case_i,byte_i,checked_byte,expected_byte);
    end
   end
   $display("COPY_PERF_TOTAL cpu_cycles=%0d retired=%0d time_ps=%0t",cpu_edges,retired,$time);
   $display("COPY_PERF_NATIVE_PASS");$finish;
  end
 end
 endtask
 always @(posedge cpuClock) begin
  if(io_bootEnable)cpu_edges=cpu_edges+1;
  if(io_bootEnable && cpu_edges%10000==0)begin $display("COPY_PERF_HEARTBEAT cpu=%0d retired=%0d active=%0d id=%0d pc=%h",cpu_edges,retired,active,current_id,io_retire_0_bits_pc);$fflush();end
  if(cpu_edges>2000000)$fatal(1,"COPY_PERF_CYCLE_BOUND");
  if(!commonColdReset)begin
   if(io_trap_valid)$fatal(1,"COPY_PERF_TRAP pc=%h cause=%h",io_trap_bits_pc,io_trap_bits_cause);
   observe(io_retire_0_valid,io_retire_0_bits_pc,io_retire_0_bits_writesRd,io_retire_0_bits_rd,io_retire_0_bits_data);
   observe(io_retire_1_valid,io_retire_1_bits_pc,io_retire_1_bits_writesRd,io_retire_1_bits_rd,io_retire_1_bits_data);
  end
 end
'''
 for token,name in [('CRC_BEGIN','mark_crc_begin'),('CRC_END','mark_crc_end'),('BEGIN','mark_begin'),('END','mark_end'),('FAIL','perf_fail'),('DONE','perf_done')]:monitor=monitor.replace("64'h"+token,"64'h"+format(symbols[name],'x'))
 tb=tb[:cut]+monitor+tb[end:]
 tb=tb.replace("    domains_started=1;",'    $display("COPY_PERF_ROM_PROGRAMMED");$fflush(); domains_started=1;')
 anchor='    for(init_i=0;init_i<32768;init_i=init_i+1) ram[init_i]=0;'
 assert tb.count(anchor)==1
 ram=bytearray((i*37+11)&255 for i in range(0x40000))
 execute([a.prefix+'objcopy','--dump-section','.bench='+str(out/'bench.bin'),'--dump-section','.data='+str(out/'table.bin'),out/'guest.elf'],'extract-preload.log')
 bench=(out/'bench.bin').read_bytes();table=(out/'table.bin').read_bytes()
 if len(bench)!=symbols['__bench_end']-symbols['__bench_start'] or len(table)!=symbols['__data_end']-symbols['__data_start']:raise ValueError('preload section span')
 ram[0x4000:0x4000+len(bench)]=bench
 ram[0x38000:0x38000+len(table)]=table
 record['external_ddr_preload']={'bench_bytes':len(bench),'bench_sha256':sha(out/'bench.bin'),'table_bytes':len(table),'table_sha256':sha(out/'table.bin'),'scope':'external DDR initial state only, no DUT state poke; production relocation independently proven'}
 (out/'ram.hex').write_text(''.join(f'{int.from_bytes(ram[n:n+8],"little"):016x}\n' for n in range(0,len(ram),8)))
 tb=tb.replace(anchor,'    $readmemh("'+str(out/'ram.hex')+'",ram);')
 (out/'testbench.sv').write_text(tb)
 execute([os.environ.get('IVERILOG','iverilog'),'-DCOMMON_INDEPENDENT_FIXED_DOMAINS','-g2012','-DSTOP_COND=1','-DASSERT_VERBOSE_COND=1','-s','cpu_boot_tb','-o',out/'perf.vvp',*files,out/'testbench.sv'],'compile.log')
 execute([os.environ.get('VVP','vvp'),out/'perf.vvp','+rom_hex='+str(out/'rom.hex'),'+cpu_half=10000','+fabric_half=10000'],'run.log','COPY_PERF_NATIVE_PASS')
 windows=[]
 for line in (out/'run.log').read_text().splitlines():
  if line.startswith('COPY_PERF_WINDOW '):windows.append({k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)})
 if len(windows)!=5:raise ValueError('missing windows')
 for f,h in frozen.items():
  if sha(f)!=h:raise ValueError('benchmark source changed during run')
 record.update(status='PASS_MATCHED_COPY_MICROBENCHMARK_NOT_BOARD_RATE',windows=windows,symbols=symbols,independent_crc32=crcs);save();print(record['status'])
if __name__=='__main__':main()
