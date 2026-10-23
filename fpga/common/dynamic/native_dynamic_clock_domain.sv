`timescale 1ns/1ps
`default_nettype none
// Physical UltraScale+ domain. Stable AON and DDR UI clocks are external;
// reconfiguration reset touches ONLY this MMCME4, never retained owners.
module native_dynamic_clock_domain #(
    parameter integer DRP_TIMEOUT_CYCLES=1024,
    parameter integer DRP_DRAIN_CYCLES=1024,
    parameter integer LOCK_STABLE_CYCLES=8,
    parameter integer MAX_PROGRAM_HZ=300000000
) (
    input wire aon_clock, common_cold_reset, source_clock250,
    input wire clock_enable, isolate,
    input wire program_valid, output wire program_ready,
    input wire [31:0] program_hz, program_token,
    input wire [23:0] program_parameters,
    input wire program_fallback,
    output wire result_valid, input wire result_ready,
    output wire [31:0] result_hz, result_token,
    output wire result_error,
    output wire managed_clock, present, gate_closed, gate_open, locked, resumed,
    output wire fatal
);
    (* ASYNC_REG="TRUE" *) reg [2:0] aon_reset_pipe;
    always @(posedge aon_clock or posedge common_cold_reset)
        if (common_cold_reset) aon_reset_pipe<=3'b111;
        else aon_reset_pipe<={aon_reset_pipe[1:0],1'b0};
    wire aon_reset=aon_reset_pipe[2];
    wire raw_mmcm, raw_clock, feedback, feedback_buffered;
    wire primitive_locked, program_reset, drp_fatal, busy;
    // Explicit no-load sinks for unused primitive outputs; no control/clock fanout.
    wire [14:0] unused_mmcm_outputs;
    wire [6:0] address;
    wire [15:0] write_data, read_data;
    wire den,dwe,drdy,ce,drp_outstanding;
    reg boot_configured, boot_sent, boot_failed;
    wire internal_ready, internal_result_valid, internal_result_error;
    wire [31:0] internal_result_hz, internal_result_token;
    // MMCM RST does not restore DRP values. Every cold start explicitly writes
    // M40/D10/O20 and LOW lock/filter before advertising boot50.
    always @(posedge aon_clock or posedge aon_reset) begin
        if (aon_reset) begin boot_configured<=0; boot_sent<=0; boot_failed<=0; end
        else if (!boot_configured && !boot_failed) begin
            if (!boot_sent && internal_ready) boot_sent<=1;
            if (boot_sent && internal_result_valid) begin
                if (internal_result_error) boot_failed<=1;
                else boot_configured<=1;
            end
        end
    end
    assign program_ready=boot_configured && internal_ready;
    assign result_valid=boot_configured && internal_result_valid;
    assign result_error=internal_result_error;
    assign result_hz=internal_result_hz;
    assign result_token=internal_result_token;
    wire mmcm_reset=common_cold_reset | program_reset | drp_outstanding;
    // The local feasibility receipt validated D10/M40/O20 and O10 on the exact
    // xczu15eg-ffvb1156-2-i part. It did NOT validate this DRP implementation.
    MMCME4_ADV #(
        .BANDWIDTH("LOW"), .CLKIN1_PERIOD(4.000),
        .DIVCLK_DIVIDE(10), .CLKFBOUT_MULT_F(40.000),
        .CLKOUT0_DIVIDE_F(20.000), .CLKOUT0_DUTY_CYCLE(0.500),
        .CLKOUT0_PHASE(0.000), .CLKOUT0_USE_FINE_PS("FALSE"),
        .CLKFBOUT_USE_FINE_PS("FALSE"), .COMPENSATION("AUTO"),
        .STARTUP_WAIT("FALSE")
    ) mmcm (
        .CLKIN1(source_clock250), .CLKIN2(1'b0), .CLKINSEL(1'b1),
        .CLKFBIN(feedback_buffered), .CLKFBOUT(feedback), .CLKOUT0(raw_mmcm),
        .RST(mmcm_reset), .PWRDWN(1'b0), .LOCKED(primitive_locked),
        .DCLK(aon_clock), .DADDR(address), .DI(write_data), .DEN(den), .DWE(dwe),
        .DO(read_data), .DRDY(drdy),
        .PSCLK(1'b0), .PSEN(1'b0), .PSINCDEC(1'b0),
        .CDDCREQ(1'b0),
        .CDDCDONE(unused_mmcm_outputs[0]), .CLKFBOUTB(unused_mmcm_outputs[1]),
        .CLKFBSTOPPED(unused_mmcm_outputs[2]), .CLKINSTOPPED(unused_mmcm_outputs[3]),
        .CLKOUT0B(unused_mmcm_outputs[4]), .CLKOUT1(unused_mmcm_outputs[5]),
        .CLKOUT1B(unused_mmcm_outputs[6]), .CLKOUT2(unused_mmcm_outputs[7]),
        .CLKOUT2B(unused_mmcm_outputs[8]), .CLKOUT3(unused_mmcm_outputs[9]),
        .CLKOUT3B(unused_mmcm_outputs[10]), .CLKOUT4(unused_mmcm_outputs[11]),
        .CLKOUT5(unused_mmcm_outputs[12]), .CLKOUT6(unused_mmcm_outputs[13]),
        .PSDONE(unused_mmcm_outputs[14])
    );
    BUFG feedback_buffer(.I(feedback), .O(feedback_buffered));
    BUFG observer_buffer(.I(raw_mmcm), .O(raw_clock));
    BUFGCE #(.CE_TYPE("SYNC"), .SIM_DEVICE("ULTRASCALE_PLUS")) managed_buffer(
        .I(raw_mmcm), .CE(ce), .O(managed_clock));
    (* ASYNC_REG="TRUE" *) reg [2:0] lock_sync;
    reg [31:0] lock_count;
    reg stable_lock, unexpected_unlock, ever_running;
    always @(posedge aon_clock or posedge aon_reset) begin
        if (aon_reset) begin
            lock_sync<=0; lock_count<=0; stable_lock<=0;
            unexpected_unlock<=0; ever_running<=0;
        end else begin
            lock_sync <= {lock_sync[1:0],primitive_locked};
            if (program_reset || !lock_sync[2]) begin lock_count<=0; stable_lock<=0; end
            else if (lock_count == LOCK_STABLE_CYCLES-1) stable_lock<=1;
            else lock_count<=lock_count+1;
            if (gate_open && stable_lock) ever_running<=1;
            // Expected unlock occurs only after the real close acknowledgement.
            if (ever_running && !lock_sync[2] && !program_reset && !gate_closed)
                unexpected_unlock<=1;
        end
    end
    assign fatal = drp_fatal | unexpected_unlock | boot_failed;
    assign present = 1'b1;
    assign locked = boot_configured && stable_lock && !program_reset && !fatal;
    wire permitted_enable = clock_enable && boot_configured && stable_lock && !fatal && !program_reset;
    native_clock_gate gate (
        .aon_clock(aon_clock), .cold_reset(aon_reset),
        .raw_clock(raw_clock), .managed_clock(managed_clock), .enable(permitted_enable),
        .gate_ce(ce), .gate_closed(gate_closed), .gate_open(gate_open), .resumed(resumed));
    native_clock_drp #(.TIMEOUT_CYCLES(DRP_TIMEOUT_CYCLES), .DRAIN_CYCLES(DRP_DRAIN_CYCLES),
        .MAX_PROGRAM_HZ(MAX_PROGRAM_HZ)) programmer (
        .aon_clock(aon_clock), .cold_reset(aon_reset),
        .gate_closed(gate_closed), .isolated(!boot_configured || isolate),
        .clock_enable((boot_configured && clock_enable) | unexpected_unlock | boot_failed),
        .program_valid(boot_configured ? program_valid : !boot_sent && !boot_failed),
        .program_ready(internal_ready),
        .program_hz(boot_configured ? program_hz : 32'd50000000),
        .program_token(boot_configured ? program_token : 32'd0),
        .program_parameters(boot_configured ? program_parameters : 24'h14280a),
        .program_fallback(boot_configured ? program_fallback : 1'b1),
        .result_valid(internal_result_valid), .result_ready(!boot_configured || result_ready),
        .result_hz(internal_result_hz), .result_token(internal_result_token),
        .result_error(internal_result_error),
        .mmcm_reset(program_reset), .fatal(drp_fatal),
        .drp_address(address), .drp_data(write_data), .drp_enable(den), .drp_write(dwe),
        .drp_read_data(read_data), .drp_ready(drdy), .busy(busy), .drp_outstanding(drp_outstanding));
endmodule
`default_nettype wire
