`timescale 1ns/1ps
// UI250 frequency synthesis with an explicit physical quarter-cycle TXC.
// PHY TXDLY must be cleared/read back; RXDLY remains enabled.
module native_gmac_eth_clock(input wire ui_clock, cold_reset,
    output wire tx_source, tx_forward_source, delay_source, locked);
    wire feedback;
    MMCME4_ADV #(.CLKIN1_PERIOD(4.0), .CLKFBOUT_MULT_F(4.0), .DIVCLK_DIVIDE(1),
        .CLKOUT0_DIVIDE_F(8.0), .CLKOUT0_PHASE(0.0),
        .CLKOUT1_DIVIDE(8), .CLKOUT1_PHASE(90.0),
        .CLKOUT2_DIVIDE(2), .COMPENSATION("AUTO")) mmcm (
        .CLKIN1(ui_clock), .CLKIN2(1'b0), .CLKINSEL(1'b1),
        .RST(cold_reset), .PWRDWN(1'b0), .CLKFBOUT(feedback), .CLKFBIN(feedback),
        .CLKOUT0(tx_source), .CLKOUT1(tx_forward_source), .CLKOUT2(delay_source),
        .LOCKED(locked), .CLKFBOUTB(), .CLKOUT0B(), .CLKOUT1B(), .CLKOUT2B(),
        .CLKOUT3(), .CLKOUT3B(), .CLKOUT4(), .CLKOUT5(), .CLKOUT6(),
        .DCLK(1'b0), .DEN(1'b0), .DWE(1'b0), .DADDR(7'b0), .DI(16'b0), .DO(), .DRDY(),
        .PSCLK(1'b0), .PSEN(1'b0), .PSINCDEC(1'b0), .PSDONE(),
        .CDDCDONE(), .CDDCREQ(1'b0), .CLKINSTOPPED(), .CLKFBSTOPPED());
endmodule

// Buffered RX feedback retained. Physical 0.75ns capture phase (33.75deg)
// trades 0.25ns of hold margin for setup; external PHY budgets are unchanged.
module native_gmac_rx_clock(input wire pad_clock, cold_reset,
    output wire clock_source, locked);
    wire feedback, feedback_buffered;
    MMCME4_ADV #(.CLKIN1_PERIOD(8.0), .CLKFBOUT_MULT_F(8.0), .DIVCLK_DIVIDE(1),
        .CLKOUT0_DIVIDE_F(8.0), .CLKOUT0_PHASE(33.75), .COMPENSATION("AUTO")) mmcm (
        .CLKIN1(pad_clock), .CLKIN2(1'b0), .CLKINSEL(1'b1), .RST(cold_reset), .PWRDWN(1'b0),
        .CLKFBOUT(feedback), .CLKFBIN(feedback_buffered), .CLKOUT0(clock_source), .LOCKED(locked),
        .CLKFBOUTB(), .CLKOUT0B(), .CLKOUT1(), .CLKOUT1B(), .CLKOUT2(), .CLKOUT2B(),
        .CLKOUT3(), .CLKOUT3B(), .CLKOUT4(), .CLKOUT5(), .CLKOUT6(),
        .DCLK(1'b0), .DEN(1'b0), .DWE(1'b0), .DADDR(7'b0), .DI(16'b0), .DO(), .DRDY(),
        .PSCLK(1'b0), .PSEN(1'b0), .PSINCDEC(1'b0), .PSDONE(),
        .CDDCDONE(), .CDDCREQ(1'b0), .CLKINSTOPPED(), .CLKFBSTOPPED());
    (* DONT_TOUCH="TRUE" *) BUFG feedback_buffer(.I(feedback), .O(feedback_buffered));
endmodule

// Tiny normal-synthesis proxy for the real buffered MIG UI input.
module native_gmac_clock_probe(input wire ui_pad, cold_reset,
    output wire tx_source, tx_forward_source, delay_source, locked);
    wire ui_clock;
    (* DONT_TOUCH="TRUE" *) BUFG input_buffer(.I(ui_pad), .O(ui_clock));
    native_gmac_eth_clock clock_dut(.ui_clock(ui_clock), .cold_reset(cold_reset),
        .tx_source(tx_source), .tx_forward_source(tx_forward_source),
        .delay_source(delay_source), .locked(locked));
endmodule
