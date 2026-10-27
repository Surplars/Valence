`timescale 1ns/1ps
// OFFLINE CANDIDATE: not included in production source lists or instantiated.
// UG571 v1.16, Cascading Delays: IDELAY MASTER -> ODELAY SLAVE_END in one IOB.
// Requires proof of the matching free ODELAY and dedicated cascade legality.
// TIME cascades in one IOB require equal DELAY_VALUE, including zero.
// Total physical delay includes intrinsic insertion; it is NOT 2*STAGE_DELAY_PS.
module native_rx_cascaded_input_delay #(
    // Deliberately no usable default: choose only after native corner analysis.
    parameter integer STAGE_DELAY_PS = -1
)(
    input wire pad_data,
    input wire delay_reset,
    output wire delayed_data
);
    initial begin
        if (STAGE_DELAY_PS < 0 || STAGE_DELAY_PS > 1100)
            $fatal(1, "RX cascade requires an explicit stage delay in 0..1100 ps");
    end
    wire cascade, returned;
    // Shares the existing VALENCE_RGMII IDELAYCTRL at 500 MHz. The caller must
    // retain its reset/RDY qualification; this module does not create a controller.
    (* IODELAY_GROUP = "VALENCE_RGMII" *)
    IDELAYE3 #(
        .CASCADE("MASTER"), .DELAY_SRC("IDATAIN"), .DELAY_FORMAT("TIME"),
        .DELAY_TYPE("FIXED"), .DELAY_VALUE(STAGE_DELAY_PS),
        .REFCLK_FREQUENCY(500.0), .SIM_DEVICE("ULTRASCALE_PLUS")
    ) master (
        .IDATAIN(pad_data), .DATAIN(1'b0), .DATAOUT(delayed_data),
        .CASC_IN(1'b0), .CASC_OUT(cascade), .CASC_RETURN(returned),
        .CLK(1'b0), .CE(1'b0), .INC(1'b0), .LOAD(1'b0),
        .CNTVALUEIN(9'b0), .CNTVALUEOUT(), .RST(delay_reset), .EN_VTC(1'b1)
    );
    (* IODELAY_GROUP = "VALENCE_RGMII" *)
    ODELAYE3 #(
        .CASCADE("SLAVE_END"), .DELAY_FORMAT("TIME"), .DELAY_TYPE("FIXED"),
        .DELAY_VALUE(STAGE_DELAY_PS), .REFCLK_FREQUENCY(500.0),
        .SIM_DEVICE("ULTRASCALE_PLUS")
    ) slave (
        .ODATAIN(1'b0), .DATAOUT(returned),
        .CASC_IN(cascade), .CASC_OUT(), .CASC_RETURN(1'b0),
        .CLK(1'b0), .CE(1'b0), .INC(1'b0), .LOAD(1'b0),
        .CNTVALUEIN(9'b0), .CNTVALUEOUT(), .RST(delay_reset), .EN_VTC(1'b1)
    );
endmodule
