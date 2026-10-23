`timescale 1ns/1ps
module reset_distribution_tb;
  reg cpuClock = 0, startupReset = 0, acquire = 0, retire = 0;
  wire synchronizedReset, functionalReset, owner;
  reg observePause = 0;
  wire observedReset = $test$plusargs("early_release") ? synchronizedReset : functionalReset;
  wire observedOwner = ($test$plusargs("lost_owner") && observePause) ? 1'b0 : owner;
  integer checks = 0, round, edgeIndex;
  CommonResetDistributionFixture dut(.*);

  task check(input bit condition, input string reason);
    begin
      checks = checks + 1;
      if (!condition) $fatal(1, "RESET_DISTRIBUTION_FAIL %s", reason);
    end
  endtask
  task tick(input integer halfPeriod);
    begin
      #(halfPeriod); cpuClock = 1;
      #1;
      #(halfPeriod); cpuClock = 0;
      #1;
    end
  endtask
  initial begin
    for (round = 0; round < 12; round = round + 1) begin
      // Both stopped-clock polarities, and phase offsets before cold assertion.
      #(round + 1); cpuClock = round % 2; #1;
      startupReset = 1; #1;
      check(synchronizedReset === 1'b1, "synchronizer assertion is not asynchronous");
      check(observedReset === 1'b1, "functional assertion is not asynchronous");
      check(owner === 1'b0, "cold reset did not clear owner");
      #19; cpuClock = 0; #1;
      startupReset = 0;
      #(7 + round);
      check(observedReset === 1'b1, "stopped clock released reset");
      acquire = 1;
      for (edgeIndex = 1; edgeIndex <= 4; edgeIndex = edgeIndex + 1) begin
        tick(2 + round % 3);
        check(synchronizedReset === (edgeIndex < 3), "three-edge synchronizer changed");
        check(observedReset === (edgeIndex < 4), "distribution release must take exactly four edges");
        check(owner === 1'b0, "owner admitted during reset release");
        // Pauses between every release edge must not advance any reset stage.
        #31;
        check(synchronizedReset === (edgeIndex < 3), "paused synchronizer advanced");
        check(observedReset === (edgeIndex < 4), "paused distribution advanced");
      end
      tick(3);
      check(owner === 1'b1, "owner not admitted after release");
      acquire = 0;
      // Normal DVFS only pauses/restarts the clock. It is not cold reset.
      observePause = 1; #97;
      check(observedReset === 1'b0, "ordinary clock stop asserted reset");
      check(observedOwner === 1'b1, "ordinary clock stop lost accepted owner");
      observePause = 0;
      tick(10); tick(5); tick(10);
      check(observedOwner === 1'b1, "rate-change edges lost accepted owner");
      check(observedReset === 1'b0, "rate-change edges asserted reset");
      // An accepted owner is retained by DFS, but a real common cold reset
      // must still clear it asynchronously, even with the CPU clock stopped.
      startupReset = 1; #1;
      check(synchronizedReset === 1'b1 && observedReset === 1'b1,
            "running cold reset did not assert through complete release chain");
      check(owner === 1'b0, "running cold reset did not clear retained owner");
      #13; startupReset = 0; #11;
      check(observedReset === 1'b1, "running cold reset released without a clock");
      for (edgeIndex = 1; edgeIndex <= 4; edgeIndex = edgeIndex + 1) begin
        tick(3);
        check(observedReset === (edgeIndex < 4), "running cold release changed four-edge contract");
      end
      acquire = 1; tick(3); acquire = 0;
      check(owner === 1'b1, "owner not reacquired after common cold reset");
      retire = 1; tick(4); retire = 0;
      check(owner === 1'b0, "owner did not retire explicitly");
    end
    $display("RESET_DISTRIBUTION_PASS checks=%0d rounds=12", checks);
    $finish;
  end
  initial begin #100000; $fatal(1, "RESET_DISTRIBUTION_TIMEOUT"); end
endmodule
