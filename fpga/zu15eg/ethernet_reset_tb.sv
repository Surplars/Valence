`timescale 1ns/1ps
module ethernet_reset_tb;
  reg clock = 0;
  reg reset = 0;
  wire held;
  always #4 clock = ~clock;
  ResetHold dut(.clock(clock), .reset(reset), .io_asserted(held));
  integer epoch, count;
  initial begin
    for (epoch=0; epoch<5; epoch=epoch+1) begin
      #1.713 reset=1;
      #0.050;
      if (held !== 1'b1) $fatal(1,"Async assertion oracle mismatch");
      repeat(9) @(posedge clock);
      #0.050;
      if (held !== 1'b1) $fatal(1,"Counter advanced while reset held");
      @(negedge clock);
      #1.117 reset=0;
      for (count=1; count<=4005; count=count+1) begin
        @(posedge clock); #0.050;
        if (held !== (count<4000)) $fatal(1,"Registered release count oracle mismatch epoch=%0d edge=%0d",epoch,count);
      end
    end
    $display("ETHERNET_ASYNC_RESET_PASS epochs=5 hold_edges=4000 clock_period_ns=8");
    $finish;
  end
  initial begin #200000; $fatal(1,"Reset CDC test timed out"); end
endmodule
