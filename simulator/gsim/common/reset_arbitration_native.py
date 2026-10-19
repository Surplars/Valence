#!/usr/bin/env python3
"""Four-state reset/acceptance and known-state round-robin oracle. No FPGA signoff."""
import argparse,hashlib,json,os,pathlib,re,subprocess,sys,time
P=pathlib.Path
ROOT=P(__file__).resolve().parents[3]
def sha(p):return hashlib.sha256(P(p).read_bytes()).hexdigest()
def tb(n,legacy):
 connects=['.clock(clock)','.reset(reset)','.io_out_ready(ready)','.io_out_valid(valid)','.io_out_bits(data)','.io_chosen(chosen)']
 for i in range(n):connects += [f'.io_in_{i}_valid(mask[{i}])',f'.io_in_{i}_bits(payload[{i}])',f'.io_in_{i}_ready(inready[{i}])']
 init='dut.ports_arbiter.ctrl_validMask_grantMask_lastGrant = last;' if legacy else ''
 return '''`timescale 1ns/1ps
module tb;
  reg clock=0,reset=1,ready=0; always #5 clock=~clock;
  localparam N=%d; reg [N-1:0] mask=0; wire [N-1:0] inready;
  reg [15:0] payload[0:N-1]; wire [15:0] data; wire valid; wire [$clog2(N)-1:0] chosen;
  CommonResetArbiterFixture dut(%s);
  integer last=N-1,expected=0,found,j,k,t,checks=0,fires=0; integer accepted[0:N-1];
  integer seed=31,negative=0,known=0;
  task cold; begin
    @(negedge clock);reset=1;mask=0;ready=0;repeat(2)@(posedge clock);
    @(negedge clock);reset=0;last=N-1;
  end endtask
  task step(input integer offered,input integer downstream);
    begin
      @(negedge clock);mask=offered;ready=downstream;
      for(j=0;j<N;j=j+1)payload[j]=16'h5100+j;
      expected=0;found=0;
      for(j=1;j<=N;j=j+1)begin
        k=(last+j)%%N;
        if(!found && ((offered>>k)&1))begin expected=k;found=1;end
      end
      #1;
      if(valid !== (offered!=0))$fatal(1,"RESET_RR_VALID_ORACLE");
      if(offered!=0)begin
        if(chosen !== expected || data !== 16'h5100+expected)$fatal(1,"RESET_RR_SELECTION_ORACLE");
        for(j=0;j<N;j=j+1)if((offered>>j)&1)
          if(inready[j] !== (downstream && expected==j))$fatal(1,"RESET_RR_FOUR_STATE_ACCEPTANCE_ORACLE n=%%d source=%%d ready=%%b chosen=%%b",N,j,inready[j],chosen);
      end
      checks=checks+1;
      @(posedge clock);
      if(found && downstream)begin last=expected;fires=fires+1;accepted[expected]=accepted[expected]+1;end
      #1;
    end
  endtask
  initial begin
    negative=$test$plusargs("negative");known=$test$plusargs("known_state");
    for(j=0;j<N;j=j+1)begin payload[j]=0;accepted[j]=0;end
    cold;
    if(negative)begin step(2,1);$fatal(1,"NEGATIVE_DID_NOT_REJECT");end
    if(known)begin
      for(t=0;t<N;t=t+1)begin
        // Cross product: each mask begins from each specified known priority.
        for(tmask=1;tmask<(1<<N);tmask=tmask+1)begin
          cold;last=t;%s
          step(tmask,1);
        end
      end
    end else begin
      for(t=0;t<N;t=t+1)begin cold;step(1<<t,1);end
      // Every possible last-grant state is established by a real accepted
      // singleton, then every mask is checked without internal state injection.
      for(t=0;t<N;t=t+1)for(tmask=1;tmask<(1<<N);tmask=tmask+1)begin cold;step(1<<t,1);step(tmask,1);end
      cold;for(t=0;t<16*N;t=t+1)step((1<<N)-1,1);
      for(t=0;t<N;t=t+1)begin
        cold;step(1<<t,0);step(0,0);step(1<<((t+1)%%N),1);
      end
      cold;
      for(t=0;t<256;t=t+1)begin seed=(seed*1103515245+12345)&32'h7fffffff;step(seed&((1<<N)-1),(t%%5)!=0);end
      cold;step(1<<(N-1),0);cold;step(2,1);
    end
    $display("RESET_RR_NATIVE_PASS n=%%0d known=%%0d checks=%%0d fire=%%0d",N,known,checks,fires);$finish;
  end
  integer tmask;
endmodule
'''%(n,','.join(connects),init)

def main():
 a=argparse.ArgumentParser();a.add_argument('output',type=P);a.add_argument('--classpath',type=P,required=True);a.add_argument('--iverilog',type=P,required=True);a.add_argument('--vvp',type=P,required=True);args=a.parse_args()
 out=args.output.resolve();out.mkdir(exist_ok=False);records=[]
 def run(cmd,name,expect=0,anchor=None):
  start=time.monotonic();p=subprocess.run(list(map(str,cmd)),cwd=ROOT,capture_output=True,text=True,timeout=120)
  text=p.stdout+p.stderr;(out/name).write_text(text)
  r={'command':list(map(str,cmd)),'returncode':p.returncode,'seconds':time.monotonic()-start,'log':name};records.append(r)
  if expect==0:assert p.returncode==0,(name,text[-4000:])
  else:assert p.returncode!=0 and anchor in text,(name,text[-4000:])
  return text
 cp=args.classpath.read_text().strip()
 for n in [2,3,4]:
  for arm in ['fixed','legacy']:
   d=out/f'{arm}-{n}';d.mkdir();run(['java','-cp',cp,'platform.CommonResetArbiterMain',d,n,arm],f'{arm}-{n}-emit.log')
   t=d/'tb.sv';t.write_text(tb(n,arm=='legacy'))
   sv=sorted(d.glob('*.sv'));run([args.iverilog,'-g2012','-s','tb','-o',d/'run.vvp',*sv],f'{arm}-{n}-compile.log')
   run([args.vvp,d/'run.vvp',*(['+known_state'] if arm=='legacy' else [])],f'{arm}-{n}-run.log')
   if arm=='legacy' and n==3:run([args.vvp,d/'run.vvp','+negative'],f'{arm}-{n}-first-nonzero-negative.log',1,'RESET_RR_FOUR_STATE_ACCEPTANCE_ORACLE')
 sources=[ROOT/'src/main/scala/ip/bus/ResetDefinedRRArbiter.scala',ROOT/'src/test/scala/platform/CommonResetArbiterMain.scala',P(__file__).resolve()]
 receipt={'status':'PASS_NATIVE_RESET_SELECTION_AND_KNOWN_STATE_RR','records':records,'source_sha256':{str(p):sha(p) for p in sources},'artifacts':{p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()},'limits':['Digital four-state/known-state arbiter-only verification','No payload stage or owner credit added','No irrevocable lock is added; cancellation before acceptance remains permitted','No routed timing or full CPU qualification']}
 (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(receipt['status'])
if __name__=='__main__':main()
