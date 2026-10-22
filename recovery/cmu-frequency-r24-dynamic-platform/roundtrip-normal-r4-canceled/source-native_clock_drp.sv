`timescale 1ns/1ps
`default_nettype none
// Bounded AON transaction engine for MMCME4_ADV, fixed D=10/M=40/VCO=1000MHz.
// Only CLKOUT0 O=20 (50MHz) and O=10 (100MHz) are encoded. This is NOT a
// software qualification whitelist. AMD XAPP888 v1.8 Tables 1,2,14,15 specify
// the addresses/masks below. M/D, bandwidth, lock/filter and fractional state
// never change. RMW retains all reserved bits; every write is read back.
module native_clock_drp #(
    parameter integer TIMEOUT_CYCLES = 1024,
    parameter integer RESET_CYCLES = 4,
    parameter integer DRAIN_CYCLES = 1024
) (
    input wire aon_clock, cold_reset,
    input wire gate_closed, isolated, clock_enable,
    input wire program_valid, output wire program_ready,
    input wire [31:0] program_hz, program_token,
    input wire program_fallback,
    output reg result_valid, input wire result_ready,
    output reg [31:0] result_hz, result_token,
    output reg result_error,
    output reg mmcm_reset, output reg fatal,
    output reg [6:0] drp_address,
    output reg [15:0] drp_data,
    output reg drp_enable, drp_write,
    input wire [15:0] drp_read_data, input wire drp_ready,
    output wire busy,
    output reg drp_outstanding=0
);
    localparam IDLE=0, RESET_WAIT=1, READ_ISSUE=2, READ_WAIT=3,
        WRITE_ISSUE=4, WRITE_WAIT=5, VERIFY_ISSUE=6, VERIFY_WAIT=7,
        DRAIN_WAIT=8, DRAIN_QUIET=9, FATAL=10, RESET_GUARD=11;
    reg [3:0] state;
    reg [31:0] timer, drain_total;
    reg [1:0] word_index;
    reg fast_rate, recovery_required, reset_drain;
    reg [15:0] write_value;
    wire legal = (program_hz == 32'd50000000 || program_hz == 32'd100000000) &&
        (!program_fallback || program_hz == 32'd50000000);
    assign busy = state != IDLE;
    assign program_ready = state == IDLE && !result_valid && !fatal &&
        gate_closed && isolated && !clock_enable && !drp_ready && !drp_outstanding;
    function [6:0] address;
        input [1:0] index;
        case(index)
            0: address=7'h27; // UltraScale/UltraScale+ power, NOT 7-series 0x28.
            1: address=7'h08;
            default: address=7'h09;
        endcase
    endfunction
    function [15:0] preserve;
        input [1:0] index;
        case(index)
            0: preserve=16'h0000;
            1: preserve=16'h1000;
            default: preserve=16'h8000;
        endcase
    endfunction
    function [15:0] setting;
        input [1:0] index;
        input fast;
        case(index)
            0: setting=16'hffff;
            1: setting=fast ? 16'h0145 : 16'h028a; // HIGH/LOW=5/5 or 10/10.
            default: setting=16'h0000; // integer, zero phase, MX=0, EDGE=0.
        endcase
    endfunction
    // FPGA configuration initializes this tracker; common cold reset MUST NOT
    // erase it because MMCM RST does not cancel an outstanding DRP transfer.
    always @(posedge aon_clock) begin
        if (drp_enable) drp_outstanding <= 1;
        if (drp_ready) drp_outstanding <= 0;
    end
    // A timed-out DEN is not canceled by deasserting DEN or resetting MMCM.
    // Do not let its late DRDY satisfy a fallback command. Drain it first;
    // if completion never arrives, fail closed; cold reset still retains the owner.
    task report_timeout;
        begin
            result_valid <= 1'b1; result_error <= 1'b1;
            recovery_required <= 1'b1; reset_drain<=0; mmcm_reset <= 1'b1;
            timer <= 0; drain_total <= 0; state <= DRAIN_WAIT;
        end
    endtask
    // A stretched/stuck response must return low before another DEN. If it
    // never does, transport quiet cannot be proved and fallback stays blocked.
    task report_not_quiet;
        begin
            result_valid<=1; result_error<=1; recovery_required<=1;
            reset_drain<=0; mmcm_reset<=1; timer<=0; drain_total<=0;
            state <= drp_outstanding && !drp_ready ? DRAIN_WAIT : DRAIN_QUIET;
        end
    endtask
    always @(posedge aon_clock or posedge cold_reset) begin
        if (cold_reset) begin
            state <= RESET_GUARD; timer <= 0; drain_total <= 0; word_index <= 0; fast_rate <= 0;
            recovery_required <= 0; reset_drain<=1; write_value <= 0;
            result_valid <= 0; result_hz <= 0; result_token <= 0; result_error <= 0;
            mmcm_reset <= 0; fatal <= 0;
            drp_address <= 0; drp_data <= 0; drp_enable <= 0; drp_write <= 0;
        end else begin
            drp_enable <= 0; drp_write <= 0;
            if (result_valid && result_ready) result_valid <= 0;
            case(state)
                RESET_GUARD: begin
                    timer<=0; drain_total<=0;
                    if (drp_ready) begin mmcm_reset<=1; state<=DRAIN_QUIET; end
                    else if (drp_outstanding) begin mmcm_reset<=1; state<=DRAIN_WAIT; end
                    else begin reset_drain<=0; state<=IDLE; end
                end
                IDLE: if (program_valid && program_ready) begin
                    result_hz <= program_hz; result_token <= program_token;
                    result_error <= 0;
                    if (!legal || (recovery_required && !program_fallback)) begin
                        result_valid <= 1; result_error <= 1;
                    end else begin
                        fast_rate <= program_hz == 32'd100000000;
                        mmcm_reset <= 1; word_index <= 0; timer <= 0; state <= RESET_WAIT;
                    end
                end
                RESET_WAIT: if (timer == RESET_CYCLES-1) begin
                    timer <= 0; state <= READ_ISSUE;
                end else timer <= timer + 1;
                READ_ISSUE: if (drp_ready || drp_outstanding) begin
                    if (timer == TIMEOUT_CYCLES-1) report_not_quiet();
                    else timer<=timer+1;
                end else begin
                    drp_address <= address(word_index); drp_enable <= 1;
                    timer <= 0; state <= READ_WAIT;
                end
                READ_WAIT: if (drp_ready) begin
                    write_value <= (drp_read_data & preserve(word_index)) | setting(word_index, fast_rate);
                    timer <= 0; state <= WRITE_ISSUE;
                end else if (timer == TIMEOUT_CYCLES-1) report_timeout();
                else timer <= timer + 1;
                WRITE_ISSUE: if (drp_ready || drp_outstanding) begin
                    if (timer == TIMEOUT_CYCLES-1) report_not_quiet();
                    else timer<=timer+1;
                end else begin
                    drp_address <= address(word_index); drp_data <= write_value;
                    drp_enable <= 1; drp_write <= 1; timer <= 0; state <= WRITE_WAIT;
                end
                WRITE_WAIT: if (drp_ready) begin
                    timer <= 0; state <= VERIFY_ISSUE;
                end else if (timer == TIMEOUT_CYCLES-1) report_timeout();
                else timer <= timer + 1;
                VERIFY_ISSUE: if (drp_ready || drp_outstanding) begin
                    if (timer == TIMEOUT_CYCLES-1) report_not_quiet();
                    else timer<=timer+1;
                end else begin
                    drp_address <= address(word_index); drp_enable <= 1;
                    timer <= 0; state <= VERIFY_WAIT;
                end
                VERIFY_WAIT: if (drp_ready) begin
                    if (drp_read_data !== write_value) begin
                        result_valid <= 1; result_error <= 1; recovery_required <= 1;
                        // This operation completed, so fallback may start after result consumption.
                        state <= IDLE;
                    end else if (word_index == 2) begin
                        mmcm_reset <= 0; recovery_required <= 0;
                        result_valid <= 1; result_error <= 0; state <= IDLE;
                    end else begin
                        word_index <= word_index + 1; state <= READ_ISSUE;
                    end
                    timer <= 0;
                end else if (timer == TIMEOUT_CYCLES-1) report_timeout();
                else timer <= timer + 1;
                DRAIN_WAIT: if (drp_ready) begin
                    timer <= 0; state <= DRAIN_QUIET;
                end else if (timer == DRAIN_CYCLES-1) begin
                    fatal <= 1; state <= FATAL;
                end else timer <= timer + 1;
                DRAIN_QUIET: if (drp_ready) timer <= 0;
                else if (timer == 3) begin
                    timer <= 0; state <= IDLE;
                    if (reset_drain) begin
                        // Old transaction drained. Ungated source must run to
                        // establish a fresh post-cold-reset close witness.
                        mmcm_reset<=0; reset_drain<=0; recovery_required<=0;
                    end
                end
                else timer <= timer + 1;
                default: begin fatal <= 1; mmcm_reset <= 1; state <= FATAL; end
            endcase
            if (state == DRAIN_WAIT || state == DRAIN_QUIET) begin
                drain_total <= drain_total + 1;
                if (drain_total == DRAIN_CYCLES-1) begin
                    fatal<=1; mmcm_reset<=1; state<=FATAL;
                end
            end
        end
    end
endmodule
`default_nettype wire
