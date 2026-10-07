`timescale 1ns/1ps
// Dedicated integer-frequency TX PLL. Both DDR clocks share the same local PLL;
// the calibration PLL is separate so CLKOUTPHY is not misused as a fabric clock.
// Software owns PHY TXDLY=0/RXDLY=1 and must verify both before enabling TX.
module native_gmac_pll_pair(input wire ui_clock, cold_reset,
    output wire tx_source, tx_forward_source, delay_source, locked);
    wire tx_feedback, delay_feedback, tx_locked, delay_locked;
    assign locked = tx_locked & delay_locked;
    PLLE4_ADV #(.CLKIN_PERIOD(4.0), .CLKFBOUT_MULT(4), .DIVCLK_DIVIDE(1),
        .CLKOUT0_DIVIDE(8), .CLKOUT0_PHASE(0.0),
        .CLKOUT1_DIVIDE(8), .CLKOUT1_PHASE(90.0), .COMPENSATION("AUTO")) tx_pll (
        .CLKIN(ui_clock), .RST(cold_reset), .PWRDWN(1'b0),
        .CLKFBOUT(tx_feedback), .CLKFBIN(tx_feedback),
        .CLKOUT0(tx_source), .CLKOUT1(tx_forward_source), .LOCKED(tx_locked),
        .CLKOUT0B(), .CLKOUT1B(), .CLKOUTPHY(), .CLKOUTPHYEN(1'b0),
        .DCLK(1'b0), .DEN(1'b0), .DWE(1'b0), .DADDR(7'b0), .DI(16'b0), .DO(), .DRDY());
    PLLE4_ADV #(.CLKIN_PERIOD(4.0), .CLKFBOUT_MULT(4), .DIVCLK_DIVIDE(1),
        .CLKOUT0_DIVIDE(2), .CLKOUT0_PHASE(0.0), .COMPENSATION("AUTO")) delay_pll (
        .CLKIN(ui_clock), .RST(cold_reset), .PWRDWN(1'b0),
        .CLKFBOUT(delay_feedback), .CLKFBIN(delay_feedback),
        .CLKOUT0(delay_source), .CLKOUT1(), .LOCKED(delay_locked),
        .CLKOUT0B(), .CLKOUT1B(), .CLKOUTPHY(), .CLKOUTPHYEN(1'b0),
        .DCLK(1'b0), .DEN(1'b0), .DWE(1'b0), .DADDR(7'b0), .DI(16'b0), .DO(), .DRDY());
endmodule

module native_gmac_pll_pair_probe(input wire ui_pad, cold_reset,
    output wire tx_source, tx_forward_source, delay_source, locked);
    wire ui_clock;
    (* DONT_TOUCH="TRUE" *) BUFG input_buffer(.I(ui_pad), .O(ui_clock));
    native_gmac_pll_pair clock_dut(.ui_clock(ui_clock), .cold_reset(cold_reset),
        .tx_source(tx_source), .tx_forward_source(tx_forward_source),
        .delay_source(delay_source), .locked(locked));
endmodule
