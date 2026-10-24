`timescale 1ns/1ps
module a1_runtime_park_tb;
reg clock=0; always #5 clock=~clock;
reg reset=1;
reg command_valid=0, status_ready=0, done_valid=0, resume_valid=0, resumed_ready=0;
reg [7:0] command_epoch=1, done_epoch=1, resume_epoch=1;
reg fenceBusy=0, architecturalIdle=0, privateIdle=0, flushDone=0;
reg invalidate=0;
wire command_ready,status_valid,done_ready,resume_ready,resumed_valid,stop,stopped,flush,held;
wire [7:0] status_epoch,held_epoch,resumed_epoch;
CommonA1RuntimePark dut(.clock(clock),.reset(reset),
.io_command_valid(command_valid),.io_command_ready(command_ready),.io_command_bits_epoch(command_epoch),
.io_command_bits_invalidateInstructions(invalidate),.io_command_bits_invalidateTranslations(1'b0),
.io_status_valid(status_valid),.io_status_ready(status_ready),.io_status_bits_epoch(status_epoch),
.io_fabricDone_valid(done_valid),.io_fabricDone_ready(done_ready),.io_fabricDone_bits(done_epoch),
.io_resume_valid(resume_valid),.io_resume_ready(resume_ready),.io_resume_bits(resume_epoch),
.io_resumed_valid(resumed_valid),.io_resumed_ready(resumed_ready),.io_resumed_bits(resumed_epoch),
.io_fenceBusy(fenceBusy),.io_architecturalIdle(architecturalIdle),.io_privateIdle(privateIdle),.io_flushDone(flushDone),
.io_stopAdmission(stop),.io_stopped(stopped),.io_flush(flush),.io_held_valid(held),.io_held_bits(held_epoch));
task tick; begin @(posedge clock); #1; end endtask
task check(input bit condition,input [511:0] why); begin if(!condition) $fatal(1,"%0s",why); end endtask
initial begin
repeat(3)tick(); reset=0; tick();
if($test$plusargs("bad_invalidate")) invalidate=1;
fenceBusy=1; command_valid=1; tick(); command_valid=0;
check(stop&&!stopped,"consume queued command without freezing older FENCE");
architecturalIdle=1; repeat(3)begin tick(); check(!stopped&&!status_valid,"older FENCE still blocks park");end
architecturalIdle=0; fenceBusy=0; tick(); check(stop&&!stopped,"stop allocation before execution drain");
repeat(4)begin tick(); check(!stopped&&!flush&&!status_valid,"ROB/LSU busy cannot park");end
architecturalIdle=1; tick(); check(stopped&&flush&&!status_valid,"park before dirty flush ack");
flushDone=1; repeat(3)tick(); check(!status_valid&&!held,"private in-flight owner blocks proof");
privateIdle=1; tick(); check(status_valid&&status_epoch==1,"drain snapshot must be offered");
privateIdle=0; repeat(3)begin tick(); check(status_valid&&status_epoch==1&&!held,"late probe retains snapshot but revokes live held");end
status_ready=1; tick(); status_ready=0;
done_valid=1; done_epoch=2; tick(); check(!done_ready&&!held,"stale completion rejected");
done_epoch=1; tick(); done_valid=0; check(!held,"fabric receipt alone cannot hide late private owner");
resume_valid=1; resume_epoch=2; tick(); check(!resume_ready&&stop,"stale resume rejected");
resume_epoch=1; tick(); resume_valid=0; repeat(3)tick(); check(stop&&stopped&&!resumed_valid,"resume must wait actual private drain");
privateIdle=1; tick(); check(!stop&&!stopped&&!resumed_valid,"actual release precedes acknowledgement");
tick(); check(!resumed_valid,"one local edge insufficient"); tick();check(resumed_valid&&resumed_epoch==1,"two post-release edges acknowledged");
repeat(3)begin tick();check(resumed_valid&&!command_ready,"terminal backpressure blocks reuse");end
resumed_ready=1;tick();resumed_ready=0;check(!command_ready,"duplicate epoch rejected");
command_epoch=2;tick();check(command_ready,"fresh epoch admitted after terminal");
$display("A1_RUNTIME_PARK_PASS: ordered drain, late probe, stale epoch, resume backpressure");$finish;
end
initial begin #10000;$fatal(1,"timeout");end
endmodule
