"""Create a deterministic native testbench for the actual shared-quiesce fixture."""
import argparse
import hashlib
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('emission', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
assert not a.output.exists()
assert (a.emission/'SharedQuiesceFixture.sv').is_file()
a.output.mkdir(parents=True)
bench = r'''
`timescale 1ps/1ps
module shared_quiesce_tb;
logic rawClock=0, managedClock=0, commonReset=1;
logic quiesce=0, isolate=0, active=0, gateEnable=1;
logic [7:0] payload=0;
wire [7:0] delayed;
wire wake,empty,ack,sharedQuiesce,managedRequest;
SharedQuiesceFixture dut(.*);
always #4000 rawClock=~rawClock;
// Testbench clock source, enabled only on the low phase. The DUT uses a clock
// input here; this is not a synthesized clk&CE gate or replacement CDC model.
always @(posedge rawClock) if(gateEnable) managedClock=1;
always @(negedge rawClock) managedClock=0;
integer i, observed=0, rawEdges=0, managedEdges=0;
logic [7:0] expected[0:63];
initial for(i=0;i<64;i=i+1) expected[i]=0;
always @(posedge managedClock) managedEdges=managedEdges+1;
always @(posedge rawClock) begin
 rawEdges=rawEdges+1;
 if(commonReset) for(i=0;i<64;i=i+1) expected[i]=0;
 else begin
  for(i=63;i>0;i=i-1) expected[i]=expected[i-1];
  expected[0]=payload;
 end
 #1;
 if(delayed!==expected[63]) $fatal(1,"FIXED_PAYLOAD_LATENCY_OR_DATA");
 if(expected[63]==8'ha5) begin
  if($test$plusargs("BAD_ORACLE")) $fatal(1,"ORACLE_NEGATIVE_REJECT");
  observed=observed+1;
 end
end
integer frozenManaged;
initial begin
 #40000;commonReset=0;
 repeat(12) @(negedge rawClock);
 if(ack!==0 || wake!==0 || empty!==1) $fatal(1,"RESET_RELEASE_NOT_IDLE");
 #719;quiesce=1;
 wait(sharedQuiesce && managedRequest && ack);
 @(negedge rawClock);gateEnable=0;
 frozenManaged=managedEdges;
 repeat(4) @(negedge rawClock);
 if(ack!==1 || managedEdges!=frozenManaged) $fatal(1,"STOPPED_ACK_OR_CLOCK");
 active=1;payload=8'ha5;
 @(negedge rawClock);active=0;payload=0;
 repeat(4) @(negedge rawClock);
 if(wake!==1 || ack!==1 || empty!==0) $fatal(1,"RAW_WAKE_WHILE_MANAGED_STOPPED");
 #719;quiesce=0;
 wait(!sharedQuiesce);
 repeat(6) @(negedge rawClock);
 if(ack!==1 || managedRequest!==1 || managedEdges!=frozenManaged) $fatal(1,"ACK_CLEARED_WITHOUT_REAL_MANAGED_EDGES");
 gateEnable=1;
 @(posedge managedClock);#1;
 if(managedRequest!==1) $fatal(1,"LOCAL_PROGRESS_STAGE_ONE");
 @(posedge managedClock);#1;
 if(managedRequest!==0) $fatal(1,"LOCAL_PROGRESS_STAGE_TWO");
 @(posedge managedClock);#1;
 if(ack!==0) $fatal(1,"ACK_NOT_RELEASED_AFTER_PROGRESS");
 wait(observed==1 && empty && !wake);
 @(negedge rawClock);#719;quiesce=1;
 wait(ack && sharedQuiesce && managedRequest);
 @(negedge rawClock);gateEnable=0;
 repeat(4) @(negedge rawClock);
 if(ack!==1) $fatal(1,"SECOND_STOP_FAILED");
 #719;commonReset=1;#2;
 if(ack!==0 || wake!==0 || sharedQuiesce!==0) $fatal(1,"COLD_RESET_WHILE_MANAGED_STOPPED");
 $display("SHARED_QUIESCE_CYCLE_PASS payloads=%0d raw_edges=%0d managed_edges=%0d",observed,rawEdges,managedEdges);
 $finish;
end
initial begin #10000000;$fatal(1,"SHARED_QUIESCE_TIMEOUT");end
endmodule
'''
(a.output/'shared_quiesce_tb.sv').write_text(bench)
sources = sorted(a.emission.glob('*.sv'))
(a.output/'sources.f').write_text(''.join('"'+str(f.resolve()).replace('\\', '/')+'"\n' for f in sources)+'shared_quiesce_tb.sv\n')
(a.output/'run.tcl').write_text('run all\nquit\n')
(a.output/'inputs.json').write_text(json.dumps({f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in sources},indent=2)+'\n')
print('Prepared actual-component shared-quiesce cycle fixture, no DUT modifications')
