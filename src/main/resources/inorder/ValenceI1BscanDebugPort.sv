// SPDX-License-Identifier: Apache-2.0
// Optional Xilinx BSCANE2 USER DR transport. See docs/debug/bscan-user-transport.md.
// This is a custom protocol, NOT a nested RISC-V TAP or SiFive BSCAN tunnel.
`default_nettype none

// Vendor-neutral engine behind an FPGA's existing TAP. BSCAN signals retain their
// native meanings. UPDATE is a clock/event, not assumed to be an enable already
// stable at negedge TCK. Its held frame/toggle is consumed in the TCK domain.
module ValenceI1BscanUserTransport #(
    // Total board DR clocks: the 64-bit USER frame plus every other TAP's
    // BYPASS bit. OpenOCD inserts those bits and extracts the matching reply.
    // Keep the last 64 incoming bits: upstream BYPASS delay and downstream
    // padding cancel at the FPGA boundary for either physical TAP order.
    parameter integer SCAN_BITS = 64
) (
    input wire bscan_tck, input wire bscan_drck,
    input wire bscan_capture, input wire bscan_shift, input wire bscan_update,
    input wire bscan_sel, input wire bscan_reset, input wire bscan_tdi,
    output wire bscan_tdo,
    input wire debug_clk, input wire debug_por_n,
    output wire dmi_reset_n,
    output wire dmi_req_valid, input wire dmi_req_ready,
    output wire [1:0] dmi_req_op, output wire [6:0] dmi_req_address,
    output wire [31:0] dmi_req_data,
    input wire dmi_rsp_valid, output wire dmi_rsp_ready,
    input wire [1:0] dmi_rsp_status, input wire [31:0] dmi_rsp_data
);
    localparam [15:0] SIGNATURE = 16'h5642;
    localparam [3:0] VERSION = 4'h1;
    localparam integer COUNT_BITS = $clog2(SCAN_BITS + 2);
    localparam [COUNT_BITS-1:0] COUNT_LIMIT = SCAN_BITS + 1;
    initial begin
        if (SCAN_BITS < 64 || SCAN_BITS > 127)
            $fatal(1, "I1 BSCAN SCAN_BITS must be 64..127");
    end
    localparam [31:0] CAPABILITY = 32'h00000701;
    wire raw_reset_n = debug_por_n && !bscan_reset;
    reg hard_reset;
    // TAP RESET can fall before the delayed primitive TCK output. Fence the
    // functional hard-reset register at positive TCK, then release it on the
    // opposite negative edge. Only these synchronizer CLR pins are excepted.
    (* ASYNC_REG = "TRUE", SHREG_EXTRACT = "NO" *) reg [2:0] raw_release;
    always @(posedge bscan_tck or negedge raw_reset_n)
        if (!raw_reset_n) raw_release <= 0;
        else raw_release <= {raw_release[1:0], 1'b1};
    wire raw_tck_reset_n = raw_release[2];
    wire work_reset_n = raw_reset_n && !hard_reset;
    (* ASYNC_REG = "TRUE" *) reg [2:0] source_release;
    always @(negedge bscan_tck or negedge work_reset_n)
        if (!work_reset_n) source_release <= 0;
        else source_release <= {source_release[1:0], 1'b1};
    wire source_reset_n = source_release[2];

    // UPDATE rises from a falling TCK edge. Release its island on positive TCK
    // so neither reset release nor its functional qualifiers launch on the
    // capture edge. Assertion is still asynchronous, including stopped TCK.
    (* ASYNC_REG = "TRUE", SHREG_EXTRACT = "NO" *) reg [2:0] update_release;
    always @(posedge bscan_tck or negedge work_reset_n)
        if (!work_reset_n) update_release <= 0;
        else update_release <= {update_release[1:0], 1'b1};
    wire update_reset_n = update_release[2];

    reg [63:0] shift_frame;
    reg [COUNT_BITS-1:0] shift_count;
    reg scan_captured;
    wire [63:0] capture_frame;
    // The BSCANE2 already registers this input at the falling TCK edge. Adding
    // another falling-edge TDO register here would introduce a one-bit skew.
    assign bscan_tdo = bscan_sel ? shift_frame[0] : 1'b0;
    always @(posedge bscan_drck or negedge source_reset_n) begin
        if (!source_reset_n) begin
            shift_frame <= 0; shift_count <= 0; scan_captured <= 0;
        end else if (bscan_sel) begin
            if (bscan_capture) begin
                shift_frame <= capture_frame; shift_count <= 0; scan_captured <= 1;
            end else if (bscan_shift) begin
                shift_frame <= {bscan_tdi, shift_frame[63:1]};
                // Saturate one ABOVE the configured length; never wrap a long scan
                // back into a valid 64/65-bit frame.
                if (shift_count < COUNT_LIMIT) shift_count <= shift_count + 1'b1;
            end
        end
    end

    reg [63:0] update_frame;
    reg update_length_ok, update_toggle, update_overrun;
    reg update_seen;
    reg update_selected, update_ack;
    // Sample the complete qualification bundle, including negative-edge source
    // readiness and acknowledgement. No live SEL/source_release/update_seen
    // path may feed an UPDATE-clocked data or enable pin. These are related-
    // clock qualifier registers, not asynchronous data synchronizers.
    always @(posedge bscan_tck or negedge source_reset_n) begin
        if (!source_reset_n) begin
            update_selected <= 0; update_ack <= 0;
        end else begin
            update_selected <= bscan_sel && source_reset_n;
            update_ack <= update_seen;
        end
    end
    always @(posedge bscan_update or negedge update_reset_n) begin
        if (!update_reset_n) begin
            update_frame <= 0; update_length_ok <= 0; update_toggle <= 0; update_overrun <= 0;
        end else if (update_selected) begin
            // Compare the live local toggle to the sampled ACK BIT. Sampling a
            // precomputed free flag would allow two malformed UPDATE pulses
            // without intervening TCK to overwrite the first held frame.
            if (update_toggle == update_ack) begin
                update_frame <= shift_frame;
                update_length_ok <= scan_captured && shift_count == SCAN_BITS;
                update_toggle <= !update_toggle;
            end else begin
                // Cannot occur with legal BSCAN TAP sequencing: even the next
                // zero-bit DR scan gives the consumer enough TCK edges. Fail
                // closed for an invalid primitive model/wiring, preserving the
                // first held frame. Requires TAP reset or control hard reset.
                update_overrun <= 1;
            end
        end
    end

    // Related UPDATE event -> positive TCK -> negative TCK. The payload and
    // event have one held owner; this is a phase boundary, not another mailbox.
    // Do not allow a new UPDATE payload to launch into same-edge negative-TCK
    // functional data pins, even when the toggle-qualified enable is inactive.
    (* KEEP = "TRUE" *) reg [63:0] qualified_frame;
    (* KEEP = "TRUE" *) reg qualified_length_ok, qualified_overrun, qualified_toggle;
    always @(posedge bscan_tck or negedge source_reset_n) begin
        if (!source_reset_n) begin
            qualified_frame <= 0; qualified_length_ok <= 0;
            qualified_overrun <= 0; qualified_toggle <= 0;
        end else begin
            qualified_frame <= update_frame;
            qualified_length_ok <= update_length_ok;
            qualified_overrun <= update_overrun;
            qualified_toggle <= update_toggle;
        end
    end

    (* ASYNC_REG = "TRUE" *) reg [1:0] update_sync;
    reg protocol_error, result_done;
    reg [1:0] result_status;
    reg [6:0] result_address;
    reg [31:0] result_data;
    wire bridge_reset_n = source_reset_n;
    wire source_ready, source_busy, response_valid;
    wire [33:0] response_payload;
    wire consume_update = update_sync[1] != update_seen;
    wire frame_ok = qualified_length_ok && qualified_frame[63:48] == SIGNATURE &&
        qualified_frame[47:44] == VERSION && qualified_frame[43:41] == 0;
    wire [1:0] request_op = qualified_frame[1:0];
    wire [6:0] request_address = qualified_frame[40:34];
    wire request_is_dmi = request_op == 1 || request_op == 2;
    wire accept_dmi = consume_update && frame_ok && request_is_dmi &&
        !protocol_error && !qualified_overrun && source_ready;
    // UPDATE pending participates immediately, so an old DONE can never appear
    // complete while a newly updated command is still reaching the TCK domain.
    wire visible_busy = source_busy || update_toggle != update_seen;
    wire visible_error = protocol_error || update_overrun;
    wire [1:0] visible_status = visible_busy ? 2'b11 :
        visible_error ? 2'b10 : result_status;
    assign capture_frame = {SIGNATURE, VERSION, visible_error, visible_busy,
        result_done, result_address, result_data, visible_status};

    // A full TCK-period assertion reaches a stopped destination too. Reset all
    // event toggles together; never release a stale event into a fresh mailbox.
    wire hard_reset_command = consume_update && frame_ok && request_op == 3 &&
        request_address == 2 && qualified_frame[33:2] == 0;
    always @(negedge bscan_tck or negedge raw_tck_reset_n)
        if (!raw_tck_reset_n) hard_reset <= 0;
        else hard_reset <= hard_reset_command;

    always @(negedge bscan_tck or negedge update_reset_n) begin
        if (!update_reset_n) begin
            update_sync <= 0; update_seen <= 0;
            protocol_error <= 0; result_done <= 0; result_status <= 0;
            result_address <= 0; result_data <= 0;
        end else begin
            update_sync <= {update_sync[0], qualified_toggle};
            if (response_valid) begin
                result_done <= 1;
                result_data <= response_payload[33:2];
                // An endpoint's reserved/failed/busy response is a completed
                // failure here; physical transport busy is represented above.
                result_status <= response_payload[1:0] == 0 ? 2'b00 : 2'b10;
            end
            if (consume_update) begin
                update_seen <= update_sync[1];
                if (!frame_ok) begin
                    protocol_error <= 1;
                end else if (request_op == 0) begin
                    // NOP/poll: safe while busy and never consumes the result.
                end else if (hard_reset_command) begin
                    // Intentional cancellation, never an automatic timeout
                    // retry. An already accepted memory write is not undone.
                    protocol_error <= 0; result_done <= 0; result_status <= 0;
                    result_address <= 0; result_data <= 0;
                end else if (request_op == 3 && request_address == 1 &&
                             qualified_frame[33:2] == 0 && source_ready) begin
                    protocol_error <= 0; result_done <= 0; result_status <= 0;
                    result_address <= 0; result_data <= 0;
                end else if (protocol_error || qualified_overrun || !source_ready) begin
                    protocol_error <= 1;
                end else if (request_op == 3 && request_address == 0 &&
                             qualified_frame[33:2] == 0) begin
                    result_done <= 1; result_status <= 0;
                    result_address <= 0; result_data <= CAPABILITY;
                end else if (accept_dmi) begin
                    result_done <= 0; result_status <= 0;
                    result_address <= request_address; result_data <= 0;
                end else begin
                    protocol_error <= 1;
                end
            end
        end
    end

    wire [40:0] request_payload;
    ValenceI1DmiCdc #(.ABITS(7)) bridge (
        .tck(bscan_tck), .debug_clk(debug_clk), .reset_n(bridge_reset_n),
        .s_req_valid(accept_dmi), .s_req_ready(source_ready), .s_req_payload(qualified_frame[40:0]),
        .s_rsp_valid(response_valid), .s_rsp_payload(response_payload), .s_rsp_ready(1'b1),
        .s_busy(source_busy), .dmi_reset_n(dmi_reset_n),
        .d_req_valid(dmi_req_valid), .d_req_ready(dmi_req_ready), .d_req_payload(request_payload),
        .d_rsp_valid(dmi_rsp_valid), .d_rsp_ready(dmi_rsp_ready),
        .d_rsp_payload({dmi_rsp_data, dmi_rsp_status}));
    assign dmi_req_op = request_payload[1:0];
    assign dmi_req_data = request_payload[33:2];
    assign dmi_req_address = request_payload[40:34];
endmodule

// Real primitive wrapper for UltraScale+ (including the repository's ZU15EG)
// and 7-series devices supporting BSCANE2. No new package pins are introduced.
// Selecting ENABLE=0 removes the primitive and transport entirely. An enabled
// board must explicitly allocate a free USER chain; JTAG_CHAIN=0 is invalid.
module ValenceI1BscanDebugPort #(
    parameter integer ENABLE = 0,
    parameter integer JTAG_CHAIN = 0,
    parameter integer SCAN_BITS = 64
) (
    input wire debug_clk, input wire debug_por_n,
    output wire dmi_reset_n,
    output wire dmi_req_valid, input wire dmi_req_ready,
    output wire [1:0] dmi_req_op, output wire [6:0] dmi_req_address,
    output wire [31:0] dmi_req_data,
    input wire dmi_rsp_valid, output wire dmi_rsp_ready,
    input wire [1:0] dmi_rsp_status, input wire [31:0] dmi_rsp_data
);
    generate if (ENABLE == 0) begin: disabled
        assign dmi_reset_n = 0;
        assign dmi_req_valid = 0; assign dmi_req_op = 0;
        assign dmi_req_address = 0; assign dmi_req_data = 0; assign dmi_rsp_ready = 0;
    end else begin: enabled
        wire capture, drck, reset, sel, shift, tck, tdi, update, tdo;
        if (JTAG_CHAIN < 1 || JTAG_CHAIN > 4) begin: invalid_chain
            initial $fatal(1, "Enabled BSCAN requires explicit free JTAG_CHAIN in 1..4");
        end
        BSCANE2 #(.JTAG_CHAIN(JTAG_CHAIN)) user_scan (
            .CAPTURE(capture), .DRCK(drck), .RESET(reset), .RUNTEST(), .SEL(sel),
            .SHIFT(shift), .TCK(tck), .TDI(tdi), .TMS(), .UPDATE(update), .TDO(tdo));
        ValenceI1BscanUserTransport #(.SCAN_BITS(SCAN_BITS)) transport (
            .bscan_tck(tck), .bscan_drck(drck), .bscan_capture(capture),
            .bscan_shift(shift), .bscan_update(update), .bscan_sel(sel),
            .bscan_reset(reset), .bscan_tdi(tdi), .bscan_tdo(tdo),
            .debug_clk(debug_clk), .debug_por_n(debug_por_n), .dmi_reset_n(dmi_reset_n),
            .dmi_req_valid(dmi_req_valid), .dmi_req_ready(dmi_req_ready),
            .dmi_req_op(dmi_req_op), .dmi_req_address(dmi_req_address), .dmi_req_data(dmi_req_data),
            .dmi_rsp_valid(dmi_rsp_valid), .dmi_rsp_ready(dmi_rsp_ready),
            .dmi_rsp_status(dmi_rsp_status), .dmi_rsp_data(dmi_rsp_data));
    end endgenerate
endmodule
`default_nettype wire
