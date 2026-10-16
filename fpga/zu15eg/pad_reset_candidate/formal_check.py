"""Bounded actual-source RTL proof under explicit ideal PLL/BUFG contracts."""
import argparse,hashlib,json,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--yosys',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 sources=[HERE/'native_gmac_pad_reset_clock.sv',ROOT/'fpga/zu15eg/native_tx_word_reset_boundary.sv',ROOT/'fpga/zu15eg/native_gmac_divided_clock.sv',ROOT/'fpga/zu15eg/native_rgmii_trispeed_quarter.sv']
 before={str(x.relative_to(ROOT)):sha(x) for x in sources}
 for x in sources:(out/x.name).write_bytes(x.read_bytes())
 native=sources[0].read_text();phase=native[native.index('        wire phase_inhibit='):native.index('        // Stage1 release')]
 control='''module Control(input tx_pad_source,cold_reset,pll_locked);
 wire locked;
'''+phase+'''
 reg [1:0] age;
 reg seen_reset=0;
 always @(posedge tx_pad_source or posedge phase_inhibit)
  if(phase_inhibit) age<=0;else if(age!=3) age<=age+1;
 always @(posedge tx_pad_source) if(phase_inhibit) seen_reset<=1;
 always @* if(seen_reset) begin
  assert(phase_reset[1]==(age<2));
  assert(locked==(pll_locked && age==3));
 end
endmodule
'''
 (out/'control.sv').write_text(control)
 contracts='''module PLLE4_ADV #(parameter CLKIN_PERIOD=4.0,CLKFBOUT_MULT=4,DIVCLK_DIVIDE=1,CLKOUT0_DIVIDE=2,CLKOUT1_DIVIDE=4,CLKOUT0_PHASE=0.0,CLKOUT1_PHASE=0.0,CLKOUT0_DUTY_CYCLE=0.5,CLKOUT1_DUTY_CYCLE=0.5,COMPENSATION="AUTO")
(input CLKIN,RST,PWRDWN,CLKFBIN,CLKOUTPHYEN,DCLK,DEN,DWE,input[6:0]DADDR,input[15:0]DI,output CLKFBOUT,CLKOUT0,CLKOUT1,LOCKED,CLKOUT0B,CLKOUT1B,CLKOUTPHY,output[15:0]DO,output DRDY);
 (* anyseq *) wire acquired;
 assign CLKOUT1=CLKIN;assign CLKOUT0=CLKIN;assign CLKFBOUT=CLKIN;assign LOCKED=acquired && !RST;
endmodule
module BUFG(input I,output O);assign O=I;endmodule
module BUFGCE_DIV #(parameter BUFGCE_DIVIDE=2,SIM_DEVICE="ULTRASCALE_PLUS") (input I,CE,CLR,output reg O);
 reg[2:0]count;
 always @(posedge I or posedge CLR)
  if(CLR)begin count<=0;O<=0;end
  else if(CE)begin O<=count<(BUFGCE_DIVIDE/2);count<=count==BUFGCE_DIVIDE-1?0:count+1;end
endmodule
module Topology(input clock,cold_reset,hot_reset,rx_present,delay_ready,output reg observed_raw=0);
 wire raw,pad,forward,refclk,locked,raw_reset,pad_reset;
 native_gmac_pad_reset_clock #(.ENABLE_PAD_DOMAIN_RESET(1)) dut(clock,cold_reset,raw,pad,forward,refclk,locked);
 native_tx_word_reset_boundary release_boundary(raw,cold_reset|!locked|hot_reset|!delay_ready,raw_reset,pad_reset);
 reg last_raw=0,was_locked=0;
 always @(posedge pad)begin
  if(locked && was_locked) assert(raw!=last_raw);
  last_raw<=raw;was_locked<=locked;
 end
 reg past_valid=0;
 always @($global_clock) begin
  past_valid<=1;
  if(past_valid && raw && !$past(raw)) begin assert(pad);observed_raw<=1;end
 end
 always @* begin assert(forward==raw);assert(raw_reset==pad_reset);end
endmodule
'''
 serializer=sources[3].read_text().split('    (* IODELAY_GROUP=')[0]+'''
 reg [2:0] proof_warm;
 always @(posedge tx_pad_clock or posedge serializer_reset)
   if(serializer_reset) proof_warm<=0; else if(proof_warm!=7) proof_warm<=proof_warm+1;
 always @(negedge tx_pad_clock) if(proof_warm>=2 && !serializer_reset)
   assert(phase_high==tx_clock);
 reg[11:0] proof_previous_word;
 always @(posedge tx_clock or posedge tx_pad_reset)
   if(tx_pad_reset) proof_previous_word<=0;
   else proof_previous_word<={txc_fall,txc_rise,tx_fall,tx_rise};
 always @(negedge tx_pad_clock) if(proof_warm>=2 && !serializer_reset) begin
   assert({rgmii_tx_control,rgmii_tx_data}==(tx_clock?proof_previous_word[4:0]:proof_previous_word[9:5]));

 end
 reg proof_last_half_clock;
 always @(negedge tx_pad_clock or posedge serializer_reset)
  if(serializer_reset)proof_last_half_clock<=0;
  else proof_last_half_clock<=tx_clock?proof_previous_word[10]:proof_previous_word[11];
 always @* if(proof_warm>=2 && !serializer_reset) begin
  if(!tx_pad_clock) assert(rgmii_tx_clock==(tx_clock?proof_previous_word[10]:proof_previous_word[11]));
  else assert(rgmii_tx_clock==proof_last_half_clock);
 end
endmodule
'''
 (out/'serializer.sv').write_text(serializer)
 contracts+='''
module ODDRE1 #(parameter SIM_DEVICE="ULTRASCALE_PLUS") (input C,D1,D2,SR,output Q);
 reg first,second;
 always @(posedge C or posedge SR) if(SR)begin first<=0;second<=0;end else begin first<=D1;second<=D2;end
 assign Q=SR?0:(C?first:second);
endmodule
module Coupling(input clock,cold_reset,hot_reset,delay_ready,input[11:0] payload,output[4:0] observed_data);
 wire raw,pad,forward,refclk,locked,raw_reset,pad_reset;
 native_gmac_pad_reset_clock #(.ENABLE_PAD_DOMAIN_RESET(1)) dut(clock,cold_reset,raw,pad,forward,refclk,locked);
 native_tx_word_reset_boundary boundary(raw,cold_reset|!locked|hot_reset|!delay_ready,raw_reset,pad_reset);
 reg[11:0] word;
 always @(posedge raw or posedge raw_reset) if(raw_reset)word<=0;else word<=payload;
 native_rgmii_trispeed_quarter #(.LOCAL_PAD_RESET_RELEASE(1),.REGISTER_SELECTED_HALF(1)) tx(
 .tx_clock(raw),.tx_pad_clock(pad),.tx_pad_reset(pad_reset),.tx_reset(raw_reset),
 .rgmii_tx_data(observed_data[3:0]),.rgmii_tx_control(observed_data[4]),
 .tx_rise(word[4:0]),.tx_fall(word[9:5]),.txc_rise(word[10]),.txc_fall(word[11]));
endmodule
'''
 (out/'contracts.sv').write_text(contracts)
 files='native_gmac_pad_reset_clock.sv native_tx_word_reset_boundary.sv native_gmac_divided_clock.sv control.sv contracts.sv serializer.sv'
 def run(top,negative=False):
  clock_steps=' '.join(f'-set-at {n} clock {n%2}' for n in range(1,41)) if top=='Coupling' else ''
  script=f'read_verilog -formal -sv {files}; prep -top {top}; flatten; clk2fflogic; opt_clean; sat -seq 40 -set-init-zero -prove-asserts -verify {clock_steps}'
  r=subprocess.run([str(a.yosys.resolve()),'-p',script],cwd=out,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=120)
  (out/(top+('-negative' if negative else '')+'.log')).write_text(r.stdout)
  return r.returncode==0 and 'SUCCESS!' in r.stdout,r.stdout
 results={}
 for top in ('Control','Topology','Coupling'):
  ok,log=run(top);assert ok,top;results[top]='PASS_40_STEPS'
 # Reachability starts from a real cold reset and reaches nonzero transmitted data.
 cover=f'read_verilog -formal -sv {files}; prep -top Coupling; flatten; clk2fflogic; opt_clean; sat -seq 40 -set-init-zero -set-at 1 cold_reset 1 -set-at 40 observed_data 31 -show observed_data -show cold_reset'
 r=subprocess.run([str(a.yosys.resolve()),'-p',cover],cwd=out,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=120)
 (out/'Coupling-cover.log').write_text(r.stdout)
 assert r.returncode==0 and 'model found' in r.stdout,'nonzero active pair unreachable'
 # Executable mutation checks reject early release and wrong raw/pad ratio.
 (out/'control.sv').write_text(control.replace('assert(phase_reset[1]','assert(phase_reset[0]'))
 ok,log=run('Control',True);assert not ok and 'proof did fail' in log
 (out/'control.sv').write_text(control)
 (out/sources[0].name).write_text(native.replace('.BUFGCE_DIVIDE(2)', '.BUFGCE_DIVIDE(4)'))
 ok,log=run('Topology',True);assert not ok and 'proof did fail' in log
 (out/sources[0].name).write_text(native)
 # Serializer preset is material to the first complete pair's phase.
 (out/'serializer.sv').write_text(serializer.replace("phase_high<=1'b1","phase_high<=1'b0"))
 ok,log=run('Coupling',True);assert not ok and 'proof did fail' in log
 (out/'serializer.sv').write_text(serializer)
 assert before=={str(x.relative_to(ROOT)):sha(x) for x in sources}
 receipt=dict(status='PASS_SOURCE_RTL_BOUNDED_FORMAL_UNDER_IDEAL_CLOCK_CONTRACTS',sourceSha256=before,yosysSha256=sha(a.yosys),steps=40,results=results,negativeEarlyRelease=True,negativeWrongRatio=True,negativeSerializerPreset=True,nonzeroAfterColdResetReachable=True,runnerSha256=sha(Path(__file__)),artifactSha256={x.name:sha(x) for x in sorted(out.iterdir()) if x.is_file()},
  assumptions=['Input clock models ideal PLL250 output; PLL500 frequency not simulated.','PLL lock arbitrary with reset forcing unlock; zero insertion delay/skew for both sibling branches.','Documented ideal divider clear and first-rising-edge behavior; no UNISIM/analog verification.','Control properties gated after sampled inhibit assertion; init zero SAT state.','Coupling selects LOCAL_PAD_RESET_RELEASE=1 and REGISTER_SELECTED_HALF=1; ON exporter requires the explicit t1-selected profile.',
  'Coupling uses alternating PAD half-cycle steps, arbitrary whole RAW words, and ideal ODDRE1 D1/D2 sampling; RX cone is excluded.',
  'First complete low/high pair and later pairs checked after two active PAD rising edges; partial startup/reset truncation is not protocol traffic.',
  'Hot reset/delay-ready only affect protocol reset boundary; rx_present intentionally unused.'],
  physicalTimingVerified=False,rxHoldFixed=False,t1PadPrimitiveProof=False,localRunAuthorized=False)
 (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
