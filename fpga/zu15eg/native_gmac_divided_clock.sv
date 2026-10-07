`timescale 1ns/1ps
// One physical 500MHz PLL output / global tree is common to both TX phases.
// Each DIV4 starts high on the first source rising edge after CLR. Releasing
// the forward divider one SOURCE cycle later makes a real +2ns TXC phase.
// CLR releases AFTER source rising edges (registered C->Q), leaving a full
// source cycle for recovery. Actual removal/recovery must both pass STA.
module native_gmac_divided_clock(input wire ui_clock, cold_reset,
    output wire tx_source, tx_pad_source, tx_forward_source, delay_source, locked);
    wire feedback, ref_source, pll_locked;
    PLLE4_ADV #(.CLKIN_PERIOD(4.0), .CLKFBOUT_MULT(4), .DIVCLK_DIVIDE(1),
        .CLKOUT0_DIVIDE(2), .COMPENSATION("AUTO")) pll (
        .CLKIN(ui_clock), .RST(cold_reset), .PWRDWN(1'b0),
        .CLKFBOUT(feedback), .CLKFBIN(feedback), .CLKOUT0(ref_source), .CLKOUT1(),
        .LOCKED(pll_locked), .CLKOUT0B(), .CLKOUT1B(), .CLKOUTPHY(), .CLKOUTPHYEN(1'b0),
        .DCLK(1'b0), .DEN(1'b0), .DWE(1'b0), .DADDR(7'b0), .DI(16'b0), .DO(), .DRDY());
    (* DONT_TOUCH="TRUE" *) BUFG delay_buffer(.I(ref_source), .O(delay_source));
    wire phase_inhibit=cold_reset | ~pll_locked;
    (* ASYNC_REG="TRUE" *) reg [2:0] phase_reset;
    always @(posedge delay_source or posedge phase_inhibit)
        if(phase_inhibit) phase_reset<=3'b111;
        else phase_reset<={phase_reset[1:0],1'b0};
    assign locked=pll_locked & ~phase_reset[2];
    (* DONT_TOUCH="TRUE" *) BUFGCE_DIV #(.BUFGCE_DIVIDE(4), .SIM_DEVICE("ULTRASCALE_PLUS")) raw_div (
        .I(delay_source), .CE(1'b1), .CLR(phase_reset[1]), .O(tx_source));
    (* DONT_TOUCH="TRUE" *) BUFGCE_DIV #(.BUFGCE_DIVIDE(4), .SIM_DEVICE("ULTRASCALE_PLUS")) forward_div (
        .I(delay_source), .CE(1'b1), .CLR(phase_reset[2]), .O(tx_forward_source));
    // Pad-only 0-degree tree: do not force its insertion delay to track the
    // widespread fabric / serial CMU raw tree. Pad and forward are paired.
    (* DONT_TOUCH="TRUE" *) BUFGCE_DIV #(.BUFGCE_DIVIDE(4), .SIM_DEVICE("ULTRASCALE_PLUS")) pad_div (
        .I(delay_source), .CE(1'b1), .CLR(phase_reset[1]), .O(tx_pad_source));
endmodule

// Dedicated ODDR250 architecture. Keep the legacy divided module and its
// hierarchy unchanged so either configurable board mode remains reproducible.
module native_gmac_quarter_clock(input wire ui_clock, cold_reset,
    output wire tx_source, tx_pad_source, tx_forward_source, delay_source, locked);
    wire feedback, ref_source, pll_locked;
    PLLE4_ADV #(.CLKIN_PERIOD(4.0), .CLKFBOUT_MULT(4), .DIVCLK_DIVIDE(1),
        .CLKOUT0_DIVIDE(2), .COMPENSATION("AUTO")) pll (
        .CLKIN(ui_clock), .RST(cold_reset), .PWRDWN(1'b0),
        .CLKFBOUT(feedback), .CLKFBIN(feedback), .CLKOUT0(ref_source), .CLKOUT1(),
        .LOCKED(pll_locked), .CLKOUT0B(), .CLKOUT1B(), .CLKOUTPHY(), .CLKOUTPHYEN(1'b0),
        .DCLK(1'b0), .DEN(1'b0), .DWE(1'b0), .DADDR(7'b0), .DI(16'b0), .DO(), .DRDY());
    (* DONT_TOUCH="TRUE" *) BUFG delay_buffer(.I(ref_source), .O(delay_source));
    wire phase_inhibit=cold_reset | ~pll_locked;
    (* ASYNC_REG="TRUE" *) reg [2:0] phase_reset;
    always @(posedge delay_source or posedge phase_inhibit)
        if(phase_inhibit) phase_reset<=3'b111;
        else phase_reset<={phase_reset[1:0],1'b0};
    assign locked=pll_locked & ~phase_reset[2];
    (* DONT_TOUCH="TRUE" *) BUFGCE_DIV #(.BUFGCE_DIVIDE(4), .SIM_DEVICE("ULTRASCALE_PLUS")) raw_div (
        .I(delay_source), .CE(1'b1), .CLR(phase_reset[1]), .O(tx_source));
    (* DONT_TOUCH="TRUE" *) BUFGCE_DIV #(.BUFGCE_DIVIDE(2), .SIM_DEVICE("ULTRASCALE_PLUS")) quarter_div (
        .I(delay_source), .CE(1'b1), .CLR(phase_reset[1]), .O(tx_pad_source));
    // Both release chains observe word edges; this is not the PHY TXC.
    assign tx_forward_source=tx_source;
endmodule

module native_gmac_divided_probe(input wire ui_pad, cold_reset,
    output wire tx_source, tx_pad_source, tx_forward_source, delay_source, locked);
    wire ui_clock;
    (* DONT_TOUCH="TRUE" *) BUFG input_buffer(.I(ui_pad), .O(ui_clock));
    native_gmac_divided_clock clock_dut(.ui_clock(ui_clock), .cold_reset(cold_reset),
        .tx_source(tx_source), .tx_forward_source(tx_forward_source),
        .tx_pad_source(tx_pad_source),
        .delay_source(delay_source), .locked(locked));
endmodule
