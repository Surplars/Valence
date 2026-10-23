#!/usr/bin/env python3
"""Real rate-CSR/CDC RTL acceptance. Physical backend is a protocol oracle here;
all native DRP profiles and a representative full-I1 roundtrip are separate gates.
"""
import argparse, hashlib, json, subprocess
from pathlib import Path


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def bench():
    ports = ['.sourceClock(source)', '.alwaysOnClock(aon)', '.commonReset(reset)',
             '.registers_request_valid(qvalid)', '.registers_request_ready(qready)',
             '.registers_request_bits_address(address)', '.registers_request_bits_write(write)',
             '.registers_request_bits_size(3\'d3)', '.registers_request_bits_data(data)',
             '.registers_request_bits_byteEnable(8\'hff)', '.registers_response_valid(rvalid)',
             '.registers_response_ready(rready)', '.registers_response_bits_data(rdata)',
             '.registers_response_bits_error(rerror)']
    for d in range(2):
        values = {'present': "1'b1", 'drainAcks': f"quiesce[{d}] ? 4'hf : 4'h0",
                  'gateClosed': f'!enabled[{d}]', 'gateOpen': f'enabled[{d}]', 'locked': "1'b1",
                  'resumed': f'!quiesce[{d}]', 'quiesce': f'quiesce[{d}]', 'clockEnable': f'enabled[{d}]',
                  'program_ready': "1'b1", 'program_valid': f'pvalid[{d}]',
                  'program_bits_hz': f'phz[{d}]', 'program_bits_token': f'ptoken[{d}]',
                  'program_bits_parameters': f'params[{d}]', 'program_bits_fallback': f'fallback[{d}]',
                  'result_valid': f'resultValid[{d}]', 'result_bits_hz': f'resultHz[{d}]',
                  'result_bits_token': f'resultToken[{d}]', 'result_bits_error': f'resultError[{d}]'}
        ports += [f'.endpoints_{d}_{n}({v})' for n,v in values.items()]
    text = r'''
`timescale 1ns/1ps
module software_rate_tb;
reg source=0,aon=0,reset=1;
always #7 source=~source;
always #5 aon=~aon;
reg qvalid=0,rready=0,write=0;
reg [63:0] address=0,data=0;
wire qready,rvalid,rerror;wire [63:0] rdata;
wire [1:0] quiesce,enabled,pvalid,fallback;
wire [31:0] phz[0:1],ptoken[0:1];wire [23:0] params[0:1];
reg [1:0] resultValid=0,resultError=0;
reg [31:0] resultHz[0:1],resultToken[0:1];
integer programs[0:1], completions[0:1], expectedHz[0:1], expectedParams[0:1];
integer d,n,m,o,beforeProgram;
reg injectError=0;
reg [63:0] value;
ClockRateManagementBoundary dut(PORTS);
always @(posedge aon) begin
  if(reset) begin
    resultValid<=0;resultError<=0;
    for(integer i=0;i<2;i=i+1)programs[i]=0;
  end else for(integer i=0;i<2;i=i+1) begin
    resultValid[i]<=pvalid[i];resultError[i]<=0;
    if(pvalid[i])begin
      if(fallback[i])begin
        if(phz[i]!=50000000 || params[i]!=24'h14280a)$fatal(1,"fallback tuple not immutable boot50");
      end else if(phz[i]!=expectedHz[i] || params[i]!=expectedParams[i])
        $fatal(1,"accepted Hz/parameters changed under staging or backpressure");
      resultHz[i]<=phz[i];resultToken[i]<=ptoken[i];programs[i]=programs[i]+1;
      if(injectError)begin resultError[i]<=1;injectError=0;end
    end
  end
end
task access(input integer bank,input integer offset,input bit wr,input [63:0] payload,
            input bit errorExpected,input integer holdCycles,output [63:0] answer);
 integer limit,prior;
 begin
  @(negedge source);address=64'h10080800+bank*128+offset;data=payload;write=wr;qvalid=1;rready=0;
  prior=programs[bank];limit=0;
  do begin @(posedge source);limit=limit+1;if(limit>1000)$fatal(1,"request timeout");end while(!qready);
  @(negedge source);qvalid=0;
  repeat(holdCycles)begin
    @(posedge source);
    if(wr&&offset==0&&programs[bank]!=prior)$fatal(1,"program began before response receipt");
  end
  @(negedge source);rready=1;limit=0;
  do begin @(posedge source);limit=limit+1;if(limit>1000)$fatal(1,"reply timeout");end while(!rvalid);
  if(rerror!==errorExpected)$fatal(1,"wrong MMIO error bank=%0d offset=%h wr=%b error=%b expected=%b",bank,offset,wr,rerror,errorExpected);
  answer=rdata;@(negedge source);rready=0;
 end
endtask
task waitIdle(input integer bank,input integer expected);
 integer tries;
 begin
  tries=0;
  do begin access(bank,80,0,0,0,0,value);tries=tries+1;
    if(tries>1000)$fatal(1,"completion timeout bank=%0d wanted=%0d got=%0d",bank,expected,value);
  end while(value!=expected);
  do begin access(bank,88,0,0,0,0,value);tries=tries+1;if(tries>2000)$fatal(1,"idle timeout");end while(value!=0);
 end
endtask
task change(input integer bank,input integer hz,input integer mult,input integer divideOut,input bit corruptResult);
 begin
  expectedHz[bank]=hz;expectedParams[bank]=(divideOut<<16)|(mult<<8)|10;
  access(bank,48,1,expectedParams[bank],0,0,value);
  injectError=corruptResult;
  access(bank,0,1,hz,0,8,value);
  // Writing a later staged profile must never alter the owned transaction.
  access(bank,48,1,24'h03200a,0,0,value);
  completions[bank]=completions[bank]+1;
  waitIdle(bank,completions[bank]);
  access(bank,8,0,0,0,0,value);
  if(value!=(corruptResult?50000000:hz))$fatal(1,"configured Hz mismatch");
 end
endtask
initial begin
 for(integer i=0;i<2;i=i+1)begin programs[i]=0;completions[i]=0;expectedHz[i]=0;expectedParams[i]=0;end
 repeat(8)@(posedge source);@(negedge source);reset=0;
 for(d=0;d<2;d=d+1)begin
  waitIdle(d,0);
  access(d,120,0,0,0,0,value);
  if(value!=($test$plusargs("strict")?64'h4352000100000002:64'h4352000300000002))$fatal(1,"wrong ABI capability");
  access(d,56,0,0,0,0,value);if(value!=64'h000080033e200a0a)$fatal(1,"wrong parameter bounds");
  if($test$plusargs("strict"))begin
   access(d,48,1,24'h0a280a,0,0,value);access(d,0,1,100000000,1,0,value);
   access(d,24,0,0,0,0,value);if(!(value&2))$fatal(1,"strict policy failed to reject unqualified parameters");
  end else begin
   for(n=50;n<=150;n=n+5)begin o=(n<80)?20:10;m=n*o/25;change(d,n*1000000,m,o,0);end
   change(d,50000000,40,20,0);
   // Valid future firmware profiles not in the initial 21-point software list.
   change(d,10000000,32,80,0);change(d,(d==0)?300000000:250000000,(d==0)?60:50,5,0);
   change(d,50000000,40,20,0);
   beforeProgram=programs[d];
   access(d,48,1,64'h10014280a,1,0,value);
   access(d,48,0,0,0,0,value);if(value!=24'h03200a)$fatal(1,"invalid staging changed value");
   access(d,0,1,100000001,1,0,value);
   access(d,48,1,24'h142809,0,0,value);access(d,0,1,50000000,1,0,value);
   access(d,48,1,24'h141f0a,0,0,value);access(d,0,1,50000000,1,0,value);
   access(d,48,1,24'h02400a,0,0,value);access(d,0,1,50000000,1,0,value);
   // Exact-frequency tuples with uncharacterized M63/64 must be rejected.
   access(d,48,1,24'h0f3f0a,0,0,value);access(d,0,1,105000000,1,0,value);
   access(d,48,1,24'h10400a,0,0,value);access(d,0,1,100000000,1,0,value);
   access(d,64,1,48,1,0,value);
   repeat(10)@(posedge aon);if(programs[d]!=beforeProgram)$fatal(1,"invalid request reached backend");
   access(d,24,1,1023,0,0,value);
   change(d,100000000,40,10,1);
   access(d,24,0,0,0,0,value);if(!(value&64))$fatal(1,"backend failure did not record program error");
  end
 end
 $display("SOFTWARE_RATE_MMIO_PASS strict=%0d programs_cpu=%0d programs_fabric=%0d",$test$plusargs("strict"),programs[0],programs[1]);$finish;
end
initial begin #10000000;$fatal(1,"global timeout");end
endmodule
'''
    return text.replace('PORTS', ',\n'.join(ports))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rtl',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    p.add_argument('--strict',action='store_true');a=p.parse_args();a.out.mkdir(exist_ok=False)
    rtl=sorted(a.rtl.resolve().glob('*.sv'));assert rtl
    tb=a.out/'software_rate_tb.sv';tb.write_text(bench());binary=a.out/'sim.vvp'
    receipt={'status':'RUNNING','scope':__doc__,'strict':a.strict,'rtl_sha256':{f.name:sha(f) for f in rtl},'cases':[]}
    try:
        for name,cmd in [('compile',['iverilog','-g2012','-s','software_rate_tb','-o',str(binary),*map(str,rtl),str(tb)]),
                         ('run',['vvp',str(binary)]+(['+strict']if a.strict else []))]:
            r=subprocess.run(cmd,capture_output=True,text=True,timeout=120);log=r.stdout+r.stderr
            (a.out/(name+'.log')).write_text(log);receipt['cases'].append({'name':name,'exit':r.returncode})
            assert r.returncode==0,log[-3000:]
            if name=='run':assert 'SOFTWARE_RATE_MMIO_PASS' in log
        receipt['status']='PASS'
    except BaseException as e:receipt.update(status='FAIL',error=repr(e));raise
    finally:(a.out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('PASS '+str(a.out/'receipt.json'))
if __name__=='__main__':main()
