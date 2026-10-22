`timescale 1ns/1ps
`default_nettype none
// Gate acknowledgement is not an inverted command. A raw-domain synchronizer
// feeds BUFGCE(SYNC). Four subsequent falling raw edges prove CE has settled
// and the last permitted full pulse ended, under the UG572 BUFGCE contract.
// Reopening is acknowledged ONLY by actual managed-clock positive edges.
// No raw edges => no new close ACK. No managed edges => no open/resumed ACK.
// The CE setup/hold path is timed, never false-pathed. UNISIM and mapped timing
// must validate this contract before any rate is admitted to software.
module native_clock_gate (
    input wire aon_clock, cold_reset, raw_clock, managed_clock,
    input wire enable,
    output wire gate_ce,
    output wire gate_closed, gate_open, resumed
);
    (* ASYNC_REG="TRUE" *) reg [2:0] raw_reset_pipe;
    always @(posedge raw_clock or posedge cold_reset)
        if (cold_reset) raw_reset_pipe<=3'b111;
        else raw_reset_pipe<={raw_reset_pipe[1:0],1'b0};
    wire raw_reset=raw_reset_pipe[2];
    (* ASYNC_REG="TRUE" *) reg [2:0] enable_sync;
    reg ce;
    reg [3:0] closed_edges;
    reg enable_seen, close_token;
    (* ASYNC_REG="TRUE" *) reg [2:0] token_sync;
    reg raw_token, closed_token;
    always @(posedge aon_clock or posedge cold_reset)
        if (cold_reset) begin enable_seen<=0; close_token<=0; end
        else begin
            enable_seen<=enable;
            if (enable_seen && !enable) close_token<=~close_token;
        end
    always @(posedge raw_clock or posedge raw_reset)
        if (raw_reset) begin enable_sync<=0; token_sync<=0; end
        else begin
            enable_sync <= {enable_sync[1:0],enable};
            token_sync <= {token_sync[1:0],close_token};
        end
    always @(negedge raw_clock or posedge raw_reset) begin
        if (raw_reset) begin ce<=0; closed_edges<=0; raw_token<=0; closed_token<=0; end
        else begin
            ce <= enable_sync[2];
            raw_token <= token_sync[2];
            if (ce || enable_sync[2] || raw_token != token_sync[2]) closed_edges <= 0;
            else begin
                closed_edges <= {closed_edges[2:0],1'b1};
                if (&closed_edges[2:0]) closed_token <= raw_token;
            end
        end
    end
    assign gate_ce = ce;
    // Async clearing is confined to evidence, not retained architectural state.
    // It removes stale restart evidence even while the destination is stopped.
    wire evidence_clear = cold_reset | ~enable;
    (* ASYNC_REG="TRUE" *) reg [3:0] managed_edges=0;
    always @(posedge managed_clock or posedge evidence_clear)
        if (evidence_clear) managed_edges <= 0;
        else managed_edges <= {managed_edges[2:0],1'b1};
    (* ASYNC_REG="TRUE" *) reg [2:0] closed_sync, token_ack_sync;
    (* ASYNC_REG="TRUE" *) reg [2:0] open_sync=0, resumed_sync=0;
    always @(posedge aon_clock or posedge cold_reset) begin
        if (cold_reset) begin closed_sync<=0; token_ack_sync<=0; end
        else begin
            closed_sync <= {closed_sync[1:0],closed_edges[3]};
            token_ack_sync <= {token_ack_sync[1:0],closed_token};
        end
    end
    always @(posedge aon_clock or posedge evidence_clear) begin
        if (evidence_clear) begin open_sync<=0; resumed_sync<=0; end
        else begin
            open_sync <= {open_sync[1:0],managed_edges[1]};
            resumed_sync <= {resumed_sync[1:0],managed_edges[3]};
        end
    end
    assign gate_closed = !enable && !enable_seen && closed_sync[2] && token_ack_sync[2] == close_token;
    assign gate_open = enable && open_sync[2];
    assign resumed = enable && resumed_sync[2];
endmodule
`default_nettype wire
