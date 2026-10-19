// SPDX-License-Identifier: Apache-2.0
// I1-only bundled mailbox adapted from debug/ValenceJtagDebugPort.sv.
// Synchronized reset releases on the edge opposite the functional registers.
`default_nettype none
module ValenceI1DmiCdc #(parameter integer ABITS = 7) (
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
    always @(posedge tck or negedge reset_n)
        if (!reset_n) source_release <= 0; else source_release <= {source_release[1:0], 1'b1};
    always @(negedge debug_clk or negedge reset_n)
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
`default_nettype wire
