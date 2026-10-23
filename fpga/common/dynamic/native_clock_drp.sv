`timescale 1ns/1ps
`default_nettype none
// Bounded AON MMCME4_ADV engine. Software supplies integer {O,M,D}; hardware
// accepts only D10, M32..62 (800..1550MHz VCO), O3..128, and the EXACT target.
// Input250/PFD25MHz. LOW-bandwidth lock/filter characterization is derived from
// AMD embeddedsw xvphy_mmcme4.c; see software-parameters.json for pinned source.
// No arbitrary address/data interface. Reserved bits are retained by RMW and
// every full word is read back. Owner reset is never derived from MMCM reset.
module native_clock_drp #(
    parameter integer TIMEOUT_CYCLES = 1024,
    parameter integer RESET_CYCLES = 4,
    parameter integer DRAIN_CYCLES = 1024,
    parameter integer MAX_PROGRAM_HZ = 300000000
) (
    input wire aon_clock, cold_reset,
    input wire gate_closed, isolated, clock_enable,
    input wire program_valid, output wire program_ready,
    input wire [31:0] program_hz, program_token,
    input wire [23:0] program_parameters,
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
        DRAIN_WAIT=8, DRAIN_QUIET=9, FATAL=10, RESET_GUARD=11, VALIDATE_M=12, VALIDATE_O=13;
    reg [3:0] state;
    reg [31:0] timer, drain_total;
    reg [3:0] word_index;
    reg recovery_required, reset_drain;
    reg [7:0] multiplier, divider, validation_count;
    // Max product is 300MHz*128 < 2^36. A 40-bit difference cannot wrap to
    // zero for any admitted operands. Serial arithmetic avoids wide multipliers.
    reg [39:0] validation_difference;
    reg [15:0] write_value;
    // M63/64 are deliberately rejected: AMD driver characterization disagrees
    // with Vivado2025.2 CP validation there. No guessed analog correction.
    wire legal_shape = program_fallback ? program_hz == 32'd50000000 :
        program_parameters[7:0] == 8'd10 &&
        program_parameters[15:8] >= 8'd32 && program_parameters[15:8] <= 8'd62 &&
        program_parameters[23:16] >= 8'd3 && program_parameters[23:16] <= 8'd128 &&
        program_hz >= 32'd10000000 && program_hz <= MAX_PROGRAM_HZ;
    assign busy = state != IDLE;
    assign program_ready = state == IDLE && !result_valid && !fatal &&
        gate_closed && isolated && !clock_enable && !drp_ready && !drp_outstanding;
    function [6:0] address;
        input [3:0] index;
        case(index)
            0: address=7'h27; // UltraScale/UltraScale+ power, not 7-series 0x28.
            1: address=7'h14;
            2: address=7'h15;
            3: address=7'h16;
            4: address=7'h08;
            5: address=7'h09;
            6: address=7'h18;
            7: address=7'h19;
            8: address=7'h1a;
            9: address=7'h4e;
            default: address=7'h4f;
        endcase
    endfunction
    function [15:0] preserve;
        input [3:0] index;
        case(index)
            0: preserve=16'h0000;
            1,4: preserve=16'h1000;
            3: preserve=16'hc000;
            6: preserve=16'hfc00;
            9: preserve=16'h66ff;
            10: preserve=16'h666f;
            default: preserve=16'h8000;
        endcase
    endfunction
    function [15:0] counts;
        input [7:0] divide;
        reg [5:0] hi,lo;
        begin
            hi=divide >> 1; lo=(divide >> 1)+divide[0];
            // Counter64 is represented by six zero bits, including O128.
            counts={4'b0000,hi,lo};
        end
    endfunction
    function [15:0] setting;
        input [3:0] index;
        input [7:0] m,o;
        case(index)
            0: setting=16'hffff;
            1: setting=counts(m);
            2: setting=m[0] ? 16'h0080 : 16'h0000;
            3: setting=16'h0145; // DIVCLK10: HIGH5/LOW5, EDGE=0.
            4: setting=counts(o);
            5: setting=o[0] ? 16'h0080 : 16'h0000;
            6: setting=m<=33 ? 16'h012c : m<=36 ? 16'h0113 : 16'h00fa;
            7: setting=16'h7c01;
            8: setting=16'h7fe9;
            9: setting=m>=38 && m<=41 ? 16'h9800 : 16'h9900;
            default: setting=m<=37 ? 16'h9090 : 16'h0890;
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
            state <= RESET_GUARD; timer <= 0; drain_total <= 0; word_index <= 0;
            multiplier<=40; divider<=20; validation_count<=0; validation_difference<=0;
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
                    if (!legal_shape || (recovery_required && !program_fallback)) begin
                        result_valid <= 1; result_error <= 1;
                    end else begin
                        multiplier <= program_fallback ? 8'd40 : program_parameters[15:8];
                        divider <= program_fallback ? 8'd20 : program_parameters[23:16];
                        validation_count <= program_fallback ? 8'd40 : program_parameters[15:8];
                        validation_difference<=0; state<=VALIDATE_M;
                    end
                end
                VALIDATE_M: begin
                    validation_difference<=validation_difference+40'd25000000;
                    validation_count<=validation_count-1'b1;
                    if(validation_count==1) begin validation_count<=divider; state<=VALIDATE_O; end
                end
                VALIDATE_O: begin
                    validation_difference<=validation_difference-{8'b0,result_hz};
                    validation_count<=validation_count-1'b1;
                    if(validation_count==1) begin
                        if(validation_difference!={8'b0,result_hz}) begin
                            result_valid<=1; result_error<=1; state<=IDLE;
                        end else begin
                            mmcm_reset<=1; word_index<=0; timer<=0; state<=RESET_WAIT;
                        end
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
                    write_value <= (drp_read_data & preserve(word_index)) | setting(word_index, multiplier, divider);
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
                    end else if (word_index == 10) begin
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
