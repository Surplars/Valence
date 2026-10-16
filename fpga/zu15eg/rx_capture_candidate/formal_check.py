"""Actual pair RTL under explicit paired-IDDRE1 and related-clock event contracts."""
import argparse,hashlib,json,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--yosys',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 source=HERE/'native_rx_falling_pair.sv';native=source.read_text();before=sha(source)
 bindings=[source,ROOT/'fpga/next/soc_top_fpga_next_ddr.sv',HERE/'export_board.py',ROOT/'fpga/zu15eg/native_rgmii_trispeed_quarter.sv']
 source_hashes={x.relative_to(ROOT).as_posix():sha(x) for x in bindings}
 (out/source.name).write_text(native)
 board=(ROOT/'fpga/next/soc_top_fpga_next_ddr.sv').read_text()
 reset=board[board.index('    (* ASYNC_REG="TRUE" *) reg [2:0] rx_reset_pipe;'):board.index('    wire tx_reset_raw, tx_reset_pad;')]
 reset=reset.replace('posedge clk_rx','posedge capture_clock').replace('soc_reset | ~delay_ready','inhibit')
 harness='''module Check #(parameter OFFSET=0)(input inhibit,advance,input[9:0] payload,output[9:0] observed,output reg observed_restart=0);
 reg seen_reset=0,seen_active=0,seen_stop=0;
 always @($global_clock)begin
  if(inhibit)seen_reset<=1;
  if(seen_reset && observed!=0)seen_active<=1;
  if(seen_active && !advance)seen_stop<=1;
  if(seen_stop && advance && observed!=0)observed_restart<=1;
 end
 reg[2:0] phase=4;
 always @($global_clock)if(advance)phase<=phase+1;
 wire capture_clock=phase<4;
 wire[2:0] fabric_phase=phase-OFFSET;
 wire fabric_clock=fabric_phase<4;
'''+reset+'''
 wire reset=rx_reset_pipe[2];
 // SAME_EDGE_PIPELINED contract: complete10-bit Q pair changes after rising C.
 // Serial sample construction and primitive analog timing are outside this proof.
 reg[9:0] iddr_pair;
 always @(posedge capture_clock or posedge reset)
  if(reset)iddr_pair<=0;else iddr_pair<=payload;
 wire[9:0] retimed;
 native_rx_falling_pair #(.ENABLE_FALLING_PAIR(1)) dut(capture_clock,reset,
  iddr_pair[4:0],iddr_pair[9:5],retimed[4:0],retimed[9:5]);
 // Original same-clock decoder consumes prior complete Q pair on rising k+1.
 reg[9:0] baseline_view,candidate_view;
 always @(posedge capture_clock or posedge reset)
  if(reset)baseline_view<=0;else baseline_view<=iddr_pair;
 always @(posedge fabric_clock or posedge reset)
  if(reset)candidate_view<=0;else candidate_view<=retimed;
 assign observed=candidate_view;
 always @(negedge fabric_clock) if(seen_reset && !reset) assert(candidate_view==baseline_view);
 always @* if(seen_reset && reset) assert(retimed==0);
endmodule
'''
 (out/'harness.sv').write_text(harness)
 def run(offset,negative=None,cover=False):
  sat='-set-at 1 inhibit 1 -set-at 48 observed 1023 -set-at 48 observed_restart 1 -show observed' if cover else '-prove-asserts -verify'
  script=f'read_verilog -formal -sv {source.name} harness.sv; chparam -set OFFSET {offset%8} Check; prep -top Check; flatten; clk2fflogic; opt_clean; sat -seq 48 {sat}'
  r=subprocess.run([str(a.yosys.resolve()),'-p',script],cwd=out,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=120)
  name=f'offset{offset}'+('-'+negative if negative else '')+('-cover' if cover else '')+'.log';(out/name).write_text(r.stdout)
  return r.returncode==0 and ('model found' if cover else 'SUCCESS!') in r.stdout,r.stdout
 results={}
 for offset in (-3,-2,-1,0,1,2,3):
  ok,log=run(offset);assert ok,offset;results[str(offset)]='PASS_48_STEPS'
 ok,log=run(1,cover=True);assert ok,'nonzero post-reset reachability'
 mutations={
  'dropped_pair':native.replace('else pair<=','else if(input_rise[4]) pair<='),
  'swapped_control':native.replace('{input_fall,input_rise}', '{input_rise[4],input_fall[3:0],input_fall[4],input_rise[3:0]}'),
  'reset_not_zero':native.replace("pair<=10'b0", "pair<=10'b1")}
 for name,bad in mutations.items():
  assert bad!=native; (out/source.name).write_text(bad);ok,log=run(1,name)
  assert not ok and 'proof did fail' in log,name
 (out/source.name).write_text(native)
 assert source_hashes=={x.relative_to(ROOT).as_posix():sha(x) for x in bindings}
 receipt=dict(status='PASS_BOUNDED_PAIR_CYCLE_EQUIVALENCE_UNDER_RELATED_CLOCK_CONTRACT',
  sources=source_hashes,
  runnerSha256=sha(Path(__file__)),yosysSha256=sha(a.yosys),steps=48,results=results,negativeMutations=list(mutations),nonzeroAfterResetReachable=True,activeStopRestartReachable=True,initialDatapathStateUnconstrained=True,
  artifacts={x.name:sha(x) for x in sorted(out.iterdir())},
  assumptions=['Datapath/reset registers initially unconstrained; assertions qualify after sampled real inhibit; event phase and proof bookkeeping initialize explicitly.',
   'Fixed related-clock event schedule with arbitrary stalls; no arbitrary rate-transition edge waveform proof.',
   'IDDRE1 SAME_EDGE_PIPELINED pair abstraction changes all10 bits after capture rising; serial sampling is not modeled.',
   'Capture/fabric clocks share period/duty, with fabric offset -3,-2,-1,0,1,2,3 of8 ideal phase steps (absolute skew below half-cycle); no jitter or analog insertion.',
   'Arbitrary advance can stop clocks at any modeled phase; inhibit arbitrary, release via actual3FF capture-clock reset block.',
   'Compared observable decoder inputs, not actual decoder state or full protocol-reset domain.',
   'No additional intended decoder cycle under the stated event order; physical setup/hold must establish that order and margins.'],
  vendorPrimitiveSimulation=False,physicalTimingVerified=False,allRateCornerMatrixAvailable=False)
 (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
