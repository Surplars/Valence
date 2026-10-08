// SPDX-License-Identifier: Apache-2.0
// JTAG DTM transport reservation, not a RISC-V Debug Module or boundary-scan implementation.
// See docs/debug/jtag-reservation.md for the reset/CDC and physical integration contracts.
`default_nettype none

module ValenceJtagTap #(
    parameter [31:0] IDCODE = 32'h00000001,
    parameter integer ABITS = 7
) (
    input wire tck, input wire tms, input wire tdi, input wire reset_n,
    output reg tdo, output reg tdo_oe,
    input wire [31:0] dtmcs_capture,
    input wire [ABITS+33:0] dmi_capture,
    output wire capture_dr, output wire update_dr, output wire tap_reset,
    output reg [4:0] instruction,
    output reg [ABITS+33:0] dr_shift
);
    localparam [3:0] TLR=0, IDLE=1, SELECT_DR=2, CAPTURE_DR=3, SHIFT_DR=4,
        EXIT1_DR=5, PAUSE_DR=6, EXIT2_DR=7, UPDATE_DR=8, SELECT_IR=9,
        CAPTURE_IR=10, SHIFT_IR=11, EXIT1_IR=12, PAUSE_IR=13, EXIT2_IR=14, UPDATE_IR=15;
    reg [3:0] state, next_state;
    reg [4:0] ir_shift;
    assign capture_dr = state == CAPTURE_DR;
    assign update_dr = state == UPDATE_DR;
    assign tap_reset = state == TLR;
    always @* begin
        case (state)
            TLR:        next_state = tms ? TLR : IDLE;
            IDLE:       next_state = tms ? SELECT_DR : IDLE;
            SELECT_DR:  next_state = tms ? SELECT_IR : CAPTURE_DR;
            CAPTURE_DR: next_state = tms ? EXIT1_DR : SHIFT_DR;
            SHIFT_DR:   next_state = tms ? EXIT1_DR : SHIFT_DR;
            EXIT1_DR:   next_state = tms ? UPDATE_DR : PAUSE_DR;
            PAUSE_DR:   next_state = tms ? EXIT2_DR : PAUSE_DR;
            EXIT2_DR:   next_state = tms ? UPDATE_DR : SHIFT_DR;
            UPDATE_DR:  next_state = tms ? SELECT_DR : IDLE;
            SELECT_IR:  next_state = tms ? TLR : CAPTURE_IR;
            CAPTURE_IR: next_state = tms ? EXIT1_IR : SHIFT_IR;
            SHIFT_IR:   next_state = tms ? EXIT1_IR : SHIFT_IR;
            EXIT1_IR:   next_state = tms ? UPDATE_IR : PAUSE_IR;
            PAUSE_IR:   next_state = tms ? EXIT2_IR : PAUSE_IR;
            EXIT2_IR:   next_state = tms ? UPDATE_IR : SHIFT_IR;
            UPDATE_IR:  next_state = tms ? SELECT_DR : IDLE;
            default:    next_state = TLR;
        endcase
    end
    always @(posedge tck or negedge reset_n) begin
        if (!reset_n) begin
            state <= TLR;
            ir_shift <= 5'b00001;
            dr_shift <= 0;
        end else begin
            state <= next_state;
            if (state == CAPTURE_IR) ir_shift <= 5'b00001;
            else if (state == SHIFT_IR) ir_shift <= {tdi, ir_shift[4:1]};
            if (state == CAPTURE_DR) begin
                case (instruction)
                    5'h01: dr_shift <= {{(ABITS+2){1'b0}}, IDCODE};
                    5'h10: dr_shift <= {{(ABITS+2){1'b0}}, dtmcs_capture};
                    5'h11: dr_shift <= dmi_capture;
                    default: dr_shift <= 0;
                endcase
            end else if (state == SHIFT_DR) begin
                case (instruction)
                    5'h01, 5'h10: dr_shift <= {{(ABITS+2){1'b0}}, tdi, dr_shift[31:1]};
                    5'h11: dr_shift <= {tdi, dr_shift[ABITS+33:1]};
                    default: dr_shift <= {{(ABITS+33){1'b0}}, tdi};
                endcase
            end
        end
    end
    // Instruction update and TDO change on the falling edge. First output bit is
    // the captured LSB, sampled BEFORE the next rising-edge shift by the adapter.
    always @(negedge tck or negedge reset_n) begin
        if (!reset_n) begin
            instruction <= 5'h01;
            tdo <= 0;
            tdo_oe <= 0;
        end else begin
            if (state == TLR) instruction <= 5'h01;
            else if (state == UPDATE_IR) instruction <= ir_shift;
            tdo_oe <= state == SHIFT_IR || state == SHIFT_DR;
            tdo <= state == SHIFT_IR ? ir_shift[0] : state == SHIFT_DR ? dr_shift[0] : 1'b0;
        end
    end
endmodule

// Capacity-one bundled-data mailbox. Both sides asynchronously reset together;
// release is synchronized independently. Payload registers are held through the
// complete request/response round trip, never bit-wise synchronized. ASYNC_REG
// plus scoped max-delay constraints are required for physical implementation.
module ValenceDmiCdc #(parameter integer ABITS = 7) (
    input wire tck, input wire debug_clk, input wire reset_n,
    input wire s_req_valid, output wire s_req_ready,
    input wire [ABITS+33:0] s_req_payload,
    output reg s_rsp_valid, output reg [33:0] s_rsp_payload,
    input wire s_rsp_ready, output wire s_busy,
    output wire dmi_reset_n,
    output wire d_req_valid, input wire d_req_ready,
    output wire [ABITS+33:0] d_req_payload,
    input wire d_rsp_valid, output wire d_rsp_ready,
    input wire [33:0] d_rsp_payload
);
    (* ASYNC_REG = "TRUE" *) reg [2:0] source_release, dest_release;
    always @(negedge tck or negedge reset_n)
        if (!reset_n) source_release <= 0; else source_release <= {source_release[1:0], 1'b1};
    always @(posedge debug_clk or negedge reset_n)
        if (!reset_n) dest_release <= 0; else dest_release <= {dest_release[1:0], 1'b1};
    wire source_reset_n = source_release[2];
    assign dmi_reset_n = dest_release[2];
    reg [ABITS+33:0] request_held;
    reg [33:0] response_held;
    reg request_toggle, response_toggle;
    (* ASYNC_REG = "TRUE" *) reg [1:0] request_sync, response_sync;
    reg source_busy, response_seen, request_seen, dest_valid, dest_waiting;
    reg [ABITS+33:0] dest_request;
    assign s_req_ready = source_reset_n && !source_busy;
    assign s_busy = source_busy || !source_reset_n;
    assign d_req_valid = dest_valid && dmi_reset_n;
    assign d_req_payload = dest_request;
    assign d_rsp_ready = dest_waiting && dmi_reset_n;
    always @(negedge tck or negedge source_reset_n) begin
        if (!source_reset_n) begin
            request_held <= 0; request_toggle <= 0; response_sync <= 0;
            source_busy <= 0; response_seen <= 0; s_rsp_valid <= 0; s_rsp_payload <= 0;
        end else begin
            response_sync <= {response_sync[0], response_toggle};
            if (s_req_valid && s_req_ready) begin
                request_held <= s_req_payload;
                request_toggle <= !request_toggle;
                source_busy <= 1;
            end
            if (source_busy && !s_rsp_valid && response_sync[1] != response_seen) begin
                s_rsp_payload <= response_held;
                response_seen <= response_sync[1];
                s_rsp_valid <= 1;
            end
            if (s_rsp_valid && s_rsp_ready) begin
                s_rsp_valid <= 0;
                source_busy <= 0;
            end
        end
    end
    always @(posedge debug_clk or negedge dmi_reset_n) begin
        if (!dmi_reset_n) begin
            response_held <= 0; response_toggle <= 0; request_sync <= 0;
            request_seen <= 0; dest_valid <= 0; dest_waiting <= 0; dest_request <= 0;
        end else begin
            request_sync <= {request_sync[0], request_toggle};
            if (!dest_valid && !dest_waiting && request_sync[1] != request_seen) begin
                dest_request <= request_held;
                request_seen <= request_sync[1];
                dest_valid <= 1;
            end
            if (d_req_valid && d_req_ready) begin dest_valid <= 0; dest_waiting <= 1; end
            if (d_rsp_valid && d_rsp_ready) begin
                response_held <= d_rsp_payload;
                response_toggle <= !response_toggle;
                dest_waiting <= 0;
            end
        end
    end
endmodule

// A reservation fails every access, including dmstatus and dmcontrol. It does not
// advertise a hart or imply that halt/resume/abstract access worked.
module ValenceDmiUnavailable (
    input wire debug_clk, input wire reset_n,
    input wire req_valid, output wire req_ready,
    output reg rsp_valid, input wire rsp_ready,
    output wire [1:0] rsp_status, output wire [31:0] rsp_data
);
    assign req_ready = reset_n && !rsp_valid;
    assign rsp_status = 2'b10;
    assign rsp_data = 0;
    always @(posedge debug_clk or negedge reset_n)
        if (!reset_n) rsp_valid <= 0;
        else begin
            if (req_valid && req_ready) rsp_valid <= 1;
            if (rsp_valid && rsp_ready) rsp_valid <= 0;
        end
endmodule

module ValenceJtagDebugPort #(
    parameter integer ENABLE = 0,
    parameter integer EXTERNAL_DMI = 0,
    parameter integer ABITS = 7,
    parameter [31:0] IDCODE = 32'h00000001,
    parameter [2:0] IDLE_HINT = 3'd7
) (
    input wire tck, input wire tms, input wire tdi, input wire trst_n,
    input wire debug_clk, input wire debug_por_n,
    output wire tdo, output wire tdo_oe,
    output wire dmi_reset_n,
    output wire dmi_req_valid, input wire dmi_req_ready,
    output wire [1:0] dmi_req_op,
    output wire [ABITS-1:0] dmi_req_address,
    output wire [31:0] dmi_req_data,
    input wire dmi_rsp_valid, output wire dmi_rsp_ready,
    input wire [1:0] dmi_rsp_status, input wire [31:0] dmi_rsp_data
);
    generate if (ENABLE == 0) begin: disabled
        assign tdo=0; assign tdo_oe=0; assign dmi_reset_n=0;
        assign dmi_req_valid=0; assign dmi_req_op=0; assign dmi_req_address=0; assign dmi_req_data=0;
        assign dmi_rsp_ready=0;
    end else begin: enabled
        wire tap_reset_n = debug_por_n && trst_n;
        wire capture_dr, update_dr, tap_reset;
        wire [4:0] instruction;
        wire [ABITS+33:0] dr_shift;
        localparam [5:0] ADDRESS_BITS = ABITS;
        wire [31:0] dtmcs;
        wire [ABITS+33:0] dmi_capture;
        ValenceJtagTap #(.IDCODE(IDCODE), .ABITS(ABITS)) tap (
            .tck(tck), .tms(tms), .tdi(tdi), .reset_n(tap_reset_n), .tdo(tdo), .tdo_oe(tdo_oe),
            .dtmcs_capture(dtmcs), .dmi_capture(dmi_capture), .capture_dr(capture_dr),
            .update_dr(update_dr), .tap_reset(tap_reset), .instruction(instruction), .dr_shift(dr_shift));
        reg hard_reset;
        // A full TCK-period asynchronous assertion reaches the stopped domain too.
        // Either endpoint's reset deassertion remains locally synchronized.
        always @(negedge tck or negedge tap_reset_n)
            if (!tap_reset_n) hard_reset <= 1;
            else hard_reset <= tap_reset || (update_dr && instruction == 5'h10 && dr_shift[17]);
        wire transport_reset_n = tap_reset_n && !hard_reset;
        reg [1:0] sticky_status;
        reg [31:0] result_data;
        reg [ABITS-1:0] result_address;
        wire source_ready, source_busy, response_valid;
        wire [33:0] response_payload;
        wire [1:0] visible_status = sticky_status != 0 ? sticky_status :
            ((source_busy && !response_valid) ? 2'b11 : 2'b00);
        // errinfo is optional and unimplemented (zero). Version remains 1, not 2.
        assign dtmcs = {17'b0, IDLE_HINT, visible_status, ADDRESS_BITS, 4'h1};
        assign dmi_capture = {result_address, result_data, visible_status};
        wire start = update_dr && instruction == 5'h11 && sticky_status == 0 &&
            (dr_shift[1:0] == 1 || dr_shift[1:0] == 2) && source_ready;
        always @(negedge tck or negedge transport_reset_n) begin
            if (!transport_reset_n) begin sticky_status<=0; result_data<=0; result_address<=0; end
            else begin
                if (response_valid) begin
                    result_data <= response_payload[33:2];
                    if (sticky_status == 0 && response_payload[1:0] != 0)
                        sticky_status <= response_payload[1:0] == 3 ? 2'b11 : 2'b10;
                end
                if (capture_dr && instruction == 5'h11 && sticky_status == 0 &&
                    source_busy && !response_valid) sticky_status <= 2'b11;
                if (start) result_address <= dr_shift[ABITS+33:34];
                // Reserved request opcode is deliberately rejected with failure.
                if (update_dr && instruction == 5'h11 && sticky_status == 0) begin
                    if (dr_shift[1:0] == 3) sticky_status <= 2'b10;
                    else if (dr_shift[1:0] != 0 && !source_ready) sticky_status <= 2'b11;
                end
                if (update_dr && instruction == 5'h10 && dr_shift[16]) sticky_status <= 0;
            end
        end
        wire req_valid, req_ready, rsp_valid, rsp_ready;
        wire [ABITS+33:0] req_payload;
        wire [33:0] rsp_payload;
        ValenceDmiCdc #(.ABITS(ABITS)) bridge (
            .tck(tck), .debug_clk(debug_clk), .reset_n(transport_reset_n),
            .s_req_valid(start), .s_req_ready(source_ready), .s_req_payload(dr_shift),
            .s_rsp_valid(response_valid), .s_rsp_payload(response_payload), .s_rsp_ready(1'b1),
            .s_busy(source_busy), .dmi_reset_n(dmi_reset_n),
            .d_req_valid(req_valid), .d_req_ready(req_ready), .d_req_payload(req_payload),
            .d_rsp_valid(rsp_valid), .d_rsp_ready(rsp_ready), .d_rsp_payload(rsp_payload));
        if (EXTERNAL_DMI != 0) begin: external_endpoint
            assign dmi_req_valid=req_valid; assign dmi_req_op=req_payload[1:0];
            assign dmi_req_data=req_payload[33:2]; assign dmi_req_address=req_payload[ABITS+33:34];
            assign req_ready=dmi_req_ready; assign rsp_valid=dmi_rsp_valid;
            assign rsp_payload={dmi_rsp_data,dmi_rsp_status}; assign dmi_rsp_ready=rsp_ready;
        end else begin: unavailable_endpoint
            assign dmi_req_valid=0; assign dmi_req_op=0; assign dmi_req_data=0; assign dmi_req_address=0;
            assign dmi_rsp_ready=0;
            ValenceDmiUnavailable unavailable (
                .debug_clk(debug_clk), .reset_n(dmi_reset_n), .req_valid(req_valid), .req_ready(req_ready),
                .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_status(rsp_payload[1:0]),
                .rsp_data(rsp_payload[33:2]));
        end
    end endgenerate
endmodule
`default_nettype wire
