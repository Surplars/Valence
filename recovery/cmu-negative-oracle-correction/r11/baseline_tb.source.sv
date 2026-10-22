`timescale 1ns/1ps
module clock_rate_cleanup_tb;
 reg clock=0; always #5 clock=~clock;
 reg reset=1;
 reg [1:0] submit_valid=0,responseCommitted=0;
 reg [31:0] clearErrors[0:1];
 reg [3:0] drainAcks[0:1];
 reg [1:0] gateClosed=0,gateOpen=3,locked=3,resumed=3;
 wire [1:0] clockEnable,quiesce,isolate,program_valid,busy,lastSuccess;
 wire [3:0] state[0:1]; wire [31:0] completed[0:1],errors[0:1],requestError[0:1],program_hz[0:1],program_token[0:1];
 reg [1:0] program_ready=3,program_result_valid=0;
 reg [31:0] program_result_token[0:1];
 wire [1:0] requests_valid,resume_valid,cancel_valid,result_ready;
 wire [31:0] requests_bits[0:1];
 reg [1:0] requests_ready=0,resume_ready=0,held_valid=0,result_valid=0,result_canceled=0,result_timedOut=0;
 reg [31:0] held_token[0:1],result_token[0:1];
 reg [7:0] held_epoch[0:1],result_epoch[0:1];
 reg boundaryBusy=0,activeLane=0,drainDeadline=0,timeoutSelected=0,cleanupFault=0;
 reg [7:0] activeEpoch=0; reg [31:0] activeToken=0;
 reg monitorNoGate=0,wrongCompletion=0,wrongQuiesce=0;
 integer i,cycles=0,normalCase; reg [31:0] token0,token1;
 ClockRateCleanupComponent dut(.clock(clock),.reset(reset),
 .io_submit_0_valid(submit_valid[0]),
 .io_submit_0_bits(32'd100000000),
 .io_responseCommitted_0(responseCommitted[0]),
 .io_clearErrors_0(clearErrors[0]),
 .io_requestError_0(requestError[0]),
 .io_state_0(state[0]),
 .io_busy_0(busy[0]),
 .io_errors_0(errors[0]),
 .io_completed_0(completed[0]),
 .io_lastSuccess_0(lastSuccess[0]),
 .io_endpoint_0_present(1'b1),
 .io_endpoint_0_drainAcks(drainAcks[0]),
 .io_endpoint_0_gateClosed(gateClosed[0]),
 .io_endpoint_0_gateOpen(gateOpen[0]),
 .io_endpoint_0_locked(locked[0]),
 .io_endpoint_0_resumed(resumed[0]),
 .io_endpoint_0_clockEnable(clockEnable[0]),
 .io_endpoint_0_quiesce(quiesce[0]),
 .io_endpoint_0_isolate(isolate[0]),
 .io_endpoint_0_program_valid(program_valid[0]),
 .io_endpoint_0_program_ready(program_ready[0]),
 .io_endpoint_0_program_bits_hz(program_hz[0]),
 .io_endpoint_0_program_bits_token(program_token[0]),
 .io_endpoint_0_result_valid(program_result_valid[0]),
 .io_endpoint_0_result_bits_hz(32'd100000000),
 .io_endpoint_0_result_bits_token(program_result_token[0]),
 .io_endpoint_0_result_bits_error(1'b0),
 .io_requests_0_valid(requests_valid[0]),
 .io_requests_0_bits(requests_bits[0]),
 .io_requests_0_ready(requests_ready[0]),
 .io_resume_0_valid(resume_valid[0]),
 .io_resume_0_ready(resume_ready[0]),
 .io_cancel_0_valid(cancel_valid[0]),
 .io_cancel_0_ready(1'b0),
 .io_held_0_valid(held_valid[0]),
 .io_held_0_bits_token(held_token[0]),
 .io_held_0_bits_epoch(held_epoch[0]),
 .io_result_0_valid(result_valid[0]),
 .io_result_0_ready(result_ready[0]),
 .io_result_0_bits_token(result_token[0]),
 .io_result_0_bits_epoch(result_epoch[0]),
 .io_result_0_bits_canceled(result_canceled[0]),
 .io_result_0_bits_timedOut(result_timedOut[0]),
 .io_submit_1_valid(submit_valid[1]),
 .io_submit_1_bits(32'd100000000),
 .io_responseCommitted_1(responseCommitted[1]),
 .io_clearErrors_1(clearErrors[1]),
 .io_requestError_1(requestError[1]),
 .io_state_1(state[1]),
 .io_busy_1(busy[1]),
 .io_errors_1(errors[1]),
 .io_completed_1(completed[1]),
 .io_lastSuccess_1(lastSuccess[1]),
 .io_endpoint_1_present(1'b1),
 .io_endpoint_1_drainAcks(drainAcks[1]),
 .io_endpoint_1_gateClosed(gateClosed[1]),
 .io_endpoint_1_gateOpen(gateOpen[1]),
 .io_endpoint_1_locked(locked[1]),
 .io_endpoint_1_resumed(resumed[1]),
 .io_endpoint_1_clockEnable(clockEnable[1]),
 .io_endpoint_1_quiesce(quiesce[1]),
 .io_endpoint_1_isolate(isolate[1]),
 .io_endpoint_1_program_valid(program_valid[1]),
 .io_endpoint_1_program_ready(program_ready[1]),
 .io_endpoint_1_program_bits_hz(program_hz[1]),
 .io_endpoint_1_program_bits_token(program_token[1]),
 .io_endpoint_1_result_valid(program_result_valid[1]),
 .io_endpoint_1_result_bits_hz(32'd100000000),
 .io_endpoint_1_result_bits_token(program_result_token[1]),
 .io_endpoint_1_result_bits_error(1'b0),
 .io_requests_1_valid(requests_valid[1]),
 .io_requests_1_bits(requests_bits[1]),
 .io_requests_1_ready(requests_ready[1]),
 .io_resume_1_valid(resume_valid[1]),
 .io_resume_1_ready(resume_ready[1]),
 .io_cancel_1_valid(cancel_valid[1]),
 .io_cancel_1_ready(1'b0),
 .io_held_1_valid(held_valid[1]),
 .io_held_1_bits_token(held_token[1]),
 .io_held_1_bits_epoch(held_epoch[1]),
 .io_result_1_valid(result_valid[1]),
 .io_result_1_ready(result_ready[1]),
 .io_result_1_bits_token(result_token[1]),
 .io_result_1_bits_epoch(result_epoch[1]),
 .io_result_1_bits_canceled(result_canceled[1]),
 .io_result_1_bits_timedOut(result_timedOut[1]),
 .io_boundaryBusy(boundaryBusy),
 .io_activeLane(activeLane),
 .io_activeEpoch(activeEpoch),
 .io_activeToken(activeToken),
 .io_drainDeadline(drainDeadline),
 .io_timeoutSelected(timeoutSelected),
 .io_cleanupFault(cleanupFault));

 task tick; begin @(posedge clock); #1; end endtask
 task step(input integer n); integer j; begin for(j=0;j<n;j=j+1) tick(); end endtask
 task idle_boot; begin
   reset=1; monitorNoGate=0; step(4); @(negedge clock); reset=0;
   while(busy) tick();
 end endtask
 task check_pending(input integer lane,input integer count); begin
   if(completed[lane]!==count || !busy[lane] || !clockEnable[lane] || !quiesce[lane])
     $fatal(1,"controller prematurely completed/released cleanup");
   if(wrongCompletion && completed[lane]!==count+1) $fatal(1,"NEGATIVE_ORACLE_REJECTED wrong completion ledger");
   if(wrongQuiesce && quiesce[lane]!==0) $fatal(1,"NEGATIVE_ORACLE_REJECTED wrong release oracle");
 end endtask
 task terminal(input integer lane,input reg canceled); begin
   @(negedge clock); result_token[lane]=activeToken; result_epoch[lane]=activeEpoch;
   result_canceled[lane]=canceled; result_timedOut[lane]=canceled; result_valid[lane]=1; #1;
   while(!result_ready[lane]) begin @(negedge clock); #1; end
   tick(); @(negedge clock); result_valid[lane]=0;
 end endtask
 task retire; begin
   @(negedge clock); boundaryBusy=0; held_valid=0; drainDeadline=0; timeoutSelected=0;
   step(3);
 end endtask
 always @(posedge clock) begin
   cycles=cycles+1;
   if(cycles>3000) $fatal(1,"component watchdog state=%0d/%0d busy=%b result=%b ready=%b",state[0],state[1],busy,result_valid,result_ready);
   if(!reset && monitorNoGate && (program_valid!=0 || clockEnable!=3))
     $fatal(1,"timeout path attempted physical clock transition");
   if(!reset && cancel_valid!=0) $fatal(1,"adapter injected cancellation instead of real boundary timeout");
 end
 initial begin
   wrongCompletion=$test$plusargs("wrong-completion"); wrongQuiesce=$test$plusargs("wrong-quiesce");
   for(i=0;i<2;i=i+1) begin clearErrors[i]=0;drainAcks[i]=0;held_token[i]=0;held_epoch[i]=0;result_token[i]=0;result_epoch[i]=0;program_result_token[i]=0; end
   idle_boot(); $display("BOOT"); monitorNoGate=1;
   @(negedge clock); submit_valid=3; tick(); @(negedge clock); submit_valid=0;
   if(state[0]!=1 || state[1]!=1) $fatal(1,"two accepted submissions missing reply owner");
   responseCommitted=3; tick(); @(negedge clock); responseCommitted=0;
   if(requests_valid!=3) $fatal(1,"both controllers not queued");
   token0=requests_bits[0];token1=requests_bits[1]; requests_ready=1; tick();
   @(negedge clock);requests_ready=0;boundaryBusy=1;activeLane=0;activeEpoch=1;activeToken=token0;
   step(70); check_pending(0,0);check_pending(1,0);
   if(requests_valid!=0 || errors[0]!=0 || errors[1]!=0) $fatal(1,"queued timer or shared ownership leak");
   @(negedge clock);held_valid=1;held_token[0]=token0;held_epoch[0]=1;drainAcks[0]=15;
   step(2); @(negedge clock);drainDeadline=1; tick();
   if(state[0]!=9 || !errors[0][4] || !clockEnable[0]) $fatal(1,"deadline lost to simultaneous qualified proof");
   @(negedge clock);drainDeadline=0;timeoutSelected=1;drainAcks[0]=0;
   step(5);check_pending(0,0);
   // Wrong transaction and ancient epoch cannot consume a terminal.
   @(negedge clock);result_valid=1;result_token[0]=token0+1;result_epoch[0]=1;result_canceled=1;result_timedOut=1;
   step(3);if(result_ready[0]) $fatal(1,"wrong token accepted");
   @(negedge clock);result_token[0]=token0;result_epoch[0]=0;
   step(3);if(result_ready[0]) $fatal(1,"wrong epoch accepted");
   @(negedge clock);result_valid=0;
    $display("FIRST_TERMINAL"); terminal(0,1);step(50);check_pending(0,0);
   if(requests_valid!=0) $fatal(1,"queued contender accepted before retirement");
   @(negedge clock);locked[0]=0;gateOpen[0]=0;
   retire();step(20);check_pending(0,0);
   if(requests_valid!=0) $fatal(1,"adapter released shared rate owner while clock safety missing");
   @(negedge clock);locked[0]=1;step(20);check_pending(0,0);
   if(requests_valid!=0) $fatal(1,"gate-open proof omitted from retirement");
   @(negedge clock);gateOpen[0]=1;step(3);
   if(completed[0]!=1 || busy[0] || lastSuccess[0]) $fatal(1,"failed cleanup missing exact completion");
   if(!requests_valid[1]) $fatal(1,"second controller lost queued request");
   @(negedge clock);requests_ready=2;tick();
   @(negedge clock);requests_ready=0;boundaryBusy=1;activeLane=1;activeEpoch=2;activeToken=token1;
   step(4);@(negedge clock);timeoutSelected=1;cleanupFault=1;
   step(90);check_pending(1,0);
   if(!errors[1][9] || !errors[1][4]) $fatal(1,"cleanup fault failed to remain reported");
    $display("SECOND_TERMINAL"); terminal(1,1);step(20);check_pending(1,0);retire();
   if(completed[1]!=1 || busy[1] || lastSuccess[1]) $fatal(1,"second cleanup retired incorrectly");
   // Reset is the only way to clear the boundary's sticky cleanup-fault condition.
   @(negedge clock);cleanupFault=0;idle_boot();
   if(completed[0]!=0 || completed[1]!=0) $fatal(1,"reset did not clear controller ledger");
   // Model-only normal branch regression: synthetic ACKs/program response are
   // NOT real clock permission. Ensure retiring does not reassert quiesce.
   for(normalCase=0;normalCase<3;normalCase=normalCase+1) begin
   @(negedge clock);cleanupFault=0;locked=3;gateOpen=3;idle_boot();
   monitorNoGate=0;
   @(negedge clock);submit_valid=1;tick();@(negedge clock);submit_valid=0;responseCommitted=1;
   tick();@(negedge clock);responseCommitted=0;requests_ready=1;token0=requests_bits[0];tick();
   @(negedge clock);requests_ready=0;boundaryBusy=1;activeLane=0;activeEpoch=1;activeToken=token0;
   step(3);@(negedge clock);held_valid=1;held_token[0]=token0;held_epoch[0]=1;drainAcks[0]=15;
   while(state[0]!=3) tick();
   @(negedge clock);gateClosed[0]=1;gateOpen[0]=0;tick();
   while(!program_valid[0]) tick();
   program_result_token[0]=program_token[0];tick();
   @(negedge clock);program_result_valid[0]=1;tick();@(negedge clock);program_result_valid[0]=0;
   while(state[0]!=6) tick();
   @(negedge clock);gateClosed[0]=0;gateOpen[0]=1;drainAcks[0]=0;resume_ready[0]=1;
   while(!resume_valid[0]) tick();tick();@(negedge clock);resume_ready[0]=0;
    $display("NORMAL_TERMINAL"); terminal(0,0);step(10);
   if(quiesce[0] || completed[0]!=0 || !busy[0]) $fatal(1,"normal retiring reasserted quiesce or completed early");
   if(normalCase==0) retire();
   else begin
     @(negedge clock);boundaryBusy=0;held_valid=0;cleanupFault=1;
     if(normalCase==2) begin locked[0]=0;gateOpen[0]=0;end
     step(3);
     if(normalCase==2) begin
       step(8);if(!busy[0] || completed[0]!=0 || !errors[0][9] || requests_valid!=0)
         $fatal(1,"fault lost across retired backpressure");
       @(negedge clock);locked[0]=1;gateOpen[0]=1;step(3);
     end
   end
   if(completed[0]!=1 || busy[0] || lastSuccess[0]!=(normalCase==0) || quiesce[0] ||
       (normalCase!=0 && !errors[0][9]))
     $fatal(1,"retirement-edge fault lost or normal bookkeeping failed case=%0d success=%b fatal=%b",normalCase,lastSuccess[0],errors[0][9]);
   end

   $display("CLOCK_RATE_CLEANUP_COMPONENT_PASS cycles=%0d two_lanes deadline_priority terminal_retirement wrong_tags sticky_fault reset",cycles);
   $finish;
 end
endmodule
