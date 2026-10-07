`timescale 1ns/1ps
// Experimental Bank66 receive clock deskew. PHY reset must NOT wait for LOCKED:
// some PHYs stop RXC while reset; waiting for RX MMCM lock would deadlock startup.
// Instantiate the raw RX BUFG outside, matched to this feedback BUFG.
module native_rx_clock(input wire pad_clock, cold_reset,
    output wire clock_source, locked);
    wire feedback, feedback_buffered;
    // MMCM supports true global-tree deskew. Use zero phase; do not apply the
    // MMCM VCO/8 phase rule to a PLLE4 (UG572's PLL-specific counter rule).
    MMCME4_ADV #(.CLKIN1_PERIOD(8.0), .CLKFBOUT_MULT_F(8.0), .DIVCLK_DIVIDE(1),
        .CLKOUT0_DIVIDE_F(8.0), .CLKOUT0_PHASE(0.0), .COMPENSATION("AUTO")) mmcm (
        .CLKIN1(pad_clock), .CLKIN2(1'b0), .CLKINSEL(1'b1), .RST(cold_reset), .PWRDWN(1'b0),
        .CLKFBOUT(feedback), .CLKFBIN(feedback_buffered), .CLKOUT0(clock_source),
        .LOCKED(locked), .CLKFBOUTB(), .CLKOUT0B(), .CLKOUT1(), .CLKOUT1B(),
        .CLKOUT2(), .CLKOUT2B(), .CLKOUT3(), .CLKOUT3B(), .CLKOUT4(), .CLKOUT5(), .CLKOUT6(),
        .DCLK(1'b0), .DEN(1'b0), .DWE(1'b0), .DADDR(7'b0), .DI(16'b0), .DO(), .DRDY(),
        .PSCLK(1'b0), .PSEN(1'b0), .PSINCDEC(1'b0), .PSDONE(), .CDDCDONE(),
        .CDDCREQ(1'b0), .CLKINSTOPPED(), .CLKFBSTOPPED());
    // Feedback and all RX CLKOUT0 buffers must have matched physical trees.
    (* DONT_TOUCH="TRUE" *) BUFG feedback_buffer(.I(feedback), .O(feedback_buffered));
endmodule

// OOC-only proxy for the already-global MIG UI clock. Retain the proxy BUFG
// because the real board's buffer also drives DDR/CPU and cannot disappear.
module native_eth_clock_probe(input wire ui_pad, cold_reset,
    output wire tx_source, delay_source, locked);
    wire ui_clock;
    (* DONT_TOUCH="TRUE" *) BUFG input_buffer(.I(ui_pad), .O(ui_clock));
    native_eth_clock clock_dut(.ui_clock(ui_clock), .cold_reset(cold_reset),
        .tx_source(tx_source), .delay_source(delay_source), .locked(locked));
endmodule

// Experimental PLL replacement for clk_wiz_eth's frequency synthesis. Keep the
// same 250MHz input and 125/500MHz outputs. Output BUFGs live in the board top.
// Not instantiated in the shipping board until independent and routed checks.
module native_eth_clock(input wire ui_clock, cold_reset,
    output wire tx_source, delay_source, locked);
    wire feedback;
    PLLE4_ADV #(.CLKIN_PERIOD(4.0), .CLKFBOUT_MULT(4), .DIVCLK_DIVIDE(1),
        .CLKOUT0_DIVIDE(8), .CLKOUT1_DIVIDE(2), .COMPENSATION("AUTO"), .CLKOUTPHY_MODE("VCO")) pll (
        .CLKIN(ui_clock), .RST(cold_reset), .PWRDWN(1'b0),
        .CLKFBOUT(feedback), .CLKFBIN(feedback),
        .CLKOUT0(tx_source), .CLKOUT1(delay_source), .LOCKED(locked),
        .CLKOUT0B(), .CLKOUT1B(), .CLKOUTPHY(), .CLKOUTPHYEN(1'b0),
        .DCLK(1'b0), .DEN(1'b0), .DWE(1'b0), .DADDR(7'b0), .DI(16'b0), .DO(), .DRDY());
endmodule
