`timescale 1ns/1ps
// Component-only two-clock test of emitted, unmodified FixedClockSafetyGuard.
// Fixed consumption is observed at the request mailbox boundary. Expected
// receipts come from test intent and actual AON command handshakes, never from
// DUT reply values. Fault timing is checked against a source-domain window model.
module fixed_clock_safety_tb;
  reg aon = 0, fixed_clk = 0, fixed_run = 1;
  always #17 aon = ~aon;
  initial begin #2; forever begin #5; if (fixed_run) fixed_clk = ~fixed_clk; end end
  reg cold = 0, safe = 1;
  reg command_valid = 0, command_enable = 0, receipt_ready = 0;
  reg [15:0] command_epoch = 0;
  wire command_ready, receipt_valid, receipt_enable, receipt_guarded, fault;
  wire [15:0] receipt_epoch;
  FixedClockSafetyGuard dut (
    .aonClock(aon), .fixedClock(fixed_clk), .commonColdReset(cold), .safe(safe),
    .io_command_ready(command_ready), .io_command_valid(command_valid),
    .io_command_bits_epoch(command_epoch), .io_command_bits_enable(command_enable),
    .io_receipt_ready(receipt_ready), .io_receipt_valid(receipt_valid),
    .io_receipt_bits_command_epoch(receipt_epoch),
    .io_receipt_bits_command_enable(receipt_enable),
    .io_receipt_bits_guarded(receipt_guarded), .io_fault(fault)
  );
  reg [8*32-1:0] case_name, inject;
  integer inject_mode = 0;
  // Negative controls corrupt only checker observations; no forced DUT state,
  // special unconditional fatal, or alternate negative-only assertion path.
  wire observed_valid = receipt_valid && (inject_mode != 3);
  wire [15:0] observed_epoch = receipt_epoch ^ ((inject_mode == 1) ? 16'h1 : 16'h0);
  wire observed_guarded = receipt_guarded ^ (inject_mode == 2);
  wire observed_fault = (inject_mode == 4) ? 1'b0 : fault;
  wire [17:0] observed_receipt = {observed_epoch, receipt_enable, observed_guarded};
  reg [16:0] accepted_command [0:63];
  reg [17:0] expected_receipt [0:63];
  integer accepted = 0, consumed = 0, returned = 0;
  integer blocked_command_cycles = 0, blocked_receipt_cycles = 0;
  integer fixed_low_edges = 0, aon_low_edges = 0, fault_age = 0;
  integer reset_count = 0;
  reg intent_guarded = 0, prior_stall = 0, prior_command_stall = 0;
  reg [17:0] held_receipt;
  reg [16:0] held_command;
  reg m_owned = 0, m_active = 0, m_failed = 0, fault_seen = 0;
  reg [15:0] m_epoch = 0, m_last = 0;
  wire fixed_fire = dut._requests_destination_valid && dut.requests_destination_ready;
  wire [16:0] fixed_command = dut._requests_destination_bits;
  wire fixed_enable = fixed_command[0];
  wire [15:0] fixed_epoch = fixed_command[16:1];

  always @(posedge fixed_clk or posedge cold) begin
    if (cold) begin
      consumed = 0; m_owned = 0; m_active = 0; m_failed = 0;
      m_epoch = 0; m_last = 0; fixed_low_edges = 0;
    end else if (!dut._fixedReset_r_resetOut) begin
      if (!safe) fixed_low_edges = fixed_low_edges + 1;
      if (m_failed && fixed_fire) $fatal(1, "FAIL_WINDOW consumed after sticky failure");
      if (m_active && !safe && !(fixed_fire && !fixed_enable && m_owned && fixed_epoch == m_epoch)) m_failed = 1;
      if (fixed_fire) begin
        if (consumed >= accepted) $fatal(1, "FAIL_CONSERVATION fixed consumption without accepted command");
        if (fixed_command !== accepted_command[consumed]) $fatal(1, "FAIL_TAG fixed consumed wrong command");
        if (fixed_enable) begin
          if (m_owned || fixed_epoch == 0 || fixed_epoch <= m_last) m_failed = 1;
          else begin m_owned = 1; m_epoch = fixed_epoch; m_last = fixed_epoch; m_active = expected_receipt[consumed][0]; end
        end else begin
          if (!m_owned || fixed_epoch != m_epoch) m_failed = 1;
          else begin m_owned = 0; m_active = 0; end
        end
        $display("FIXED_CONSUME time=%0t epoch=%0d enable=%0b safe=%0b", $time, fixed_epoch, fixed_enable, safe);
        consumed = consumed + 1;
      end
    end
  end
  always @(posedge aon or posedge cold) begin
    if (cold) begin
      accepted = 0; returned = 0; prior_stall = 0; prior_command_stall = 0;
      fault_age = 0; fault_seen = 0; aon_low_edges = 0;
    end else if (!dut._aonReset_r_resetOut) begin
      if (!safe) aon_low_edges = aon_low_edges + 1;
      if (prior_command_stall && ({command_epoch, command_enable} !== held_command || !command_valid))
        $fatal(1, "FAIL_STABILITY command changed while backpressured");
      if (prior_stall && (!observed_valid || observed_receipt !== held_receipt))
        $fatal(1, "FAIL_STABILITY receipt changed while backpressured");
      prior_command_stall = command_valid && !command_ready;
      held_command = {command_epoch, command_enable};
      prior_stall = observed_valid && !receipt_ready;
      held_receipt = observed_receipt;
      if (prior_command_stall) blocked_command_cycles = blocked_command_cycles + 1;
      if (prior_stall) blocked_receipt_cycles = blocked_receipt_cycles + 1;
      if (command_valid && command_ready) begin
        if (accepted >= 64) $fatal(1, "FAIL_CONSERVATION scoreboard overflow");
        accepted_command[accepted] = {command_epoch, command_enable};
        expected_receipt[accepted] = {command_epoch, command_enable, intent_guarded};
        accepted = accepted + 1;
        $display("AON_ACCEPT time=%0t epoch=%0d enable=%0b guarded_expect=%0b", $time, command_epoch, command_enable, intent_guarded);
      end
      if (observed_valid && receipt_ready) begin
        if (returned >= accepted || returned >= consumed) $fatal(1, "FAIL_CONSERVATION unsolicited receipt");
        if (observed_receipt[17:1] !== expected_receipt[returned][17:1])
          $fatal(1, "FAIL_TAG receipt expected=%h actual=%h", expected_receipt[returned], observed_receipt);
        if (observed_receipt[0] !== expected_receipt[returned][0])
          $fatal(1, "FAIL_WINDOW guarded expected=%b actual=%b", expected_receipt[returned][0], observed_receipt[0]);
        returned = returned + 1;
        $display("AON_RECEIPT time=%0t epoch=%0d enable=%0b guarded=%0b", $time, observed_epoch, receipt_enable, observed_guarded);
      end
      if (m_failed) fault_age = fault_age + 1;
      if ((!m_failed && observed_fault !== 1'b0) || (fault_age >= 3 && observed_fault !== 1'b1))
        $fatal(1, "FAIL_WINDOW fault expected_source=%b age=%0d actual=%b", m_failed, fault_age, observed_fault);
      if (fault_seen && observed_fault !== 1'b1) $fatal(1, "FAIL_WINDOW sticky fault cleared without cold reset");
      if (observed_fault) fault_seen = 1;
    end
  end

  task wait_aon(input integer n); repeat(n) @(negedge aon); endtask
  task send_command(input [15:0] ep, input en, input guarded_expect);
    begin
      @(negedge aon); command_epoch = ep; command_enable = en;
      intent_guarded = guarded_expect; command_valid = 1;
      @(posedge aon); while (!command_ready) @(posedge aon);
      @(negedge aon); command_valid = 0;
    end
  endtask
  task wait_raw_receipt; begin while (!receipt_valid) @(negedge aon); end endtask
  task drain(input integer n);
    integer raw_count;
    begin
      // Wait on actual transfers, not checker counts, so drop-receipt negative
      // controls reach the ordinary final conservation assertion.
      raw_count = 0; @(negedge aon); receipt_ready = 1;
      while (raw_count < n) begin @(posedge aon); if (receipt_valid) raw_count = raw_count + 1; end
      @(negedge aon); receipt_ready = 0;
    end
  endtask
  task assert_reset;
    begin
      @(negedge aon); command_valid = 0; receipt_ready = 0;
      $display("RESET_CANCEL accepted=%0d consumed=%0d returned=%0d", accepted, consumed, returned);
      cold = 1; reset_count = reset_count + 1;
      #1;
      if (dut.owned !== 0 || dut.active !== 0 || dut.failed !== 0 || dut.pending !== 0 ||
          dut.lastEpoch !== 0 || dut.epoch !== 0 || receipt_valid !== 0 || fault !== 0 ||
          dut.requests.requestToggle !== 0 || dut.requests.ackToggle !== 0 || dut.requests.valid !== 0 || dut.requests.token !== 0 ||
          dut.requests.requestSync.stages !== 0 || dut.requests.ackSync.stages !== 0 ||
          dut.replies.requestToggle !== 0 || dut.replies.ackToggle !== 0 || dut.replies.valid !== 0 || dut.replies.token !== 0 ||
          dut.replies.requestSync.stages !== 0 || dut.replies.ackSync.stages !== 0 || dut.faultSync.stages !== 0)
        $fatal(1, "FAIL_RESET owners not canceled asynchronously");
      repeat(4) @(negedge aon); fixed_run = 1; safe = 1; cold = 0;
      wait_aon(8);
      if (!command_ready || receipt_valid || fault) $fatal(1, "FAIL_RESET stale work after reset release");
    end
  endtask
  task fresh_epoch_one;
    begin send_command(1,1,1); drain(1); send_command(1,0,0); drain(1); end
  endtask
  task prove_failed_closed;
    integer before_consumed;
    begin
      wait_aon(6);
      if (!observed_fault) $fatal(1, "FAIL_WINDOW missing fault after failed command/window");
      before_consumed = consumed;
      send_command(32,1,0); wait_aon(12);
      if (consumed != before_consumed || receipt_valid || dut.requests_destination_ready)
        $fatal(1, "FAIL_WINDOW failure did not prevent later fixed consumption");
    end
  endtask
  task finish_check(input integer blocked_outstanding);
    begin
      wait_aon(8);
      if (accepted != returned + blocked_outstanding || consumed != returned || receipt_valid)
        $fatal(1, "FAIL_CONSERVATION accepted=%0d consumed=%0d returned=%0d expected_blocked=%0d receipt_valid=%b", accepted, consumed, returned, blocked_outstanding, receipt_valid);
      $display("PASS case=%0s inject=%0s accepted=%0d consumed=%0d returned=%0d command_stall=%0d receipt_stall=%0d resets=%0d fixed_low=%0d aon_low=%0d fault=%0b", case_name, inject, accepted, consumed, returned, blocked_command_cycles, blocked_receipt_cycles, reset_count, fixed_low_edges, aon_low_edges, fault);
      $finish;
    end
  endtask

  integer saved_consumed, saved_fixed_low, saved_aon_low;
  initial begin
    if (!$value$plusargs("CASE=%s", case_name)) case_name = "arm_exact";
    if (!$value$plusargs("INJECT=%s", inject)) inject = "none";
    if (inject == "tag") inject_mode = 1;
    if (inject == "guarded") inject_mode = 2;
    if (inject == "drop_receipt") inject_mode = 3;
    if (inject == "fault") inject_mode = 4;
    $display("BEGIN case=%0s inject=%0s aon_period=34ns fixed_period=10ns fixed_phase=2ns", case_name, inject);
    assert_reset();
    case (case_name)
      "arm_exact": begin
        send_command(16'h1234,1,1); drain(1); send_command(16'h1234,0,0); drain(1); finish_check(0);
      end
      "backpressure": begin
        @(negedge fixed_clk); fixed_run = 0; send_command(7,1,1);
        fork
          begin send_command(7,0,0); end
          begin wait_aon(10); fixed_run = 1; end
        join
        wait_raw_receipt(); wait_aon(12);
        if (blocked_command_cycles < 8 || blocked_receipt_cycles < 8) $fatal(1, "FAIL_COVER backpressure not exercised");
        drain(2); send_command(8,1,1); drain(1); send_command(8,0,0); drain(1); finish_check(0);
      end
      "unsafe_arm": begin
        @(negedge fixed_clk); safe = 0; send_command(1,1,0); drain(1); wait_aon(5);
        if (!dut.owned || dut.active || fault) $fatal(1, "FAIL_WINDOW unsafe arm must own but not activate");
        send_command(1,0,0); drain(1);
        if (dut.owned || dut.active || fault) $fatal(1, "FAIL_WINDOW unsafe arm disarm did not cleanly release");
        @(negedge fixed_clk); safe = 1; repeat(3) @(negedge fixed_clk);
        send_command(2,1,1); drain(1); send_command(2,0,0); drain(1); finish_check(0);
      end
      "arm_just_raised": begin
        @(negedge fixed_clk); safe = 0; send_command(1,1,0);
        while (!(dut._requests_destination_valid && dut.requests_destination_ready)) @(negedge fixed_clk);
        safe = 1; // current sample is safe, previous fixed sample was unsafe
        drain(1);
        if (dut.active || fault) $fatal(1, "FAIL_WINDOW arm lacked two safe source samples");
        send_command(1,0,0); drain(1); finish_check(0);
      end
      "arm_just_revoked": begin
        send_command(1,1,0);
        while (!(dut._requests_destination_valid && dut.requests_destination_ready)) @(negedge fixed_clk);
        safe = 0; // previous fixed sample was safe, current consumption is unsafe
        drain(1);
        if (dut.active || fault) $fatal(1, "FAIL_WINDOW arm trusted stale safe sample");
        send_command(1,0,0); drain(1); finish_check(0);
      end
      "brief_revoke": begin
        send_command(1,1,1); drain(1);
        saved_fixed_low = fixed_low_edges; saved_aon_low = aon_low_edges;
        @(posedge aon); @(negedge fixed_clk); safe = 0;
        @(negedge fixed_clk); safe = 1;
        if (fixed_low_edges != saved_fixed_low + 1 || aon_low_edges != saved_aon_low)
          $fatal(1, "FAIL_COVER revocation must span one fixed edge and zero AON edges");
        wait_aon(14); prove_failed_closed(); finish_check(1);
      end
      "disarm_then_change": begin
        send_command(1,1,1); drain(1); saved_consumed = consumed; send_command(1,0,0);
        while (consumed == saved_consumed) @(negedge fixed_clk);
        @(negedge fixed_clk); safe = 0;
        wait_raw_receipt(); wait_aon(10); drain(1);
        if (fault || dut.owned || dut.active) $fatal(1, "FAIL_WINDOW post-disarm change faulted");
        finish_check(0);
      end
      "disarm_at_change": begin
        send_command(1,1,1); drain(1); send_command(1,0,0);
        while (!(dut._requests_destination_valid && dut.requests_destination_ready)) @(negedge fixed_clk);
        safe = 0; @(posedge fixed_clk); @(negedge fixed_clk); drain(1); wait_aon(8);
        if (fault || dut.owned || dut.active) $fatal(1, "FAIL_WINDOW matching disarm edge must close window");
        finish_check(0);
      end
      "wrong_epoch": begin
        send_command(1,1,1); drain(1); send_command(2,0,0); drain(1); prove_failed_closed(); finish_check(1);
      end
      "duplicate_active": begin
        send_command(1,1,1); drain(1); send_command(1,1,0); drain(1); prove_failed_closed(); finish_check(1);
      end
      "duplicate_retired": begin
        fresh_epoch_one(); send_command(1,1,0); drain(1); prove_failed_closed(); finish_check(1);
      end
      "zero_epoch": begin
        send_command(0,1,0); drain(1); prove_failed_closed(); finish_check(1);
      end
      "reset_command": begin
        @(negedge fixed_clk); fixed_run = 0; send_command(9,1,1);
        @(negedge aon); command_epoch = 10; command_enable = 1; command_valid = 1; intent_guarded = 1;
        wait_aon(8);
        if (accepted != 1 || consumed != 0 || returned != 0 || command_ready) $fatal(1, "FAIL_COVER command owner was not held");
        assert_reset(); fresh_epoch_one(); finish_check(0);
      end
      "reset_receipt": begin
        send_command(9,1,1); wait_raw_receipt(); wait_aon(8);
        if (accepted != 1 || consumed != 1 || returned != 0 || !dut.owned) $fatal(1, "FAIL_COVER receipt owner was not held");
        @(negedge fixed_clk); fixed_run = 0;
        assert_reset(); fresh_epoch_one(); finish_check(0);
      end
      "reset_fault": begin
        send_command(1,1,1); drain(1);
        @(negedge fixed_clk); safe = 0; @(negedge fixed_clk); safe = 1;
        prove_failed_closed();
        @(negedge fixed_clk); fixed_run = 0;
        assert_reset(); fresh_epoch_one(); finish_check(0);
      end
      "pause_receipt": begin
        send_command(1,1,1); wait_raw_receipt();
        @(negedge fixed_clk); fixed_run = 0; wait_aon(12);
        if (!dut.owned || !dut.active || !receipt_valid) $fatal(1, "FAIL_WINDOW paused source lost its owner");
        drain(1); wait_aon(6); fixed_run = 1; send_command(1,0,0); drain(1); finish_check(0);
      end
      default: $fatal(1, "FAIL_CONFIGURATION unknown case");
    endcase
  end
  initial begin #1000000; $fatal(1, "FAIL_TIMEOUT bounded simulation watchdog"); end
endmodule
