"""Focused actual355 decoder/reset/admission equivalence under ideal paired capture."""
import argparse,hashlib,json,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('native','yosys','sv2v','output'):p.add_argument('--'+n,type=Path,required=True)
 p.add_argument('--allow-stalls',action='store_true');p.add_argument('--stop-all-phases',action='store_true');p.add_argument('--offsets',default='-3,-2,-1,0,1,2,3');a=p.parse_args()
 out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 inv=json.loads((a.native/'rtl-inventory.json').read_text());entry=json.loads((a.native/'native-entry.json').read_text())
 assert entry['rtlInventorySha256']==sha(a.native/'rtl-inventory.json')
 names=['TriSpeedRgmiiRx.sv','CdcResetRelease.sv','CdcLevel.sv','TriSpeedManagedGmac.sv','EthernetPhysicalIngress.sv','EthernetIngressPacker.sv'];bound={}
 for name in names:
  f=a.native/name;assert sha(f)==inv['files'][name]['sha256'] and f.stat().st_size==inv['files'][name]['bytes'];bound[name]=sha(f)
  (out/name).write_bytes(f.read_bytes())
 pair=HERE/'native_rx_falling_pair.sv';(out/pair.name).write_bytes(pair.read_bytes());bound[pair.name]=sha(pair)
 converted=subprocess.run([str(a.sv2v.resolve())]+names[:3],cwd=out,check=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 (out/'actual.v').write_text(converted.stdout);(out/'sv2v.log').write_text(converted.stderr)
 harness='''module DecoderCheck #(parameter OFFSET=0)(input inhibit,media_open,rate_valid,input[1:0]rate_bits,input[9:0] payload,input advance,output reg observed_valid=0,output reg observed_restart=0);
 reg[2:0] phase=4;
 always @($global_clock)if(advance)phase<=phase+1;
 wire capture_clock=phase<4;
 wire[2:0] fabric_phase=phase-OFFSET;
 wire fabric_clock=fabric_phase<4;
 reg seen_reset=0,seen_stop=0;
 always @($global_clock)if(observed_valid && !advance)seen_stop<=1;
 always @($global_clock)if(inhibit)seen_reset<=1;
 wire fabric_reset,capture_reset,raw_open;
 CdcResetRelease rawRxRelease(fabric_clock,inhibit,fabric_reset);
 CdcResetRelease captureRelease(capture_clock,inhibit,capture_reset);
 CdcLevel rawRxOpen(fabric_clock,fabric_reset,media_open,raw_open);
 // Ideal external paired-symbol token is stable across both related rising edges.
 // The token changes only at capture falling, midway between corresponding rises.
 reg[9:0] token;
 always @(negedge capture_clock or posedge inhibit)if(inhibit)token<=0;else token<=payload;
 reg[9:0] old_q,new_q;
 always @(posedge fabric_clock or posedge fabric_reset)if(fabric_reset)old_q<=0;else old_q<=token;
 always @(posedge capture_clock or posedge capture_reset)if(capture_reset)new_q<=0;else new_q<=token;
 wire[9:0] retimed;
 native_rx_falling_pair #(.ENABLE_FALLING_PAIR(1)) pair(capture_clock,capture_reset,new_q[4:0],new_q[9:5],retimed[4:0],retimed[9:5]);
 wire old_ready,new_ready,old_step,new_step,old_valid,new_valid,old_error,new_error,old_odd,new_odd;
 wire[7:0]old_data,new_data;
 TriSpeedRgmiiRx baseline(fabric_clock,fabric_reset,old_ready,rate_valid,rate_bits,!raw_open,!raw_open,old_q[4:0],old_q[9:5],old_step,old_data,old_valid,old_error,old_odd);
 TriSpeedRgmiiRx candidate(fabric_clock,fabric_reset,new_ready,rate_valid,rate_bits,!raw_open,!raw_open,retimed[4:0],retimed[9:5],new_step,new_data,new_valid,new_error,new_odd);
 always @(posedge fabric_clock)if(seen_reset && !fabric_reset)begin
   assert(old_ready==new_ready);
   if(raw_open)assert(old_q[4]==retimed[4]);
   assert(old_valid==new_valid);
   assert(old_step==new_step);
   assert(old_odd==new_odd);
   if(old_valid)begin assert(old_data==new_data);assert(old_error==new_error);observed_valid<=1;if(seen_stop)observed_restart<=1;end
   if(!raw_open)begin assert(!old_valid);assert(!new_valid);end
 end
endmodule
'''
 (out/'harness.sv').write_text(harness)
 results={}
 steps=96 if a.stop_all_phases else 80
 def run(off,phase=None,label='',cover=False):
  clock_constraint='' if a.allow_stalls else '-set advance 1'
  if phase is not None:
   clock_constraint+=' '+' '.join(f'-set-at {n} advance 0' for n in range(64+phase,72+phase))
  proof=f'-set-at 1 inhibit 1 -set-at {steps} observed_restart 1' if cover else '-prove-asserts -verify'
  script=f'read_verilog -formal -sv actual.v {pair.name} harness.sv; chparam -set OFFSET {off%8} DecoderCheck; prep -top DecoderCheck; flatten; clk2fflogic; opt_clean; sat -seq {steps} {clock_constraint} {proof}'
  filename=f'offset{off}-stop{phase}'+label+'.log'
  try:r=subprocess.run([str(a.yosys.resolve()),'-p',script],cwd=out,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180)
  except subprocess.TimeoutExpired as e:
   (out/filename).write_bytes(e.stdout or b'');(out/'INCOMPLETE.json').write_text(json.dumps(dict(status='TIMEOUT',case=filename,seconds=180)))
   raise
  (out/filename).write_text(r.stdout)
  return r.returncode==0 and ('model found' if cover else 'SUCCESS!') in r.stdout,r.stdout
 for off in map(int,a.offsets.split(',')):
  assert -4<off<4
  for phase in (range(8) if a.stop_all_phases else [None]):
   ok,log=run(off,phase);assert ok,(off,phase);results[f'{off}:{phase}']=f'PASS_{steps}_STEPS'
 if a.stop_all_phases:
  ok,log=run(0,0,'-cover',True);assert ok,'accepted-byte restart cover'
  native=pair.read_text()
  for name,bad in {'dropped_pair':native.replace('else pair<=','else if(input_rise[4]) pair<='),'swapped_control':native.replace('{input_fall,input_rise}','{input_rise[4],input_fall[3:0],input_fall[4],input_rise[3:0]}')}.items():
   (out/pair.name).write_text(bad);ok,log=run(0,0,'-'+name);assert not ok and 'proof did fail' in log,name
  (out/pair.name).write_text(native)
 receipt=dict(status='PASS_FOCUSED_ACTUAL_DECODER_EQUIVALENCE_UNDER_IDEAL_CAPTURE_CONTRACT',nativeInputSha256=bound,nativeInventorySha256=sha(a.native/'rtl-inventory.json'),runnerSha256=sha(Path(__file__)),yosysSha256=sha(a.yosys),sv2vSha256=sha(a.sv2v),results=results,stopEveryPhase=a.stop_all_phases,acceptedByteRestartReachable=a.stop_all_phases,negativePairMutations=a.stop_all_phases,artifacts={x.name:sha(x) for x in out.iterdir()},physicalTimingVerified=False,
 assumptions=['Actual emitted355 CdcResetRelease,CdcLevel,TriSpeedRgmiiRx; unchanged PhysicalIngress/packer integration bound for composition.', 'Paired IDDRE1 output and external token stability are contracts, not vendor serial sampling simulation.', 'Initial datapath state unconstrained; assertions qualify after inhibit; media-open and rate commands arbitrary.', 'Fixed related-clock phase order; arbitrary stalls enabled='+str(a.allow_stalls)+'. No arbitrary rate-transition clock waveform proof.', 'PHY/IDELAY readiness loss distinct from common reset remains outside this harness.'])
 (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
