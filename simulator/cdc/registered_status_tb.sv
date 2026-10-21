`timescale 1ns/1ps
module registered_status_tb;
  reg sourceClock=0, destinationClock=0, commonColdReset=0, statusIn=0;
  reg sourceRun=1, destinationRun=1;
  integer sourceHalf=5, destinationHalf=7;
  wire statusOut;
  RegisteredStatusClockBoundary dut(.*);
  always begin #(sourceHalf); if(sourceRun) sourceClock=~sourceClock; end
  initial begin #3; forever begin #(destinationHalf); if(destinationRun) destinationClock=~destinationClock; end end
  integer sr=7, dr=7, q=0, pipe=0, checks=0;
  integer fault=0;
  reg observed;
  // Independent edge-count oracle, not derived from implementation hierarchy.
  always @(posedge sourceClock or posedge commonColdReset) begin
    if(commonColdReset) begin sr<=7; q<=0; end
    else begin sr<=((sr<<1)&7); q<=sr!=0 ? 0 : statusIn; end
  end
  always @(posedge destinationClock or posedge commonColdReset) begin
    if(commonColdReset) begin dr<=7; pipe<=0; end
    else begin dr<=((dr<<1)&7); pipe<=dr!=0 ? 0 : ((pipe<<1)|q)&3; end
  end
  always @(posedge sourceClock or posedge destinationClock or posedge commonColdReset) begin
    #1;
    observed=statusOut;
    // Deliberate monitor negative controls, never a replacement DUT.
    if(fault==1 && commonColdReset) observed=1;
    if(fault==2 && !commonColdReset && dr!=0) observed=1;
    if(observed !== ((pipe & 2)!=0)) $fatal(1,"STATUS_ORACLE_MISMATCH fault=%0d at %0t",fault,$time);
    checks=checks+1;
  end
  task reset_now;
    begin commonColdReset=1; #2; if(statusOut!==0) $fatal(1,"RESET_NOT_ASYNCHRONOUS"); end
  endtask
  task settle;
    begin #400; if(statusOut!==statusIn) $fatal(1,"STATUS_DID_NOT_SETTLE"); end
  endtask
  initial begin
    if($value$plusargs("fault=%d",fault)) begin end
    #2; reset_now(); #31; statusIn=1; commonColdReset=0; settle();
    statusIn=0; settle();
    // A pulse entirely between source edges must not become a launch.
    @(negedge sourceClock); #1; statusIn=1; #1; statusIn=0; settle();
    statusIn=1; settle();
    // Calibration fault while both clocks stopped: board common reset must
    // revoke readiness immediately, even if no more source edges occur.
    @(negedge sourceClock); sourceRun=0;
    @(negedge destinationClock); destinationRun=0;
    #11; statusIn=0; #11;
    if(statusOut!==1) $fatal(1,"UNEXPECTED_RAW_STATUS_ASYNC_PATH");
    reset_now(); #29; commonColdReset=0;
    #80; if(statusOut!==0) $fatal(1,"STALE_READY_WHILE_STOPPED");
    destinationRun=1; #160; if(statusOut!==0) $fatal(1,"STALE_READY_DEST_RESTART");
    statusIn=1; #80; if(statusOut!==0) $fatal(1,"READY_WITHOUT_SOURCE_RELEASE");
    sourceRun=1; settle();
    // Destination stopped during fault; source may restart first but the
    // destination must complete its own release before readiness can return.
    @(negedge destinationClock); destinationRun=0;
    statusIn=0; reset_now(); #21; commonColdReset=0; #120;
    statusIn=1; #120; if(statusOut!==0) $fatal(1,"READY_WITH_STOPPED_DEST");
    destinationRun=1; settle();
    // Swap the relative clock rates and phases, and inject short common reset.
    sourceHalf=11; destinationHalf=4;
    statusIn=0; reset_now(); #1; commonColdReset=0; settle();
    statusIn=1; settle();
    if(checks<200) $fatal(1,"INSUFFICIENT_CHECKS");
    $display("REGISTERED_STATUS_NATIVE_PASS checks=%0d",checks); $finish;
  end
  initial begin #10000; $fatal(1,"TIMEOUT"); end
endmodule
