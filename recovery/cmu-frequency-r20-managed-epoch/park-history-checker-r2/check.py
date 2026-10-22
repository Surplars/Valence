from pathlib import Path
import importlib.util,json,hashlib
root=Path.cwd();out=root/'out/cmu-frequency-r20/park-history-checker-r2';runner=root/'simulator/gsim/common/managed_control_epoch_native.py';tb=root/'simulator/gsim/common/managed_control_epoch_tb.sv'
spec=importlib.util.spec_from_file_location('managed',runner);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
text=tb.read_text();start=text.index('  reg controlRawHeldSeen=');end=text.index('  rtl8211f_pin_model phy',start);history=text[start:end]
start=text.index('      if(!cancelBeforeHeldSeen || proofPauseSeen!=0)');end=text.index('      // Cancellation requires no held+idle qualification.',start);final=text[start:end]
unit='''`timescale 1ns/1ps
module park_history_checker;
reg fabricClock=0,reset=1,bootstrapPark=0,controlParkRequest=0;
reg fabricHeld_valid=0,fabricIdle=0,controlEpochBusy=1;
reg [7:0] controlQualifiedEpoch=1,fabricHeld_bits=1;
integer proofPauseSeen=0,scenario=0;
always #5 fabricClock=~fabricClock;
'''+history+'''
task step;begin @(posedge fabricClock);#1;@(negedge fabricClock);end endtask
initial begin
 if($value$plusargs("scenario=%d",scenario))begin end
 step();reset=0;cancelBeforeHeldSeen=1;
 case(scenario)
 0:begin // Real raw held without all-idle does not obligate a park on cancel.
   fabricHeld_valid=1;fabricIdle=0;step();fabricHeld_valid=0;step();
   if(controlAnyRawHeldSamples!=1||controlRawHeldSamples!=0)$fatal(1,"UNIT_ZERO_PARK_SETUP");
 end
 1:begin // A genuine prior matching held+idle sample authorizes later park.
   fabricHeld_valid=1;fabricIdle=1;step();fabricHeld_valid=0;fabricIdle=0;
   controlParkRequest=1;step();controlParkRequest=0;step();
   if(!controlRawHeldSeen||controlRawHeldSamples!=1)$fatal(1,"UNIT_LEGAL_PARK_SETUP");
 end
 2:begin controlParkRequest=1;step();end
 3:begin fabricHeld_valid=1;fabricIdle=1;controlParkRequest=1;step();end
 4:begin fabricHeld_valid=1;fabricIdle=1;step();fabricHeld_valid=0;
   controlQualifiedEpoch=2;controlParkRequest=1;step();end
 endcase
'''+final+'''
 $display("PARK_HISTORY_CHECKER_PASS scenario=%0d raw=%0d qualified=%0d",scenario,controlAnyRawHeldSamples,controlRawHeldSamples);
 $finish;
end
initial begin #1000;$fatal(1,"UNIT_TIMEOUT");end
endmodule
'''
(out/'checker.sv').write_text(unit)
record=dict(status='RUNNING',cases=[],source_sha256={str(p.relative_to(root)):m.base.sha(p) for p in (runner,tb)},extraction_sha256={'history':hashlib.sha256(history.encode()).hexdigest(),'cancel_final_assertion':hashlib.sha256(final.encode()).hexdigest()},scope='exact extracted testbench checker logic only; no DUT/native epoch coverage',tools=m.base.tool_hashes({'iverilog':Path('/workspace/scratch/41e4a649bb60/native-tools/bin/iverilog'),'vvp':Path('/workspace/scratch/41e4a649bb60/native-tools/root/usr/bin/vvp')}),checks=[])
try:
 rc,log=m.run(['/workspace/scratch/41e4a649bb60/native-tools/bin/iverilog','-g2012','-s','park_history_checker','-o',out/'checker.vvp',out/'checker.sv'],out,'compile',10,record);assert rc==0,log
 for i in range(5):
  rc,log=m.run(['/workspace/scratch/41e4a649bb60/native-tools/root/usr/bin/vvp','-i',out/'checker.vvp',f'+scenario={i}'],out,f'case-{i}',10,record)
  if i<2:assert rc==0 and 'PARK_HISTORY_CHECKER_PASS' in log,log
  else:assert rc!=0 and 'MANAGED_CONTROL_PARK_WITHOUT_PRIOR_MATCHED_RAW_HELD' in log and 'PARK_HISTORY_CHECKER_PASS' not in log,log
  record['checks'].append({'scenario':i,'result':'PASS' if i<2 else 'PASS_EXPECTED_REJECTION','lines':log.splitlines()})
 assert all(m.base.sha(root/n)==h for n,h in record['source_sha256'].items())
 assert all(m.base.sha(Path(t['path']))==t['sha256'] for t in record['tools'].values())
 record['status']='PASS_EXTRACTED_CHECKER_UNIT'
finally:
 record['artifacts_sha256']={p.name:m.base.sha(p) for p in out.iterdir() if p.is_file() and p.name!='receipt.json'}
 (out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
 print(record['status']);print(json.dumps(record['checks'],indent=2))
