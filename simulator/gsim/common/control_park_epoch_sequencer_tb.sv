`timescale 1ns/1ps
// Ordering-only unit witness. parked and released are test inputs/models, NOT
// real MAC/PHY/MDIO, clock-gate, cross-domain or whole-system lifecycle proof.
module control_park_epoch_sequencer_tb;
  reg clock = 0, reset = 1;
  always #5 clock = ~clock;
  reg prepare_valid = 0, held_valid = 0, allIdle = 0;
  reg [7:0] prepare_epoch = 0, held_epoch = 0;
  reg completion_valid = 0, completion_canceled = 0;
  reg [7:0] completion_epoch = 0;
  reg consumed = 0, retired = 0, parked = 0, parkReleased = 0, holdRelease = 0;
  wire parkRequest, qualified_valid, permit, busy, fault;
  wire [7:0] qualified_epoch;
  integer checks = 0, completed = 0, faultCases = 0, negative = 0;
  reg [255:0] phase = "reset";

  CommonControlParkEpochSequencer dut (
    .clock(clock), .reset(reset),
    .io_prepare_valid(prepare_valid), .io_prepare_bits(prepare_epoch),
    .io_fabricHeld_valid(held_valid), .io_fabricHeld_bits(held_epoch),
    .io_fabricAllObligationsIdle(allIdle),
    .io_completion_valid(completion_valid), .io_completion_bits_epoch(completion_epoch),
    .io_completion_bits_canceled(completion_canceled),
    .io_terminalConsumedAtAon(consumed), .io_retired(retired),
    .io_parked(parked), .io_parkReleased(parkReleased),
    .io_parkRequest(parkRequest), .io_qualified_valid(qualified_valid),
    .io_qualified_bits(qualified_epoch), .io_retirementPermit(permit),
    .io_busy(busy), .io_fault(fault)
  );

  // Only the specified same-clock consumed-low ordering contract is modeled.
  always @(posedge clock) begin
    if (reset) parkReleased <= 0;
    else parkReleased <= !parkRequest && !holdRelease;
  end

  task step;
    begin @(posedge clock); #1; end
  endtask
  task check(input bit predicate, input string message);
    begin
      checks = checks + 1;
      if (!predicate) $fatal(1, "CONTROL_PARK_ORACLE phase=%0s: %s", phase, message);
    end
  endtask
  task coldReset;
    begin
      @(negedge clock);
      reset = 1; prepare_valid = 0; held_valid = 0; allIdle = 0;
      completion_valid = 0; completion_canceled = 0; consumed = 0;
      retired = 0; parked = 0; holdRelease = 0;
      repeat (3) step;
      check(!parkReleased, "release receipt must reset low");
      @(negedge clock); reset = 0; step;
      check(!busy && !fault && !parkRequest && !qualified_valid && !permit,
        "cold reset must clear ownership, requests and protocol fault");
    end
  endtask
  task prepare(input [7:0] epoch);
    begin
      @(negedge clock); prepare_epoch = epoch; prepare_valid = 1;
      step;
      @(negedge clock); prepare_valid = 0;
      #1;
      check(busy && !fault && !parkRequest && !qualified_valid && !permit,
        "prepare must reserve without parking old CPU CSR work");
    end
  endtask
  task holdAndQualify(input [7:0] epoch);
    begin
      @(negedge clock); held_valid = 1; held_epoch = epoch; allIdle = 1; parked = 0;
      step;
      check(parkRequest && !qualified_valid && !permit, "held requests park but is not MAC proof");
      @(negedge clock); parked = 1; #1;
      check(qualified_valid && qualified_epoch == epoch, "actual current parked must qualify owned epoch");
      step; // The actual outward qualification, not an internal hint, is retained.
    end
  endtask
  task terminal(input [7:0] epoch, input bit canceled);
    begin
      @(negedge clock);
      completion_valid = 1; completion_epoch = epoch; completion_canceled = canceled;
      #1;
      check(!qualified_valid && !permit, "terminal must immediately withdraw qualification");
      step;
    end
  endtask
  task consumeAndRetire;
    begin
      @(negedge clock); consumed = 1; holdRelease = 1;
      step;
      check(!parkRequest && !qualified_valid && !permit && busy,
        "AON consumption releases park but cannot use a preexisting release level");
      repeat (3) begin
        step;
        check(!permit && !fault && busy, "retirement must wait for actual low-request observation");
      end
      @(negedge clock); holdRelease = 0; parked = 0; held_valid = 0; allIdle = 0;
      step;
      check(permit && busy && !parkRequest && !fault,
        "new local traffic must not require post-release re-drain");
      repeat (3) begin step; check(permit && busy && !fault, "real terminal owner persists until fire"); end
      @(negedge clock); retired = 1;
      step;
      // The real fabric withdraws its retained terminal on this same fire edge.
      retired = 0; completion_valid = 0; consumed = 0;
      #1;
      check(!busy && !permit && !qualified_valid && !parkRequest && !fault,
        "only real retirement fire clears ownership");
      completed = completed + 1;
    end
  endtask
  task checkStickyFault;
    begin
      step;
      check(fault && !qualified_valid && !permit, "bad protocol must fail closed");
      @(negedge clock); prepare_valid = 0; completion_valid = 0; consumed = 0; retired = 0;
      held_valid = 0; parked = 0;
      repeat (3) begin step; check(fault && !qualified_valid && !permit, "fault must remain sticky"); end
      faultCases = faultCases + 1;
    end
  endtask

  initial begin
    if ($value$plusargs("negative=%d", negative)) begin end
    coldReset;
    phase = "normal-current-proof";
    prepare(1);
    @(negedge clock); parked = 1;
    repeat (3) begin step; check(!parkRequest && !qualified_valid, "parked alone is not epoch proof"); end
    @(negedge clock); held_valid = 1; held_epoch = 2; allIdle = 1;
    repeat (3) begin step; check(!parkRequest && !qualified_valid, "wrong held epoch must be ignored"); end
    @(negedge clock); held_epoch = 1; allIdle = 0;
    repeat (3) begin step; check(!parkRequest && !qualified_valid, "all real fabric owners must drain first"); end
    holdAndQualify(1);
    @(negedge clock); parked = 0; #1;
    check(parkRequest && !qualified_valid && !fault, "live false parked must withdraw proof without global fault");
    step;
    @(negedge clock); parked = 1; held_valid = 0; #1;
    check(parkRequest && !qualified_valid, "lost real held must withdraw current proof");
    step;
    @(negedge clock); held_valid = 1; allIdle = 0; #1;
    check(parkRequest && !qualified_valid, "nonidle fabric cannot retain outward proof");
    step;
    @(negedge clock); allIdle = 1; #1;
    check(qualified_valid && qualified_epoch == 1, "current proof can recover on the same owned epoch");
    terminal(1, 0);
    repeat (4) begin step; check(parkRequest && !permit && !fault, "completion is not AON consumption"); end
    consumeAndRetire;

    phase = "early-cancel-idle-release";
    prepare(2);
    check(parkReleased, "early cancellation deliberately begins with idle release high");
    terminal(2, 1);
    check(!parkRequest && !fault, "early cancel requires no park or qualification");
    consumeAndRetire;

    phase = "late-held-cancel-wins";
    prepare(3);
    @(negedge clock);
    held_valid = 1; held_epoch = 3; allIdle = 1; parked = 1;
    completion_valid = 1; completion_epoch = 3; completion_canceled = 1;
    step;
    check(!parkRequest && !qualified_valid && !fault, "matching canceled terminal wins over unsent park");
    consumeAndRetire;

    phase = "unqualified-phy-like-cancel";
    prepare(4);
    @(negedge clock); held_valid = 1; held_epoch = 4; allIdle = 1; parked = 0;
    repeat (5) step;
    check(parkRequest && !qualified_valid && !fault, "unavailable MAC proof is not a global fault");
    terminal(4, 1);
    check(parkRequest, "unqualified cancel still retains already asserted park until receipt");
    consumeAndRetire;
    phase = "next-epoch-after-cancel";
    prepare(5); holdAndQualify(5); terminal(5, 0); consumeAndRetire;

    phase = "zero-prepare"; coldReset;
    @(negedge clock); prepare_valid = 1; prepare_epoch = 0;
    checkStickyFault;
    phase = "overlapping-prepare"; coldReset; prepare(1);
    @(negedge clock); prepare_valid = 1; prepare_epoch = 2;
    checkStickyFault;
    phase = "stale-prepare"; coldReset; prepare(7); terminal(7, 1); consumeAndRetire;
    @(negedge clock); prepare_valid = 1; prepare_epoch = 7;
    checkStickyFault;
    phase = "epoch-no-wrap"; coldReset; prepare(255); terminal(255, 1); consumeAndRetire;
    @(negedge clock); prepare_valid = 1; prepare_epoch = 1;
    checkStickyFault;
    phase = "wrong-terminal-epoch"; coldReset; prepare(1); holdAndQualify(1);
    @(negedge clock); completion_valid = 1; completion_epoch = 2; completion_canceled = 1;
    checkStickyFault;
    check(parkRequest && busy, "protocol fault may not reopen an already parked owner");
    phase = "changed-before-aon"; coldReset; prepare(1); terminal(1, 1);
    @(negedge clock); completion_epoch = 2;
    checkStickyFault;
    phase = "withdrawn-before-aon"; coldReset; prepare(1); terminal(1, 1);
    @(negedge clock); completion_valid = 0;
    checkStickyFault;
    phase = "changed-canceled-bit"; coldReset; prepare(1); holdAndQualify(1); terminal(1, 0);
    @(negedge clock); completion_canceled = 1;
    checkStickyFault;
    phase = "unqualified-normal"; coldReset; prepare(1);
    @(negedge clock); completion_valid = 1; completion_epoch = 1; completion_canceled = 0;
    checkStickyFault;
    phase = "normal-same-edge-proof"; coldReset; prepare(1);
    @(negedge clock); held_valid = 1; held_epoch = 1; allIdle = 1; parked = 0;
    step;
    @(negedge clock); parked = 1; completion_valid = 1; completion_epoch = 1; completion_canceled = 0;
    checkStickyFault;
    phase = "consumption-without-terminal"; coldReset; prepare(1);
    @(negedge clock); consumed = 1;
    checkStickyFault;
    phase = "retirement-without-permit"; coldReset; prepare(1);
    @(negedge clock); retired = 1;
    checkStickyFault;
    phase = "terminal-without-owner"; coldReset;
    @(negedge clock); completion_valid = 1; completion_epoch = 1; completion_canceled = 1;
    checkStickyFault;

    phase = "oracle-negative";
    // Deliberately wrong independent expected count proves the runner does not
    // mistake a simulator exit/message or an ignored check for successful proof.
    check(completed == (negative != 0 ? 8 : 7), "independent retired-epoch count");
    check(faultCases == 13, "independent protocol-fault case count");
    $display("CONTROL_PARK_EPOCH_SEQUENCER_PASS checks=%0d retired=%0d faults=%0d scope=ordering-only",
      checks, completed, faultCases);
    $finish;
  end
  initial begin #100000; $fatal(1, "CONTROL_PARK_ORACLE timeout phase=%0s", phase); end
endmodule
