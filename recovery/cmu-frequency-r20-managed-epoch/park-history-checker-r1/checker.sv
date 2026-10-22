`timescale 1ns/1ps
module park_history_checker;
reg fabricClock=0,reset=1,bootstrapPark=0,controlParkRequest=0;
reg fabricHeld_valid=0,fabricIdle=0,controlEpochBusy=1;
reg [7:0] controlQualifiedEpoch=1,fabricHeld_bits=1;
integer proofPauseSeen=0,scenario=0;
always #5 fabricClock=~fabricClock;
  reg controlRawHeldSeen=0,cancelBeforeHeldSeen=0;
  reg [7:0] controlRawHeldEpoch=0;
  integer controlRawHeldSamples=0,controlAnyRawHeldSamples=0;
  // A runtime park may legally outlive the transient raw-held observation on
  // cancellation. It still needs a matching, genuinely idle prior-edge witness.
  always @(posedge fabricClock) begin
    if(reset) begin
      controlRawHeldSeen=0;controlRawHeldEpoch=0;controlRawHeldSamples=0;controlAnyRawHeldSamples=0;
    end else begin
      // Check before capturing this edge: a simultaneous observation cannot
      // retroactively justify an earlier park request.
      if(controlParkRequest && !bootstrapPark &&
          (!controlRawHeldSeen || controlRawHeldEpoch!==controlQualifiedEpoch))
        $fatal(1,"MANAGED_CONTROL_PARK_WITHOUT_PRIOR_MATCHED_RAW_HELD");
      if(fabricHeld_valid && controlEpochBusy &&
          fabricHeld_bits===controlQualifiedEpoch && fabricHeld_bits!=0) begin
        controlAnyRawHeldSamples=controlAnyRawHeldSamples+1;
        if(fabricIdle) begin
          controlRawHeldSeen=1;controlRawHeldEpoch=fabricHeld_bits;
          controlRawHeldSamples=controlRawHeldSamples+1;
        end
      end
    end
  end

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
      if(!cancelBeforeHeldSeen || proofPauseSeen!=0)
        $fatal(1,"MANAGED_CONTROL_CANCEL_ORDER_OR_NORMAL_ONLY_PAUSE");

 $display("PARK_HISTORY_CHECKER_PASS scenario=%0d raw=%0d qualified=%0d",scenario,controlAnyRawHeldSamples,controlRawHeldSamples);
 $finish;
end
initial begin #1000;$fatal(1,"UNIT_TIMEOUT");end
endmodule
