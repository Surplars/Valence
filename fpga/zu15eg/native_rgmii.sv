`timescale 1ns/1ps
// 1 Gb/s/full duplex. Legacy mode needs PHY TXDLY; FPGA-centered modes need
// software-verified TXDLY=0/RXDLY=1. Never add the delay at both ends.
// RAW clocks and pad DDRs run continuously even when managed MAC clocks stop.
module native_rgmii #(
    // Candidate-only: a phase-aligned, always-on pad tree from the same PLL.
    // Default keeps the established single-tree board interface unchanged.
    parameter ISOLATE_TX_PAD_CLOCK = 0,
    parameter FPGA_TX_CLOCK_SHIFT = 0,
    parameter TX_CALIBRATED_CLOCK = 0,
    // Optional dedicated ODDR250 mode. Raw MAC remains byte-wide at 125MHz.
    parameter TX_QUARTER_DDR = 0,
    parameter RX_DATA_DELAY_PS = 1100
) (
    input wire tx_clock, rx_clock, tx_reset, rx_reset,
    input wire tx_pad_clock,
    input wire tx_forward_clock, tx_forward_reset,
    input wire delay_clock, delay_reset,
    output wire delay_ready,
    input wire [7:0] gmii_tx_data,
    input wire gmii_tx_enable, gmii_tx_error,
    input wire [3:0] rgmii_rx_data,
    input wire rgmii_rx_control,
    output wire [3:0] rgmii_tx_data,
    output wire rgmii_tx_control, rgmii_tx_clock,
    output reg [7:0] gmii_rx_data,
    output reg gmii_rx_valid, gmii_rx_error,
    output reg gigabit_link
);
    // Keep raw-domain transfer to pad DDR local. All lanes/control share latency.
    reg [7:0] tx_data;
    reg tx_enable, tx_fall_control;
    always @(posedge tx_clock or posedge tx_reset)
        if (tx_reset) begin tx_data <= 0; tx_enable <= 0; tx_fall_control <= 0; end
        else begin
            tx_data <= gmii_tx_data;
            tx_enable <= gmii_tx_enable;
            // Register both DDR control symbols. No XOR after the pad stage.
            tx_fall_control <= gmii_tx_enable ^ gmii_tx_error;
        end
    wire tx_ddr_clock = (ISOLATE_TX_PAD_CLOCK || TX_QUARTER_DDR) ? tx_pad_clock : tx_clock;
    wire tx_output_reset = TX_QUARTER_DDR ? tx_forward_reset : tx_reset;
    wire quarter_phase;
    wire [4:0] quarter_low, quarter_high;
    generate if(TX_QUARTER_DDR) begin: quarter_tx_boundary
        // Start after a shared word-clock reset release. The first CLK250
        // edge at raw+4 ends the idle high half; steady low begins at raw+0.
        reg phase_high;
        always @(posedge tx_pad_clock or posedge tx_output_reset)
            if(tx_output_reset) phase_high<=1'b1;
            else phase_high<=~phase_high;
        wire capture_word=~phase_high;
        reg [4:0] pad_low, pad_high;
        always @(negedge tx_pad_clock or posedge tx_output_reset)
            if(tx_output_reset) begin pad_low<=0; pad_high<=0; end
            else if(capture_word) begin
                // Capture only at raw+6, after the old high symbol and
                // before the next low. No mixed-byte halves, still II=1.
                pad_low<={tx_enable,tx_data[3:0]};
                pad_high<={tx_fall_control,tx_data[7:4]};
            end
        assign quarter_phase=phase_high;
        assign quarter_low=pad_low;
        assign quarter_high=pad_high;
    end else begin: ordinary_tx_boundary
        assign quarter_phase=1'b0;
        assign quarter_low=5'b0;
        assign quarter_high=5'b0;
    end endgenerate
    wire [4:0] quarter_symbol=quarter_phase ? quarter_high : quarter_low;
    wire tx_clock_raw;
    ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS")) tx_clock_ddr (
        .C(TX_QUARTER_DDR ? tx_ddr_clock : ((FPGA_TX_CLOCK_SHIFT && !TX_CALIBRATED_CLOCK) ? tx_forward_clock : tx_ddr_clock)),
        .D1(TX_QUARTER_DDR ? quarter_phase : 1'b1), .D2(TX_QUARTER_DDR ? ~quarter_phase : 1'b0),
        .SR((TX_QUARTER_DDR || (FPGA_TX_CLOCK_SHIFT && !TX_CALIBRATED_CLOCK)) ? tx_forward_reset : tx_reset), .Q(tx_clock_raw));
    generate if(TX_CALIBRATED_CLOCK) begin: calibrated_tx_clock
        native_tx_output_delay clock_delay(.symbol(tx_clock_raw), .delay_reset(delay_reset),
            .delayed_symbol(rgmii_tx_clock));
    end else begin: direct_tx_clock
        assign rgmii_tx_clock=tx_clock_raw;
    end endgenerate
    ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS")) tx_control_ddr (
        .C(tx_ddr_clock), .D1(TX_QUARTER_DDR ? quarter_symbol[4] : tx_enable),
        .D2(TX_QUARTER_DDR ? quarter_symbol[4] : tx_fall_control), .SR(tx_output_reset), .Q(rgmii_tx_control));
    genvar lane;
    for (lane=0; lane<4; lane=lane+1) begin: lanes
        ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS")) tx_ddr (
            .C(tx_ddr_clock), .D1(TX_QUARTER_DDR ? quarter_symbol[lane] : tx_data[lane]),
            .D2(TX_QUARTER_DDR ? quarter_symbol[lane] : tx_data[lane+4]), .SR(tx_output_reset), .Q(rgmii_tx_data[lane]));
    end
    wire [7:0] rx_data;
    wire rx_dv, rx_fall_ctl;
    // Calibrated data delay compensates the raw BUFG capture insertion. Never
    // gate REFCLK with CMU; keep RX in reset until calibration is ready.
    (* IODELAY_GROUP="VALENCE_RGMII" *)
    IDELAYCTRL #(.SIM_DEVICE("ULTRASCALE")) delay_control (
        .REFCLK(delay_clock), .RST(delay_reset), .RDY(delay_ready));
    wire [4:0] delayed_rx;
    wire [4:0] rx_pad_data = {rgmii_rx_control,rgmii_rx_data};
    for (lane=0; lane<5; lane=lane+1) begin: receive_delay
        (* IODELAY_GROUP="VALENCE_RGMII" *)
        IDELAYE3 #(.DELAY_FORMAT("TIME"), .DELAY_TYPE("FIXED"), .DELAY_SRC("IDATAIN"),
            // Installed 2025.1 UNISIM enforces <=1100ps for this device/refclk.
            .DELAY_VALUE(RX_DATA_DELAY_PS), .REFCLK_FREQUENCY(500.0), .SIM_DEVICE("ULTRASCALE_PLUS")) data_delay (
            .IDATAIN(rx_pad_data[lane]), .DATAIN(1'b0),
            // UG571: CLK is unused in FIXED mode. REFCLK remains 500MHz on
            // IDELAYCTRL; do not clock the slower dynamic-control port with it.
            .DATAOUT(delayed_rx[lane]), .CLK(1'b0), .CE(1'b0), .INC(1'b0),
            .LOAD(1'b0), .CNTVALUEIN(9'b0), .CNTVALUEOUT(), .RST(delay_reset), .EN_VTC(1'b1),
            .CASC_IN(1'b0), .CASC_RETURN(1'b0), .CASC_OUT());
    end
    for (lane=0; lane<4; lane=lane+1) begin: receive
        IDDRE1 #(.DDR_CLK_EDGE("SAME_EDGE_PIPELINED"), .IS_CB_INVERTED(1'b1)) rx_ddr (
            .C(rx_clock), .CB(rx_clock), .D(delayed_rx[lane]), .R(rx_reset),
            .Q1(rx_data[lane]), .Q2(rx_data[lane+4]));
    end
    IDDRE1 #(.DDR_CLK_EDGE("SAME_EDGE_PIPELINED"), .IS_CB_INVERTED(1'b1)) rx_control_ddr (
        .C(rx_clock), .CB(rx_clock), .D(delayed_rx[4]), .R(rx_reset), .Q1(rx_dv), .Q2(rx_fall_ctl));
    // Idle in-band status is captured only when DV=0 and RX_ER=0. Reject
    // 10/100 and half duplex; these frame engines are not nibble repeaters.
    reg [3:0] status;
    always @(posedge rx_clock or posedge rx_reset)
        if (rx_reset) begin
            gmii_rx_data <= 0; gmii_rx_valid <= 0; gmii_rx_error <= 0; status <= 0; gigabit_link <= 0;
        end else begin
            if (!rx_dv && !rx_fall_ctl) status <= rx_data[3:0];
            gigabit_link <= status[0] && status[3] && status[2:1] == 2'b10;
            gmii_rx_data <= rx_data;
            gmii_rx_valid <= rx_dv && gigabit_link;
            gmii_rx_error <= (rx_dv ^ rx_fall_ctl) && gigabit_link;
        end
endmodule
